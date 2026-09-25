#!/usr/bin/env python3
"""Apply a reviewed complete package overlay in the existing workspace.

Only package recipe files, their reviewed inventory and recovery records change.
Solving, installing and module publication are separate explicit operations.
"""
import argparse
import importlib.util
import json
import keyword
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True


def sibling(name, module_name):
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recovery = sibling("overlay-recovery.py", "cse_overlay_recovery_shared")
gate = recovery.inventory_helper()
Error = recovery.RecoveryError
INVENTORY = "package-repos/overlay-inventory.json"
FINISHED = {"applied", "restored", "cancelled"}


def maintenance(workspace):
    return sibling("workspace-build.py", "cse_workspace_build_shared").maintenance_lock(workspace)


def require_build_idle(workspace):
    sibling("workspace-build.py", "cse_workspace_build_shared").require_recovery_idle(workspace)


def package_module(package):
    module = package.replace("-", "_")
    if module[0].isdigit() or keyword.iskeyword(module) or module in ("async", "await"):
        module = "_" + module
    return module


def safe_workspace(workspace):
    workspace = Path(workspace).resolve()
    prepared = os.environ.get("CSE_BUILD_WORKSPACE")
    if prepared and Path(prepared).resolve() != workspace:
        raise Error("--workspace does not match the prepared CSE shell")
    if not (workspace / "environments").is_dir():
        raise Error("Missing recorded workspace environments")
    for relative in (".cse-overlay", "package-repos"):
        if (workspace / relative).is_symlink():
            raise Error("Workspace overlay state/input path is a symlink: " + relative)
    return workspace


def records(workspace):
    result = []
    journal = workspace / ".cse-overlay"
    if not journal.exists():
        return result
    for directory in sorted(journal.iterdir()):
        if directory.is_symlink() or not directory.is_dir():
            raise Error("Unexpected entry in overlay journal: " + str(directory))
        path = directory / "record.json"
        if path.is_symlink() or not path.is_file():
            raise Error("Incomplete overlay journal: " + str(directory))
        value = json.loads(path.read_text())
        if (value.get("schema_version") != 1 or value.get("id") != directory.name
                or value.get("workspace") != str(workspace)):
            raise Error("Overlay journal identity mismatch: " + str(path))
        repository = value.get("repository", "cse_trials")
        if not re.fullmatch(r"[A-Za-z_]\w*", repository):
            raise Error("Unsafe overlay journal repository: " + str(path))
        if value.get("operation") == "reconcile":
            packages = value.get("packages")
            if (not isinstance(packages, dict) or not packages
                    or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
                           or state not in ("new", "changed", "already-recorded")
                           for name, state in packages.items())):
                raise Error("Invalid overlay reconciliation record: " + str(path))
        elif (not re.fullmatch(r"[A-Za-z_]\w*", value.get("module", ""))
              or value.get("target") != "package-repos/spack_repo/" + repository
              + "/packages/" + value.get("module", "")):
            raise Error("Unsafe overlay journal package path: " + str(path))
        result.append(value)
    return result


def ready(workspace, except_record=None):
    for record in records(workspace):
        if record["status"] not in FINISHED and record["id"] != except_record:
            raise Error("Incomplete overlay transaction " + record["id"]
                        + "; restore it before another workspace operation")


def save(workspace, record):
    recovery.atomic_write(workspace / ".cse-overlay" / record["id"] / "record.json",
                          recovery.json_bytes(record))


def fingerprint(path):
    if path.is_symlink():
        raise Error("Unsafe symlink: " + str(path))
    if not path.exists():
        return None
    return recovery.safe_files(path) if path.is_dir() else recovery.digest(path.read_bytes())


def protected_inputs(workspace, target=None):
    result = recovery.inputs(workspace)
    for tree in ("modulefiles", "presentation"):
        path = workspace / tree
        if path.exists():
            result.update((tree + "/" + name, value)
                          for name, value in recovery.safe_files(path).items())
    return {name: value for name, value in result.items()
            if name != INVENTORY and (target is None or not name.startswith(target + "/"))}


