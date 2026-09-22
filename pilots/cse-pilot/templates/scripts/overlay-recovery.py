#!/usr/bin/env python3
"""Recover a failed locked build in an isolated candidate, using pinned Spack.

Run with `spack python overlay-recovery.py` in the existing prepared build shell.
No command changes the source workspace, its locks, views, modules or prefixes.
"""
import argparse
import ast
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time

try:
    import spack.util.spack_yaml as yaml
except ImportError:
    import yaml


class RecoveryError(ValueError):
    pass


class TerminationRequested(BaseException):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def read_yaml(path):
    with path.open() as stream:
        return yaml.load_config(stream) if hasattr(yaml, "load_config") else yaml.safe_load(stream)


def write_yaml(path, value):
    if hasattr(yaml, "dump_config"):
        path.write_text(yaml.dump_config(value))
    else:
        rendered = yaml.safe_dump(value, sort_keys=False)
        # PyYAML represents Spack override keys as quoted strings. Restore the
        # double-colon spelling so a later real Spack process sees the override.
        rendered = re.sub(
            r"^(\s*)'([A-Za-z_][A-Za-z_0-9-]*):':", r"\1\2::", rendered,
            flags=re.MULTILINE,
        )
        path.write_text(rendered)


def atomic_write(path, data):
    temporary = path.with_name("." + path.name + ".recovery-tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def save(candidate, record):
    atomic_write(candidate / "recovery.json", json_bytes(record))


def safe_files(root):
    if root.is_symlink() or not root.is_dir():
        raise RecoveryError("expected a real directory: " + str(root))
    result = {}
    for directory, dirs, names in os.walk(str(root)):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink():
                raise RecoveryError("input symlinks are unsupported: " + str(path))
        for name in names:
            path = Path(directory) / name
            if not path.is_file():
                raise RecoveryError("non-regular input: " + str(path))
            result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def inputs(workspace):
    result = {}
    for tree in ("configs", "catalog", "package-repos"):
        root = workspace / tree
        if root.exists():
            result.update((tree + "/" + name, value) for name, value in safe_files(root).items())
    environments = workspace / "environments"
    if environments.is_symlink():
        raise RecoveryError("environment tree is a symlink")
    for path in environments.glob("*/*/spack.*"):
        if path.name not in ("spack.yaml", "spack.lock"):
            continue
        if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
            raise RecoveryError("environment input is a symlink: " + str(path))
        result[path.relative_to(workspace).as_posix()] = digest(path.read_bytes())
    manifest = workspace / "workspace-manifest.yaml"
    if manifest.exists():
        if manifest.is_symlink():
            raise RecoveryError("workspace manifest is a symlink")
        result[manifest.name] = digest(manifest.read_bytes())
    return result


def inventory_helper():
    path = Path(__file__).with_name("verify-overlay-inputs.py")
    spec = importlib.util.spec_from_file_location("overlay_inventory", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_lock(path):
    document = json.loads(path.read_text())
    if document.get("_meta", {}).get("lockfile-version") != 6:
        raise RecoveryError("expected Spack 1.2.2 lockfile version 6: " + str(path))
    nodes = document.get("concrete_specs")
    if not isinstance(nodes, dict) or not nodes:
        raise RecoveryError("unsupported or empty lock: " + str(path))
    for key, node in nodes.items():
        if not re.fullmatch("[a-z2-7]{32}", key) or not isinstance(node, dict) or not node.get("name"):
            raise RecoveryError("invalid concrete lock node: " + str(path))
    return document, nodes


def lock_nodes(path):
    return load_lock(path)[1]


def scoped_inputs(workspace):
    """Only self-contained local includes are safe to copy without rendering."""
    paths = list((workspace / "environments").glob("*/*/spack.yaml"))
    paths += list((workspace / "configs").rglob("*.yaml"))
    paths += list((workspace / "catalog").rglob("*.yaml"))
    for path in paths:
        value = read_yaml(path)
        if not isinstance(value, dict):
            raise RecoveryError("expected a YAML mapping: " + str(path))
        body = value.get("spack", value)
        if not isinstance(body, dict):
            raise RecoveryError("expected a Spack YAML mapping: " + str(path))
        for key, includes in body.items():
            if str(key).rstrip(":") != "include":
                continue
            if not isinstance(includes, list):
                raise RecoveryError("unsupported include declaration: " + str(path))
            for include in includes:
                if not isinstance(include, str) or "$" in include or "://" in include:
                    raise RecoveryError("recovery requires local recorded includes: " + str(path))
                target = (path.parent / include).resolve()
                try:
                    target.relative_to(workspace)
                except ValueError:
                    raise RecoveryError("include escapes workspace: " + str(target))
                if not target.exists():
                    raise RecoveryError("missing include: " + str(target))
        if path.name == "repos.yaml" and path.parent.name == "common":
            repositories = body.get("repos")
            if not isinstance(repositories, dict) or not repositories:
                raise RecoveryError("unsupported repository declaration: " + str(path))
            for namespace, repository in repositories.items():
                if not re.fullmatch(r"[A-Za-z_]\w*", str(namespace)):
                    raise RecoveryError("unsafe repository namespace: " + str(namespace))
                if isinstance(repository, str):
                    target = (path.parent / repository).resolve()
                    try:
                        target.relative_to(workspace)
                    except ValueError:
                        raise RecoveryError("local repository escapes workspace: " + str(target))
                    if not target.is_dir():
                        raise RecoveryError("local repository is missing: " + str(target))
                elif not isinstance(repository, dict) or not repository.get("git"):
                    raise RecoveryError("unsupported repository declaration for " + str(namespace))


def session_members(session_id):
    """Return live (non-zombie) PIDs in one child-owned process session."""
    members = set()
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text()
                fields = stat[stat.rfind(")") + 2:].split()
                # fields starts at proc(5) field 3: state, ppid, pgrp, session.
                state, session = fields[0], int(fields[3])
                if session == session_id and state != "Z":
                    members.add(int(entry.name))
            except (OSError, ValueError, IndexError):
                continue
        return members

    try:
        output = subprocess.check_output(
            ["ps", "-axo", "pid=,state="],
            universal_newlines=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in output.splitlines():
        fields = line.split(None, 1)
        if not fields:
            continue
        try:
            pid = int(fields[0])
            actual_session = os.getsid(pid)
        except (ValueError, ProcessLookupError, PermissionError):
            continue
        state = fields[1] if len(fields) == 2 else ""
        if actual_session == session_id and not state.startswith("Z"):
            members.add(pid)
    return members


def terminate_session(process, session_id):
    """Stop every process in a session created for one Spack command."""
    if session_id != process.pid or session_id <= 1:
        raise RecoveryError("refusing to terminate an unverified process session")
    try:
        if session_id == os.getsid(0):
            raise RecoveryError("refusing to terminate the recovery helper's own session")
    except AttributeError:
        pass

    def members():
        found = session_members(session_id)
        if found is None:
            raise RecoveryError(
                "cannot inspect the isolated Spack process session; resume is blocked"
            )
        return found

    def signal_members(signum):
        for pid in sorted(members(), reverse=True):
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass

    signal_members(signal.SIGTERM)
    deadline = time.monotonic() + 10
    while members() and time.monotonic() < deadline:
        # Catch workers forked into a new process group after the first scan.
        signal_members(signal.SIGTERM)
        time.sleep(0.1)
    if members():
        signal_members(signal.SIGKILL)
        deadline = time.monotonic() + 5
        while members() and time.monotonic() < deadline:
            signal_members(signal.SIGKILL)
            time.sleep(0.1)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    return sorted(members())


def command(record, candidate, args, label, capture=False):
    environment = os.environ.copy()
    environment.pop("SPACK_ENV", None)
    environment.update(SPACK_DISABLE_LOCAL_CONFIG="true", PYTHONDONTWRITEBYTECODE="1",
                       SPACK_MISC_CACHE_PATH=str(candidate / "state/misc"),
                       SPACK_USER_CACHE_PATH=str(candidate / "state/user"))
    logs = candidate / "logs"
    logs.mkdir(exist_ok=True)
    logfile = logs / ("{:04d}-{}.log".format(len(record["commands"]), label))
    entry = {"argv": [record["spack"]] + args, "log": str(logfile.relative_to(candidate)),
             "started": time.time()}
    record["commands"].append(entry)
    save(candidate, record)
    with logfile.open("w") as output:
        process = subprocess.Popen(entry["argv"], stdout=output, stderr=subprocess.STDOUT,
                                   env=environment, cwd=str(candidate), start_new_session=True)
        entry["pid"] = process.pid
        entry["session_id"] = process.pid
        save(candidate, record)
        try:
            result = process.wait()
        except BaseException:
            previous_handler = signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                remaining = terminate_session(process, entry["session_id"])
            finally:
                signal.signal(signal.SIGTERM, previous_handler)
            entry["interrupted"] = True
            entry["workers_remaining"] = remaining
            entry["session_checked"] = not remaining
            save(candidate, record)
            if remaining:
                raise RecoveryError(
                    "interrupted Spack session still has live workers {}; resume is blocked"
                    .format(remaining)
                )
            raise
    remaining = session_members(entry["session_id"])
    if remaining is None:
        raise RecoveryError(
            "cannot verify that the Spack process session stopped; resume is blocked"
        )
    if remaining:
        discovered = sorted(remaining)
        remaining = terminate_session(process, entry["session_id"])
        entry["workers_remaining"] = remaining
        entry["session_checked"] = not remaining
        entry["returncode"] = result
        save(candidate, record)
        raise RecoveryError(
            "Spack command exited with live session workers {}; remaining after cleanup: {}; "
            "the command is not accepted as complete".format(discovered, remaining)
        )
    entry["returncode"] = result
    entry["workers_remaining"] = []
    entry["session_checked"] = True
    save(candidate, record)
    output = logfile.read_text(errors="replace")
    if result:
        raise RecoveryError("{} failed; see {}\n{}".format(label, logfile, output[-2000:]))
    return output if capture else None


def spack_identity(spack):
    executable = Path(spack).resolve()
    if not executable.is_file():
        raise RecoveryError("Spack executable is missing: " + str(executable))
    version = subprocess.check_output([str(executable), "--version"], universal_newlines=True).strip()
    if version.split()[0] != "1.2.2":
        raise RecoveryError("this recovery helper targets pinned Spack 1.2.2; got " + version)
    root = executable.parent.parent
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], universal_newlines=True).strip()
    source = subprocess.check_output(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        universal_newlines=True,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        universal_newlines=True,
    ).strip()
    if dirty:
        raise RecoveryError("Spack checkout has tracked modifications")
    expected_commit = os.environ.get("CSE_SPACK_COMMIT")
    expected_source = os.environ.get("CSE_SPACK_SOURCE")
    expected_tag = os.environ.get("CSE_SPACK_TAG")
    if expected_commit and commit != expected_commit:
        raise RecoveryError("Spack commit does not match the prepared workspace")
    if expected_source and source != expected_source:
        raise RecoveryError("Spack source does not match the prepared workspace")
    if expected_tag and expected_commit:
        tagged = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", expected_tag + "^{commit}"],
            universal_newlines=True,
        ).strip()
        if tagged != expected_commit:
            raise RecoveryError("Spack tag does not resolve to the prepared commit")
    return {"version": version, "commit": commit, "source": source,
            "executable_sha256": digest(executable.read_bytes())}