def validate_repository(workspace, repository=None, check_inventory=True):
    root = workspace / "package-repos"
    inventory = gate.snapshot(root)
    inventory_path = root / gate.INVENTORY
    if not inventory_path.exists() and any(item["status"] == "applied" for item in records(workspace)):
        raise Error("Reviewed inventory disappeared after overlay apply; restore the matching record")
    if check_inventory and (inventory_path.exists() or inventory_path.is_symlink()):
        errors = gate.check(root)
        if errors:
            raise Error("Current overlay inventory failed: " + "; ".join(errors))
    recovery.scoped_inputs(workspace)
    if repository is None:
        return root
    if not re.fullmatch(r"[A-Za-z_]\w*", repository):
        raise Error("Unsafe repository namespace")
    matches = [repo for repo in inventory["repositories"]
               if repo["namespace"] == repository and repo["api"] == "v2.0"]
    if len(matches) != 1 or matches[0]["path"] != "spack_repo/" + repository:
        raise Error("Expected the recorded " + repository + " API v2 repository")
    config = recovery.read_yaml(workspace / "configs/common/repos.yaml")
    entry = config.get("repos", {}).get(repository)
    if not isinstance(entry, str) or (workspace / "configs/common" / entry).resolve() != root / matches[0]["path"]:
        raise Error("The existing repos.yaml does not register this " + repository + " repository")
    return root / matches[0]["path"]


def select_environment(workspace, environment):
    if environment is None:
        return
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", environment)
            or ".." in environment.split("/")
            or not (workspace / "environments" / environment / "spack.yaml").is_file()):
        raise Error("--environment must name an existing compiler/lane")


def impact(workspace, before_repo, after_repo, module, package):
    old_broad, old_uncertain, old_modules = recovery.local_impact(before_repo, module, package)
    new_broad, new_uncertain, new_modules = recovery.local_impact(after_repo, module, package)
    providers = (recovery.provider_directives(before_repo / "packages" / module / "package.py")
                 != recovery.provider_directives(after_repo / "packages" / module / "package.py"))
    broad = old_broad or new_broad or providers
    result = {"affected": [], "unchanged": [], "unlocked": [], "affected_lock_sha256": {},
              "provider_directives_changed": providers,
              "uncertain_recipe_imports": sorted(set(old_uncertain + new_uncertain)),
              "impacted_local_modules": sorted(set(old_modules + new_modules)),
              "scope_reason": "old/new imports, dynamic lookup or provider changes; all locks"
              if broad else "locks containing the corrected package"}
    for path in sorted((workspace / "environments").glob("*/*/spack.yaml")):
        name = path.parent.relative_to(workspace / "environments").as_posix()
        lock = path.with_name("spack.lock")
        if not lock.exists():
            result["unlocked"].append(name)
        elif broad or any(node["name"] == package for node in recovery.lock_nodes(lock).values()):
            result["affected"].append(name)
            result["affected_lock_sha256"][name] = recovery.digest(lock.read_bytes())
        else:
            result["unchanged"].append(name)
    return result


def prepare_correction(workspace, source, package, environment, staging, repository):
    if source.is_symlink():
        raise Error("The corrected package directory is a symlink")
    source = source.resolve()
    if not (source / "package.py").is_file():
        raise Error("--from must name a complete package directory containing package.py")
    inferred = source.name.lstrip("_").replace("_", "-")
    package = package or inferred
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", package):
        raise Error("Use --package NAME or an API v2 package directory name")
    module = package_module(package)
    select_environment(workspace, environment)
    repo = validate_repository(workspace, repository)
    target = repo / "packages" / module
    if source == target.resolve():
        raise Error("Use edit or a separate complete package directory; do not edit live recipes before apply")
    source_files = recovery.safe_files(source)
    before_package = fingerprint(target)
    if before_package == source_files:
        raise Error("Correction is identical to the current overlay")
    before_inventory = fingerprint(workspace / INVENTORY)
    # Validate the whole proposed repository before changing any live recipe.
    candidate_root = staging / "package-repos"
    shutil.copytree(str(workspace / "package-repos"), str(candidate_root))
    after_repo = candidate_root / "spack_repo" / repository
    candidate = after_repo / "packages" / module
    if candidate.exists():
        shutil.rmtree(str(candidate))
    shutil.copytree(str(source), str(candidate))
    new_inventory = gate.snapshot(candidate_root)
    (candidate_root / gate.INVENTORY).write_bytes(recovery.json_bytes(new_inventory))
    target_name = target.relative_to(workspace).as_posix()
    result = {"package": package, "module": module, "repository": repository, "target": target_name,
              "environment": environment, "source": str(source),
              "package_before": before_package, "package_after": source_files,
              "inventory_before": before_inventory,
              "inventory_after": recovery.digest((candidate_root / gate.INVENTORY).read_bytes()),
              "protected_inputs": protected_inputs(workspace, target_name), "resolved": {}}
    result.update(impact(workspace, repo, after_repo, module, package))
    return result, candidate, candidate_root / gate.INVENTORY


def new_record(workspace, prepared, status="preparing"):
    journal = workspace / ".cse-overlay"
    journal.mkdir(exist_ok=True)
    identifier = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:12]
    directory = journal / identifier
    directory.mkdir()
    record = dict(prepared, schema_version=1, id=identifier, workspace=str(workspace),
                  created=time.time(), status=status)
    save(workspace, record)
    return record, directory


def transaction_paths(record):
    inventory = ("inventory", INVENTORY, "inventory_before", "inventory_after")
    if record.get("operation") == "reconcile":
        return (inventory,)
    return (("package", record["target"], "package_before", "package_after"), inventory)


def restore_bytes(workspace, record):
    """Recover only the exact transaction-owned paths, retaining new bytes."""
    directory = workspace / ".cse-overlay" / record["id"]
    for label, relative, old_key, new_key in transaction_paths(record):
        live = workspace / relative
        current, old, new = fingerprint(live), record[old_key], record[new_key]
        if current == old:
            continue
        if current not in (None, new):
            raise Error("Later edits prevent overlay restoration: " + str(live))
        backup = directory / "original" / label
        if old is not None and fingerprint(backup) != old:
            raise Error("Original overlay backup is missing or changed: " + str(backup))
        if current is not None:
            retained = directory / ("replaced-" + label + "-" + uuid.uuid4().hex[:8])
            os.replace(str(live), str(retained))
        if old is not None:
            os.replace(str(backup), str(live))


def apply_overlay(workspace, source, package=None, environment=None, dry_run=False,
                  edit_record=None, repository="cse_trials"):
    workspace = safe_workspace(workspace)
    with maintenance(workspace):
        require_build_idle(workspace)
        ready(workspace, edit_record)
        with tempfile.TemporaryDirectory(prefix="cse-overlay-validation-") as temporary:
            prepared, staged_package, staged_inventory = prepare_correction(
                workspace, Path(source), package, environment, Path(temporary), repository)
            if dry_run:
                return dict(prepared, status="dry-run")
            if edit_record:
                record = next(item for item in records(workspace) if item["id"] == edit_record)
                if record["status"] != "editing":
                    raise Error("Editable overlay transaction is no longer active")
                if protected_inputs(workspace, record["target"]) != record["protected_inputs"]:
                    raise Error("Workspace changed during editing")
                if (prepared["package_before"] != record["package_before"]
                        or prepared["inventory_before"] != record["inventory_before"]):
                    raise Error("Recipe or inventory changed during editing")
                directory = workspace / ".cse-overlay" / edit_record
                record.update(prepared, status="preparing")
                save(workspace, record)
            else:
                record, directory = new_record(workspace, prepared)
            try:
                stage = directory / "stage"
                stage.mkdir()
                shutil.copytree(str(staged_package), str(stage / "package"))
                shutil.copy2(str(staged_inventory), str(stage / "inventory"))
                (directory / "original").mkdir()
                if (protected_inputs(workspace, record["target"]) != record["protected_inputs"]
                        or fingerprint(workspace / record["target"]) != record["package_before"]
                        or fingerprint(workspace / INVENTORY) != record["inventory_before"]
                        or recovery.safe_files(Path(source)) != record["package_after"]):
                    raise Error("Workspace or reviewed correction changed during staging")
                record["status"] = "applying"
                save(workspace, record)
                for label, relative in (("package", record["target"]), ("inventory", INVENTORY)):
                    live = workspace / relative
                    live.parent.mkdir(parents=True, exist_ok=True)
                    if live.exists():
                        os.replace(str(live), str(directory / "original" / label))
                    os.replace(str(stage / label), str(live))
                if gate.check(workspace / "package-repos"):
                    raise Error("Applied overlay did not match its reviewed inventory")
                if protected_inputs(workspace, record["target"]) != record["protected_inputs"]:
                    raise Error("Unrelated workspace inputs changed during apply")
                record["status"] = "applied"
                save(workspace, record)
            except BaseException:
                try:
                    restore_bytes(workspace, record)
                    record["status"] = "restored"
                except BaseException as rollback_error:
                    record["status"] = "restore_failed"
                    record["restore_error"] = str(rollback_error)
                save(workspace, record)
                raise
            return record