def repository_probe(record, candidate, environment):
    env_path = candidate / "environments" / environment
    selected_text = command(
        record, candidate,
        ["-e", str(env_path), "location", "--repo", record["repository"]],
        "overlay-repository", True,
    ).strip().splitlines()
    if not selected_text:
        raise RecoveryError("Spack did not report the candidate overlay repository")
    selected = selected_text[-1]
    expected = candidate / "package-repos" / "spack_repo" / record["repository"]
    if Path(selected).resolve() != expected.resolve():
        raise RecoveryError("Spack selected an unexpected overlay repository: " + selected)

    builtin_text = command(
        record, candidate, ["-e", str(env_path), "location", "--repo", "builtin"],
        "builtin-repository", True,
    ).strip().splitlines()
    if not builtin_text:
        raise RecoveryError("Spack did not report the builtin repository")
    builtin = Path(builtin_text[-1]).resolve()
    if not builtin.is_dir():
        raise RecoveryError("builtin repository is missing: " + str(builtin))
    head = subprocess.check_output(
        ["git", "-C", str(builtin), "rev-parse", "HEAD"], universal_newlines=True
    ).strip()
    source = subprocess.check_output(
        ["git", "-C", str(builtin), "remote", "get-url", "origin"],
        universal_newlines=True,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(builtin), "status", "--porcelain", "--untracked-files=no"],
        universal_newlines=True,
    ).strip()
    if dirty:
        raise RecoveryError("builtin repository has tracked modifications")
    config = read_yaml(candidate / "configs" / "common" / "repos.yaml")
    expected_builtin = config.get("repos", {}).get("builtin", {})
    if not isinstance(expected_builtin, dict):
        raise RecoveryError("builtin repository does not have recorded provenance")
    if expected_builtin.get("git") and source != expected_builtin["git"]:
        raise RecoveryError("builtin repository source does not match repos.yaml")
    expected_commit = expected_builtin.get("commit")
    if expected_commit and head != expected_commit:
        raise RecoveryError("builtin repository commit does not match repos.yaml")
    expected_tag = expected_builtin.get("tag")
    if expected_tag:
        tagged = subprocess.check_output(
            ["git", "-C", str(builtin), "rev-parse", str(expected_tag) + "^{commit}"],
            universal_newlines=True,
        ).strip()
        if tagged != head:
            raise RecoveryError("builtin repository tag does not resolve to its active commit")
    identity = {"path": str(builtin), "source": source, "commit": head,
                "recorded_commit": expected_commit, "recorded_tag": expected_tag}
    previous = record.get("builtin_identity")
    if previous and previous != identity:
        raise RecoveryError("builtin repository identity changed since preparation")
    record["builtin_identity"] = identity
    save(candidate, record)