def reconcile_overlay(workspace, packages, dry_run=False, repository="cse_trials"):
    """Explicitly register named live edits without pretending to own prior bytes."""
    workspace = safe_workspace(workspace)
    if not packages or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) for name in packages):
        raise Error("reconcile requires explicit --package NAME selections")
    with maintenance(workspace):
        require_build_idle(workspace)
        ready(workspace)
        repo = validate_repository(workspace, repository, check_inventory=False)
        inventory_path = workspace / INVENTORY
        before = fingerprint(inventory_path)
        if before is None:
            raise Error("Missing overlay inventory; refresh startup controls before reconciliation")
        old = gate.validate_inventory(json.loads(inventory_path.read_text(),
                                                 object_pairs_hook=gate.unique_object))
        current = gate.snapshot(workspace / "package-repos")

        def identities(document):
            return {item["path"]: (item["namespace"], item["api"])
                    for item in document["repositories"]}

        def files(document):
            return {item["path"] + "/" + name: digest
                    for item in document["repositories"] for name, digest in item["files"].items()}

        if identities(old) != identities(current):
            raise Error("Reconciliation cannot change repository identities")
        expected, actual = files(old), files(current)
        base = repo.relative_to(workspace / "package-repos").as_posix() + "/packages/"
        prefixes = {name: base + package_module(name) + "/" for name in sorted(set(packages))}
        changed = sorted(name for name in set(expected) | set(actual)
                         if expected.get(name) != actual.get(name))
        unrelated = [name for name in changed if not any(name.startswith(prefix) for prefix in prefixes.values())]
        if unrelated:
            raise Error("Changes outside selected packages: " + ", ".join(unrelated))
        states = {}
        for package, prefix in prefixes.items():
            if prefix + "package.py" not in actual:
                raise Error("Selected overlay recipe is missing: " + prefix + "package.py")
            old_files = {name: digest for name, digest in expected.items() if name.startswith(prefix)}
            new_files = {name: digest for name, digest in actual.items() if name.startswith(prefix)}
            states[package] = "new" if not old_files else "changed" if old_files != new_files else "already-recorded"
        prepared = {"operation": "reconcile", "repository": repository, "packages": states,
                    "inventory_before": before, "protected_inputs": protected_inputs(workspace),
                    "affected": [], "unchanged": [], "unlocked": [], "affected_lock_sha256": {},
                    "resolved": {}, "changed_files": changed,
                    "scope_reason": "historical recipe bytes unavailable; conservatively flag all existing locks"}
        if not changed:
            return dict(prepared, status="already-recorded")
        for path in sorted((workspace / "environments").glob("*/*/spack.yaml")):
            name = path.parent.relative_to(workspace / "environments").as_posix()
            lock = fingerprint(path.with_name("spack.lock"))
            prepared["unlocked" if lock is None else "affected"].append(name)
            if lock is not None:
                prepared["affected_lock_sha256"][name] = lock
        data = recovery.json_bytes(current)
        prepared["inventory_after"] = recovery.digest(data)
        if dry_run:
            return dict(prepared, status="dry-run")
        record, directory = new_record(workspace, prepared)
        try:
            original = directory / "original"
            original.mkdir()
            shutil.copy2(str(inventory_path), str(original / "inventory"))
            stage = directory / "inventory"
            stage.write_bytes(data)
            shutil.copymode(str(inventory_path), str(stage))
            if (protected_inputs(workspace) != prepared["protected_inputs"]
                    or fingerprint(inventory_path) != before
                    or fingerprint(original / "inventory") != before):
                raise Error("Workspace changed during overlay reconciliation")
            record["status"] = "applying"
            save(workspace, record)
            os.replace(str(stage), str(inventory_path))
            if (gate.check(workspace / "package-repos")
                    or protected_inputs(workspace) != prepared["protected_inputs"]):
                raise Error("Workspace changed during overlay reconciliation")
            record["status"] = "applied"
            save(workspace, record)
        except BaseException:
            try:
                restore_bytes(workspace, record)
                record["status"] = "restored"
            except BaseException as rollback_error:
                record["status"] = "restore_failed"
                record["restore_error"] = str(rollback_error)
            save(workspace, record)
            raise
        return record


def restore_overlay(workspace, identifier):
    workspace = safe_workspace(workspace)
    with maintenance(workspace):
        require_build_idle(workspace)
        ready(workspace, identifier)
        matches = [item for item in records(workspace) if item["id"] == identifier]
        if len(matches) != 1:
            raise Error("Unknown overlay record: " + identifier)
        record = matches[0]
        if record["status"] in ("restored", "cancelled"):
            return record
        if protected_inputs(workspace, record.get("target")) != record["protected_inputs"]:
            if record.get("operation") == "reconcile":
                raise Error("Later workspace/lock changes prevent inventory-only restoration")
            raise Error("Later workspace/lock changes prevent recipe-only restoration; "
                        "apply the retained previous package as a new correction, then reconcretize the selected environment")
        for _, relative, before, after in transaction_paths(record):
            current = fingerprint(workspace / relative)
            allowed = (record[after],) if record["status"] == "applied" else (None, record[before], record[after])
            if current not in allowed:
                raise Error("Later edits prevent overlay restoration: " + relative)
        record["status"] = "restoring"
        save(workspace, record)
        try:
            restore_bytes(workspace, record)
            record["status"] = "restored"
        except BaseException:
            record["status"] = "restore_failed"
            save(workspace, record)
            raise
        save(workspace, record)
        return record


def check_workspace(workspace, environments, action="build"):
    workspace = safe_workspace(workspace)
    with maintenance(workspace):
        ready(workspace)
        validate_repository(workspace)
        pending = []
        for environment in environments:
            select_environment(workspace, environment)
            lock = workspace / "environments" / environment / "spack.lock"
            current = fingerprint(lock)
            for record in records(workspace):
                if record["status"] != "applied" or environment not in record["affected"]:
                    continue
                proof = record.get("resolved", {}).get(environment)
                if not proof or proof["lock_sha256"] != current:
                    pending.append(environment + " (overlay " + record["id"] + ")")
        if pending and action == "build":
            raise Error("Recipe changes require explicit selected reconcretization before build: "
                        + ", ".join(pending))
        return pending


def mark_resolved(workspace, environment):
    workspace = safe_workspace(workspace)
    with maintenance(workspace):
        ready(workspace)
        validate_repository(workspace)
        select_environment(workspace, environment)
        lock = workspace / "environments" / environment / "spack.lock"
        recovery.load_lock(lock)
        proof = {"lock_sha256": fingerprint(lock), "inventory_sha256": fingerprint(workspace / INVENTORY),
                 "resolved_at": time.time()}
        changed = []
        for record in records(workspace):
            if record["status"] == "applied" and environment in record["affected"]:
                record.setdefault("resolved", {})[environment] = proof
                save(workspace, record)
                changed.append(record["id"])
        return changed