def recipe_probe(record, candidate, environment):
    code = ("import inspect,json,spack.repo; "
            "c=spack.repo.PATH.get_pkg_class(" + repr(record["package"]) + "); "
            "print('RECOVERY_JSON='+json.dumps({'recipe':inspect.getfile(c)}))")
    output = command(record, candidate, ["-e", str(candidate / "environments" / environment),
                                        "python", "-c", code], "recipe", True)
    data = next((json.loads(line.split("=", 1)[1]) for line in output.splitlines()
                 if line.startswith("RECOVERY_JSON=")), None)
    expected = candidate / record["recipe"]
    if not data or Path(data["recipe"]).resolve() != expected.resolve():
        raise RecoveryError("Spack did not select the candidate overlay recipe: " + str(data))


def local_impact(repo, module, package):
    impacted = {module}
    imports = {}
    uncertain = []
    for path in (repo / "packages").glob("*/package.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        refs = set()
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
                if node.level:
                    uncertain.append(str(path.relative_to(repo)))
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("__import__", "import_module", "exec", "eval", "get_pkg_class"):
                uncertain.append(str(path.relative_to(repo)))
            for name in names:
                prefix = "spack_repo." + repo.name + ".packages."
                if name.startswith(prefix):
                    refs.add(name[len(prefix):].split(".")[0])
                elif name.startswith("spack_repo.") and not name.startswith("spack_repo.builtin."):
                    uncertain.append(str(path.relative_to(repo)))
        imports[path.parent.name] = refs
    while True:
        extra = {name for name, refs in imports.items() if refs & impacted} - impacted
        if not extra:
            break
        impacted.update(extra)
    # Imported package modules need not map 1:1 to Spack names; broaden safely.
    return impacted != {module} or bool(uncertain), sorted(set(uncertain)), sorted(impacted)


def provider_directives(recipe):
    if not recipe.is_file():
        return []
    tree = ast.parse(recipe.read_text(), filename=str(recipe))
    return sorted(
        ast.dump(node, annotate_fields=True, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "provides"
    )


def isolate_environment(path):
    document = read_yaml(path)
    if not isinstance(document, dict) or not isinstance(document.get("spack"), dict):
        raise RecoveryError("candidate environment is not a Spack mapping: " + str(path))
    body = document["spack"]
    for key in list(body):
        if str(key).rstrip(":") in ("view", "modules"):
            del body[key]
    body["view"] = False
    disabled = {"default": {"enable": []}}
    if hasattr(yaml, "syaml_str"):
        key = yaml.syaml_str("modules")
        key.override = True
        body[key] = disabled
        write_yaml(path, document)
    else:
        placeholder = "__recovery_modules_override__"
        body[placeholder] = disabled
        write_yaml(path, document)
        rendered = path.read_text()
        marker = "  " + placeholder + ":\n"
        if rendered.count(marker) != 1:
            raise RecoveryError("could not render the candidate module override: " + str(path))
        path.write_text(rendered.replace(marker, "  modules::\n", 1))
    verified = read_yaml(path)
    verified_body = verified.get("spack", {}) if isinstance(verified, dict) else {}
    module_keys = [key for key in verified_body if str(key).rstrip(":") == "modules"]
    if verified_body.get("view") is not False or len(module_keys) != 1:
        raise RecoveryError("candidate view/module isolation was not rendered: " + str(path))
    module_policy = verified_body[module_keys[0]]
    if not isinstance(module_policy, dict) or module_policy.get("default", {}).get("enable") != []:
        raise RecoveryError("candidate module generation was not disabled: " + str(path))


def language_provider_identity(node, nodes):
    providers = []
    for dependency in node.get("dependencies", []):
        virtuals = set((dependency.get("parameters") or {}).get("virtuals", []))
        if not virtuals.intersection({"c", "cxx", "fortran"}):
            continue
        provider = nodes.get(dependency.get("hash"), {})
        providers.append({
            "name": provider.get("name"),
            "version": str(provider.get("version", "")),
            "parameters": provider.get("parameters"),
            "architecture": provider.get("arch", provider.get("architecture")),
            "external_path": provider.get("external_path"),
            "virtuals": sorted(virtuals.intersection({"c", "cxx", "fortran"})),
        })
    return sorted(providers, key=lambda item: json.dumps(item, sort_keys=True))


def user_parameters(node):
    parameters = dict(node.get("parameters") or {})
    # Spack derives this field from recipe patch directives. A successful local
    # patch correction is expected to change it; it is not an operator variant.
    parameters.pop("patches", None)
    return parameters


def same_failed_coordinate(old, old_nodes, new, new_nodes):
    return (
        new.get("name") == old.get("name")
        and str(new.get("version", "")) == str(old.get("version", ""))
        and user_parameters(new) == user_parameters(old)
        and new.get("arch", new.get("architecture"))
        == old.get("arch", old.get("architecture"))
        and language_provider_identity(new, new_nodes)
        == language_provider_identity(old, old_nodes)
    )


def prepare(args):
    workspace = args.workspace.resolve()
    candidate = args.candidate.resolve()
    source = args.source.resolve()
    prepared_workspace = os.environ.get("CSE_BUILD_WORKSPACE")
    if prepared_workspace and Path(prepared_workspace).resolve() != workspace:
        raise RecoveryError("--workspace does not match the prepared CSE build shell")
    try:
        candidate.resolve().relative_to(workspace)
    except ValueError:
        pass
    else:
        raise RecoveryError("candidate must be outside the source workspace")
    if candidate.exists() or candidate.is_symlink():
        raise RecoveryError("candidate path already exists; use status/solve/retry to resume")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", source.name) or not (source / "package.py").is_file():
        raise RecoveryError("--from must name a complete package module directory containing package.py")
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*", args.package):
        raise RecoveryError("invalid Spack package name")
    if not re.fullmatch(r"[A-Za-z_]\w*", args.repository):
        raise RecoveryError("--repository must be a Spack repository namespace")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", args.environment) or ".." in args.environment.split("/"):
        raise RecoveryError("--environment must be a compiler/lane from this workspace")
    before = inputs(workspace)
    if not before:
        raise RecoveryError("workspace has no recorded inputs")
    scoped_inputs(workspace)
    source_files = safe_files(source)
    gate = inventory_helper()
    if (workspace / "package-repos/overlay-inventory.json").exists():
        errors = gate.check(workspace / "package-repos")
        if errors:
            raise RecoveryError("source overlay inventory failed: " + "; ".join(errors))
    # Validate old workspaces too, without admitting or modifying their inputs.
    gate.snapshot(workspace / "package-repos")
    selected_environment = workspace / "environments" / args.environment
    if not selected_environment.is_dir():
        raise RecoveryError("selected environment is missing: " + str(selected_environment))
    original = lock_nodes(selected_environment / "spack.lock")
    matches = [(key, node) for key, node in original.items() if node["name"] == args.package]
    if args.failed_hash:
        matches = [(key, node) for key, node in matches if key == args.failed_hash]
    if len(matches) != 1:
        raise RecoveryError("select exactly one failed node using --failed-hash FULL_HASH; found " + str(len(matches)))
    old_hash, old_node = matches[0]
    if old_node.get("external"):
        raise RecoveryError("the failed package is external; it cannot be rebuilt by an overlay")
    identity = spack_identity(args.spack)
    candidate.mkdir(parents=True)
    record = {"schema_version": 1, "status": "preparing", "workspace": str(workspace),
              "candidate": str(candidate), "baseline": before, "package": args.package,
              "environment": args.environment, "old_hash": old_hash, "old_node": old_node,
              "repository": args.repository,
              "spack": str(Path(args.spack).resolve()), "spack_identity": identity,
              "commands": [], "affected": [], "unchanged": [], "unlocked": [], "solved": [],
              "retry": None, "created": time.time()}
    save(candidate, record)
    try:
        for relative in before:
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(workspace / relative), str(target))
        repo = candidate / "package-repos/spack_repo" / args.repository
        if not (repo / "repo.yaml").is_file():
            raise RecoveryError("overlay repository missing: " + str(repo))
        target = repo / "packages" / source.name
        old = safe_files(target) if target.exists() else {}
        old_broad, old_uncertain, old_modules = local_impact(
            repo, source.name, args.package
        )
        old_providers = provider_directives(target / "package.py")
        if old == source_files:
            raise RecoveryError("candidate correction is identical to the existing overlay")
        if target.exists():
            shutil.rmtree(str(target))
        shutil.copytree(str(source), str(target))
        record["recipe"] = (target / "package.py").relative_to(candidate).as_posix()
        record["package_files_before"] = old
        record["package_files_after"] = source_files
        inventory = gate.snapshot(candidate / "package-repos")
        (candidate / "package-repos/overlay-inventory.json").write_bytes(json_bytes(inventory))
        new_broad, new_uncertain, new_modules = local_impact(
            repo, source.name, args.package
        )
        new_providers = provider_directives(target / "package.py")
        provider_change = old_providers != new_providers
        broad = old_broad or new_broad or provider_change
        record["scope_reason"] = (
            "old/new local recipe imports, dynamic lookup, or provider change; "
            "all locked environments"
            if broad else "locks containing the corrected package"
        )
        record["uncertain_recipe_imports"] = sorted(set(old_uncertain + new_uncertain))
        record["impacted_local_modules"] = sorted(set(old_modules + new_modules))
        record["provider_directives_changed"] = provider_change
        for path in sorted((candidate / "environments").glob("*/*/spack.yaml")):
            name = path.parent.relative_to(candidate / "environments").as_posix()
            isolate_environment(path)
            # Rewrite absolute references to retained inputs, leave install/cache roots.
            path.write_text(path.read_text().replace(str(workspace) + "/", str(candidate) + "/"))
            lock = path.with_name("spack.lock")
            if not lock.exists():
                record["unlocked"].append(name)
            elif broad or any(node["name"] == args.package for node in lock_nodes(lock).values()):
                record["affected"].append(name)
            else:
                record["unchanged"].append(name)
        for path in (candidate / "configs").rglob("*.yaml"):
            path.write_text(path.read_text().replace(str(workspace) + "/", str(candidate) + "/"))
        # Prevent old literal misc-cache paths from inheriting stale repository indices.
        config_path = candidate / "configs/common/config.yaml"
        config = read_yaml(config_path)
        config["config"]["misc_cache"] = str(candidate / "state/misc")
        write_yaml(config_path, config)
        repository_probe(record, candidate, args.environment)
        recipe_probe(record, candidate, args.environment)
        if inputs(workspace) != before or safe_files(source) != source_files:
            raise RecoveryError("source inputs changed during preparation; discard this candidate")
        record["candidate_inputs"] = inputs(candidate)
        record["status"] = "prepared"
        save(candidate, record)
    except BaseException:
        record["status"] = "prepare_failed"
        save(candidate, record)
        raise
    print_status(candidate, record)


def guarded(candidate, record):
    if record["candidate"] != str(candidate):
        raise RecoveryError("candidate moved; prepare a new candidate at its final path")
    if inputs(Path(record["workspace"])) != record["baseline"]:
        raise RecoveryError("source workspace inputs changed; prepare a new recovery against the current baseline")
    if inputs(candidate) != record["candidate_inputs"]:
        raise RecoveryError("candidate inputs changed outside recovery; prepare a new candidate")
    if spack_identity(record["spack"]) != record["spack_identity"]:
        raise RecoveryError("Spack identity changed since preparation")


def process_is_running(entry):
    if not entry:
        return False
    session_id = entry.get("session_id")
    if isinstance(session_id, int) and session_id > 1:
        members = session_members(session_id)
        if members is None:
            return not entry.get("session_checked", False)
        if members:
            return True
        return False
    pid = entry.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_interrupted_solve(candidate, record):
    active = record.get("active_solve")
    if not active:
        return
    last = record.get("commands", [])[-1] if record.get("commands") else None
    if process_is_running(last):
        raise RecoveryError(
            "the recorded Spack process is still running; do not start another recovery operation"
        )
    backup = candidate / active["backup"]
    lock = candidate / "environments" / active["environment"] / "spack.lock"
    if not backup.is_file() or digest(backup.read_bytes()) != active["sha256"]:
        raise RecoveryError("interrupted solve backup is missing or changed; retain the candidate for review")
    atomic_write(lock, backup.read_bytes())
    if inputs(candidate) != active["candidate_inputs"]:
        raise RecoveryError(
            "interrupted solve changed inputs beyond its lock; retain the candidate for review"
        )
    record["candidate_inputs"] = active["candidate_inputs"]
    record["active_solve"] = None
    record["status"] = "solve_interrupted"
    save(candidate, record)


def describe_nodes(nodes):
    return [{"hash": key, "name": node["name"], "version": node.get("version"),
             "compiler": node.get("compiler"), "parameters": node.get("parameters"),
             "architecture": node.get("arch", node.get("architecture"))}
            for key, node in sorted(nodes.items())]


def solve(candidate, record):
    recover_interrupted_solve(candidate, record)
    guarded(candidate, record)
    repository_probe(record, candidate, record["environment"])
    for name in record["affected"]:
        if name in record["solved"]:
            continue
        environment = candidate / "environments" / name
        lock = environment / "spack.lock"
        before = lock.read_bytes()
        backup = candidate / "state" / "locks" / (name.replace("/", "-") + ".before")
        backup.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(backup, before)
        record["active_solve"] = {
            "environment": name,
            "backup": backup.relative_to(candidate).as_posix(),
            "sha256": digest(before),
            "candidate_inputs": record["candidate_inputs"],
        }
        record["status"] = "solving"
        save(candidate, record)
        try:
            # Fresh solves avoid reusing the old corrected dependency/ancestors.
            command(record, candidate, ["-e", str(environment), "concretize", "-f", "--fresh", "-j", "1"], "solve")
            recipe_probe(record, candidate, name) if any(n["name"] == record["package"] for n in lock_nodes(lock).values()) else None
        except BaseException:
            atomic_write(lock, before)
            record["active_solve"] = None
            record["status"] = "solve_failed"
            record["candidate_inputs"] = inputs(candidate)
            save(candidate, record)
            raise
        record["solved"].append(name)
        record["active_solve"] = None
        record["candidate_inputs"] = inputs(candidate)
        save(candidate, record)
    plans = {}
    for name in record["affected"]:
        old_path = Path(record["workspace"]) / "environments" / name / "spack.lock"
        new_path = candidate / "environments" / name / "spack.lock"
        old_document, old = load_lock(old_path)
        new_document, new = load_lock(new_path)
        plans[name] = {"lock_before_sha256": digest(old_path.read_bytes()),
                       "lock_after_sha256": digest(new_path.read_bytes()),
                       "roots_before": old_document.get("roots", []),
                       "roots_after": new_document.get("roots", []),
                       "removed": describe_nodes({k: v for k, v in old.items() if k not in new}),
                       "added": describe_nodes({k: v for k, v in new.items() if k not in old}),
                       "retained_hashes": sorted(set(old) & set(new))}
    for name in record["unchanged"]:
        old_path = Path(record["workspace"]) / "environments" / name / "spack.lock"
        new_path = candidate / "environments" / name / "spack.lock"
        if old_path.read_bytes() != new_path.read_bytes():
            raise RecoveryError("solve changed an environment outside the affected set: " + name)
    original_nodes = lock_nodes(
        Path(record["workspace"]) / "environments" / record["environment"] / "spack.lock"
    )
    target = lock_nodes(candidate / "environments" / record["environment"] / "spack.lock")
    old = record["old_node"]
    matches = [
        (hash_value, node)
        for hash_value, node in target.items()
        if same_failed_coordinate(old, original_nodes, node, target)
    ]
    if len(matches) != 1 or matches[0][0] == record["old_hash"]:
        raise RecoveryError(
            "solve did not produce one changed node matching the failed version, variants, "
            "architecture and language-provider identity; inspect candidate locks"
        )
    record["new_hash"] = matches[0][0]
    payload = {"package": record["package"], "environment": record["environment"],
               "old_hash": record["old_hash"], "new_hash": record["new_hash"],
               "scope": {"reason": record["scope_reason"],
                         "affected": record["affected"],
                         "unchanged": record["unchanged"],
                         "unlocked": record["unlocked"],
                         "old_and_new_local_modules": record["impacted_local_modules"],
                         "uncertain_recipe_imports": record["uncertain_recipe_imports"],
                         "provider_directives_changed": record["provider_directives_changed"]},
               "environments": plans, "inputs": record["candidate_inputs"]}
    data = json_bytes(payload)
    (candidate / "plan.json").write_bytes(data)
    record["plan_sha256"] = digest(data)
    record["status"] = "solved"
    save(candidate, record)
    print_status(candidate, record)


def installed(record, candidate, hash_value):
    code = ("import json,spack.environment; e=spack.environment.active_environment(); "
            "s=[s for s in e.all_specs() if s.dag_hash()==" + repr(hash_value) + "]; "
            "print('RECOVERY_JSON='+json.dumps({'installed':bool(s and s[0].installed),"
            "'prefix':str(s[0].prefix) if s else None}))")
    output = command(record, candidate, ["-e", str(candidate / "environments" / record["environment"]),
                                        "python", "-c", code], "installed", True)
    for line in output.splitlines():
        if line.startswith("RECOVERY_JSON="):
            return json.loads(line.split("=", 1)[1])
    raise RecoveryError("could not determine installed status")


def approved_plan(candidate, record, approval):
    plan = candidate / "plan.json"
    if not plan.is_file() or digest(plan.read_bytes()) != record.get("plan_sha256") or approval != record["plan_sha256"]:
        raise RecoveryError("review plan.json then pass its recorded digest with --approve-plan")


def require_compute():
    if os.environ.get("CSE_NODE_CONTEXT") != "compute":
        raise RecoveryError("this action requires the existing workspace's prepared compute shell")


def retry(candidate, record, approval):
    guarded(candidate, record)
    approved_plan(candidate, record, approval)
    require_compute()
    if record.get("status") not in ("solved", "retry_failed", "retry_passed"):
        raise RecoveryError("retry requires a completed candidate solve")
    repository_probe(record, candidate, record["environment"])
    recipe_probe(record, candidate, record["environment"])
    if record.get("retry") == "passed":
        print_status(candidate, record)
        return
    current = installed(record, candidate, record["new_hash"])
    if current["installed"]:
        raise RecoveryError("corrected hash is already installed; a skipped install is not a verified build retry. Retain evidence or use a fresh candidate/store; no prefix will be removed")
    record["status"] = "building"
    save(candidate, record)
    try:
        command(record, candidate, ["-e", str(candidate / "environments" / record["environment"]),
                                    "install", "--only-concrete", "--no-add", "--no-cache", "--fail-fast",
                                    "--keep-stage", "-v", "-j", "1",
                                    "/" + record["new_hash"]], "retry")
        after = installed(record, candidate, record["new_hash"])
        if not after["installed"] or not Path(after["prefix"]).is_dir():
            raise RecoveryError("install returned success without an installed corrected prefix")
        guarded(candidate, record)
    except BaseException:
        record["status"] = "retry_failed"
        save(candidate, record)
        raise
    record["retry"] = "passed"
    record["status"] = "retry_passed"
    record["verified_prefix"] = after["prefix"]
    save(candidate, record)
    print_status(candidate, record)


def missing_specs(record, candidate):
    code = (
        "import json,spack.environment; e=spack.environment.active_environment(); "
        "m=[s.dag_hash() for s in e.all_specs() "
        "if not getattr(s,'external',False) and not s.installed]; "
        "print('RECOVERY_JSON='+json.dumps({'missing':sorted(m)}))"
    )
    output = command(
        record, candidate,
        ["-e", str(candidate / "environments" / record["environment"]),
         "python", "-c", code],
        "missing", True,
    )
    for line in output.splitlines():
        if line.startswith("RECOVERY_JSON="):
            return json.loads(line.split("=", 1)[1])["missing"]
    raise RecoveryError("could not determine missing candidate specs")


def resume(candidate, record, approval):
    guarded(candidate, record)
    approved_plan(candidate, record, approval)
    require_compute()
    if record.get("retry") != "passed":
        raise RecoveryError("resume requires a successful focused retry first")
    if record.get("resume") == "passed":
        print_status(candidate, record)
        return
    repository_probe(record, candidate, record["environment"])
    recipe_probe(record, candidate, record["environment"])
    record["status"] = "resuming"
    save(candidate, record)
    try:
        command(
            record, candidate,
            ["-e", str(candidate / "environments" / record["environment"]),
             "install", "--only-concrete", "--no-add", "--fail-fast", "-j", "1"],
            "resume",
        )
        missing = missing_specs(record, candidate)
        if missing:
            raise RecoveryError(
                "candidate environment install returned success with missing concrete specs: "
                + ", ".join(missing)
            )
        guarded(candidate, record)
    except BaseException:
        record["status"] = "resume_failed"
        save(candidate, record)
        raise
    record["resume"] = "passed"
    record["status"] = "resume_passed"
    save(candidate, record)
    print_status(candidate, record)


def export(candidate, record, destination):
    guarded(candidate, record)
    approved_plan(candidate, record, record.get("plan_sha256"))
    if record.get("retry") != "passed":
        raise RecoveryError("export requires a successful corrected build retry")
    if destination.exists() or destination.is_symlink():
        raise RecoveryError("export destination already exists")
    for protected in (Path(record["workspace"]).resolve(), candidate.resolve()):
        try:
            destination.resolve().relative_to(protected)
        except ValueError:
            pass
        else:
            raise RecoveryError("export destination must be outside protected workspace trees")
    destination.mkdir(parents=True)
    source = (candidate / record["recipe"]).parent
    shutil.copytree(str(source), str(destination / source.name))
    (destination / "recovery.json").write_bytes(json_bytes(record))
    shutil.copyfile(str(candidate / "plan.json"), str(destination / "plan.json"))
    shutil.copytree(str(candidate / "logs"), str(destination / "logs"))
    checksums = safe_files(destination)
    (destination / "SHA256SUMS").write_text("".join(h + "  " + name + "\n" for name, h in sorted(checksums.items())))
    print("Exported correction and build evidence: " + str(destination))
    print("On another system, prepare against its own workspace using --from " + str(destination / source.name))


def print_status(candidate, record):
    print("Status: " + record["status"])
    print("Candidate: " + str(candidate))
    for key in ("affected", "unchanged", "unlocked"):
        print(key.capitalize() + ": " + (", ".join(record[key]) or "none"))
    if record.get("plan_sha256"):
        print("Review: " + str(candidate / "plan.json"))
        print("Retry approval: --approve-plan " + record["plan_sha256"])
    if record.get("resume") == "passed":
        print("Candidate environment: all concrete specs installed")
    print("Record: " + str(candidate / "recovery.json"))


@contextlib.contextmanager
def candidate_lock(candidate):
    lock = candidate / ".operator.lock"
    if lock.is_symlink():
        raise RecoveryError("candidate operation lock is a symlink")
    with lock.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryError("another recovery operation is using this candidate")
        yield


def main(argv=None):
    def terminate(_signum, _frame):
        raise TerminationRequested()

    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    prepare_parser = sub.add_parser("prepare", help="inspect all locks and stage a separate correction")
    prepare_parser.add_argument("--workspace", type=Path, default=Path(os.environ.get("CSE_BUILD_WORKSPACE", ".")))
    prepare_parser.add_argument("--environment", required=True)
    prepare_parser.add_argument("--package", required=True)
    prepare_parser.add_argument("--failed-hash")
    prepare_parser.add_argument("--from", dest="source", type=Path, required=True)
    prepare_parser.add_argument("--repository", default="cse_trials")
    prepare_parser.add_argument("--spack", default=shutil.which("spack"))
    prepare_parser.add_argument("--candidate", required=True, type=Path)
    for action in ("status", "solve", "retry", "resume", "export"):
        child = sub.add_parser(action)
        child.add_argument("--candidate", type=Path, required=True)
        if action in ("retry", "resume"):
            child.add_argument("--approve-plan", required=True)
        if action == "export":
            child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            if not args.spack:
                raise RecoveryError("enter the existing prepared build shell first (Spack is missing)")
            prepare(args)
        elif args.action:
            candidate = args.candidate.resolve()
            with candidate_lock(candidate):
                record = json.loads((candidate / "recovery.json").read_text())
                if args.action == "status":
                    print_status(candidate, record)
                elif process_is_running(record.get("commands", [])[-1] if record.get("commands") else None):
                    raise RecoveryError("the recorded Spack process is still running")
                elif record["status"] == "prepare_failed":
                    raise RecoveryError("preparation failed; inspect the record and use a new candidate directory")
                elif args.action == "solve":
                    solve(candidate, record)
                elif args.action == "retry":
                    retry(candidate, record, args.approve_plan)
                elif args.action == "resume":
                    resume(candidate, record, args.approve_plan)
                else:
                    export(candidate, record, args.output.absolute())
        else:
            parser.error("select prepare, status, solve, retry, resume or export")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("overlay-recovery: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("overlay-recovery: interrupted; retain candidate and rerun the same operation", file=sys.stderr)
        return 130
    except TerminationRequested:
        print("overlay-recovery: terminated; child stopped and candidate retained for safe resume", file=sys.stderr)
        return 143


if __name__ == "__main__":
    sys.exit(main())