def located_package(workspace, environment, package, spack, repo):
    if not spack:
        raise Error("Use the prepared Spack shell or --spack to locate the pinned builtin package")
    identity = {"spack": recovery.spack_identity(spack)}
    command = [str(spack), "-e", str(workspace / "environments" / environment), "location"]
    environment_vars = os.environ.copy()
    environment_vars.pop("SPACK_ENV", None)
    environment_vars.update(SPACK_DISABLE_LOCAL_CONFIG="true", PYTHONDONTWRITEBYTECODE="1")

    def locate(arguments):
        output = subprocess.check_output(command + arguments, env=environment_vars,
                                         universal_newlines=True).strip().splitlines()
        if not output:
            raise Error("Spack did not report the package/repository location")
        return Path(output[-1]).resolve()

    source = locate(["--package-dir", package])
    if source.name.lstrip("_").replace("_", "-") != package:
        raise Error("Spack selected an unexpected package directory: " + str(source))
    if source.parent == repo / "packages":
        return source, identity
    builtin = locate(["--repo", "builtin"])
    if source.parent != builtin / "packages":
        raise Error("Selected package is outside the recorded overlay and builtin repository")
    config = recovery.read_yaml(workspace / "configs/common/repos.yaml").get("repos", {}).get("builtin")
    if not isinstance(config, dict) or not config.get("git") or not (config.get("commit") or config.get("tag")):
        raise Error("Builtin repository lacks recorded source and commit/tag provenance")

    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(builtin)] + list(arguments),
                                       universal_newlines=True).strip()

    head, origin = git("rev-parse", "HEAD"), git("remote", "get-url", "origin")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise Error("Builtin repository has tracked modifications")
    if origin != config["git"] or (config.get("commit") and config["commit"] != head):
        raise Error("Builtin repository does not match recorded provenance")
    if config.get("tag") and git("rev-parse", str(config["tag"]) + "^{commit}") != head:
        raise Error("Builtin repository tag does not identify its current commit")
    identity["builtin"] = {"path": str(builtin), "source": origin, "commit": head,
                           "recorded_tag": config.get("tag")}
    return source, identity


def edit_overlay(workspace, package, environment, spack, editor=None, repository="cse_trials"):
    workspace = safe_workspace(workspace)
    select_environment(workspace, environment)
    if not environment or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", package):
        raise Error("edit requires --package and --environment")
    editor = editor or os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        raise Error("Set EDITOR (or VISUAL) to the on-system editor command first")
    with maintenance(workspace):
        require_build_idle(workspace)
        ready(workspace)
        repo = validate_repository(workspace, repository)
        module = package_module(package)
        source = repo / "packages" / module
        identity = None
        if not source.is_dir():
            source, identity = located_package(workspace, environment, package, spack, repo)
            module = source.name
        recovery.safe_files(source)
        target = "package-repos/spack_repo/" + repository + "/packages/" + module
        prepared = {"package": package, "module": module, "repository": repository, "target": target,
                    "environment": environment, "source": str(source), "spack_identity": identity,
                    "package_before": fingerprint(workspace / target),
                    "package_after": fingerprint(workspace / target),
                    "inventory_before": fingerprint(workspace / INVENTORY),
                    "inventory_after": fingerprint(workspace / INVENTORY),
                    "protected_inputs": protected_inputs(workspace, target), "affected": [], "resolved": {}}
        record, directory = new_record(workspace, prepared, "editing")
        editable = directory / "editable" / module
        editable.parent.mkdir()
        shutil.copytree(str(source), str(editable))
        backup = directory / "edit-original" / module
        backup.parent.mkdir()
        shutil.copytree(str(source), str(backup))
    # The unfinished record blocks other participating commands during editing.
    # A generated launcher may additionally retain its inherited operation lock.
    try:
        result = subprocess.call(shlex.split(editor) + [str(editable / "package.py")])
        if result:
            raise Error("Editor failed; correction retained at " + str(editable))
        if recovery.safe_files(editable) == recovery.safe_files(backup):
            with maintenance(workspace):
                record["status"] = "cancelled"
                save(workspace, record)
            return record
        return apply_overlay(workspace, editable, package, environment,
                             edit_record=record["id"], repository=repository)
    except BaseException:
        print("Editable correction retained: " + str(editable)
              + "; use restore --record " + record["id"] + " to cancel the incomplete edit", file=sys.stderr)
        raise


def print_record(record):
    print("Overlay " + record.get("id", "preview") + ": " + record["status"])
    for package, state in sorted(record.get("packages", {}).items()):
        print(package + ": " + state)
    for path in record.get("changed_files", []):
        print("inventory change: " + path)
    if record.get("operation") == "reconcile":
        print("Recipe files and locks are unchanged. Restore rolls back only inventory registration.")
        if record.get("affected"):
            print("Existing locks require selected reconcretization before another build; "
                  "historical recipe bytes were unavailable for a narrower impact comparison.")
    for key in ("affected", "unchanged", "unlocked"):
        if key in record:
            print(key + ": " + (", ".join(record[key]) or "none"))
    if record.get("environment") and record["status"] == "applied":
        print("Next: ./cse-build login concretize --environment " + record["environment"] + " --reconcretize")
        print("Then: ./cse-build compute resume --environment " + record["environment"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action")
    for name in ("apply", "edit", "reconcile", "restore", "status", "check", "resolved"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, default=os.environ.get("CSE_BUILD_WORKSPACE"))
        if name in ("apply", "edit"):
            command.add_argument("--repository", default="cse_trials")
            command.add_argument("--package", required=name == "edit")
            command.add_argument("--environment", required=name == "edit")
        if name == "apply":
            command.add_argument("--from", type=Path, dest="source", required=True)
            command.add_argument("--dry-run", action="store_true")
        if name == "reconcile":
            command.add_argument("--repository", default="cse_trials")
            command.add_argument("--package", action="append", required=True)
            command.add_argument("--dry-run", action="store_true")
        if name == "edit":
            default = str(Path(os.environ["SPACK_ROOT"]) / "bin/spack") if os.environ.get("SPACK_ROOT") else shutil.which("spack")
            command.add_argument("--spack", default=default)
        if name in ("restore", "status"):
            command.add_argument("--record", required=name == "restore")
        if name in ("check", "resolved"):
            command.add_argument("--environment", required=True, action="append" if name == "check" else "store")
        if name == "check":
            command.add_argument("--action", choices=("build", "concretize"), default="build", dest="operation")
    args = parser.parse_args()
    if not args.action or not args.workspace:
        parser.error("select an action and use the prepared CSE shell or --workspace")
    try:
        if args.action == "apply":
            print_record(apply_overlay(args.workspace, args.source, args.package, args.environment,
                                       args.dry_run, repository=args.repository))
        elif args.action == "edit":
            print_record(edit_overlay(args.workspace, args.package, args.environment, args.spack,
                                      repository=args.repository))
        elif args.action == "reconcile":
            print_record(reconcile_overlay(args.workspace, args.package, args.dry_run, args.repository))
        elif args.action == "restore":
            print_record(restore_overlay(args.workspace, args.record))
        elif args.action == "status":
            workspace = safe_workspace(args.workspace)
            with maintenance(workspace):
                for record in records(workspace):
                    if not args.record or record["id"] == args.record:
                        print_record(record)
        elif args.action == "check":
            pending = check_workspace(args.workspace, args.environment, args.operation)
            print("Pending selected overlay solves: " + (", ".join(pending) or "none"))
        elif args.action == "resolved":
            print("Recorded selected solve for overlay records: "
                  + ", ".join(mark_resolved(args.workspace, args.environment)))
        return 0
    except (Error, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("workspace-overlay: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
