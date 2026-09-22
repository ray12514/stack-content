#!/usr/bin/env python3
"""Maintain one environment in an existing CSE workspace.

The guard and lock checks are intentionally standard-library only. Concretize
and resume are run with ``spack python`` and lazily load the recovery helpers.
"""

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import sys
import time


class BuildError(ValueError):
    pass


LOCK_NAME = ".cse-maintenance.lock"
LOCK_FD_ENV = "CSE_MAINTENANCE_LOCK_FD"
RECOVERY_DIRECTORY = ".cse-build-recovery"
ACTIVE_STATUSES = {
    "concretize_preparing", "concretizing", "resume_preparing", "resuming",
    "concretize_recovery_required", "resume_recovery_required",
}


def _lock_path(workspace):
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise BuildError("workspace is missing: " + str(workspace))
    path = workspace / LOCK_NAME
    if path.is_symlink():
        raise BuildError("workspace maintenance lock is a symlink")
    return path


def _inherited_lock_fd(workspace):
    value = os.environ.get(LOCK_FD_ENV)
    if value is None:
        return None
    try:
        fd = int(value)
    except ValueError:
        raise BuildError(LOCK_FD_ENV + " is not a file descriptor")
    if fd < 0:
        raise BuildError(LOCK_FD_ENV + " is not a valid file descriptor")
    path = _lock_path(workspace)
    try:
        descriptor = os.fstat(fd)
        target = path.stat()
    except OSError as error:
        raise BuildError("inherited maintenance lock is unavailable: " + str(error))
    if not stat.S_ISREG(descriptor.st_mode) or (
        descriptor.st_dev, descriptor.st_ino
    ) != (target.st_dev, target.st_ino):
        raise BuildError("inherited maintenance lock does not match this workspace")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise BuildError("inherited maintenance lock is not owned by this operation")
    return fd


@contextlib.contextmanager
def maintenance_lock(workspace):
    """Hold or adopt the workspace-wide finite-operation lock."""
    workspace = Path(workspace).resolve()
    inherited = _inherited_lock_fd(workspace)
    if inherited is not None:
        yield inherited
        return

    path = _lock_path(workspace)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags, 0o660)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BuildError("workspace maintenance lock is not a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BuildError("another finite workspace operation is active")
        previous = os.environ.get(LOCK_FD_ENV)
        was_inheritable = os.get_inheritable(fd)
        os.set_inheritable(fd, True)
        os.environ[LOCK_FD_ENV] = str(fd)
        try:
            yield fd
        finally:
            os.set_inheritable(fd, was_inheritable)
            if previous is None:
                os.environ.pop(LOCK_FD_ENV, None)
            else:
                os.environ[LOCK_FD_ENV] = previous
    finally:
        os.close(fd)


def _recovery():
    path = Path(__file__).with_name("overlay-recovery.py")
    spec = importlib.util.spec_from_file_location("cse_overlay_recovery", str(path))
    if spec is None or spec.loader is None:
        raise BuildError("cannot load the workspace recovery support")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workspace_overlay():
    path = Path(__file__).with_name("workspace-overlay.py")
    spec = importlib.util.spec_from_file_location("cse_workspace_overlay", str(path))
    if spec is None or spec.loader is None:
        raise BuildError("cannot load the workspace overlay gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _environment(workspace, name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) or ".." in name.split("/"):
        raise BuildError("--environment must be an existing compiler/lane")
    root = workspace / "environments"
    path = root / name
    if path.is_symlink() or not path.is_dir():
        raise BuildError("environment is missing or unsafe: " + name)
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise BuildError("environment escapes the workspace: " + name)
    manifest = resolved / "spack.yaml"
    if manifest.is_symlink() or not manifest.is_file():
        raise BuildError("environment manifest is missing or unsafe: " + name)
    return resolved


def _record_paths(workspace):
    root = workspace / RECOVERY_DIRECTORY
    if root.is_symlink():
        raise BuildError("build recovery directory is a symlink")
    if not root.exists():
        return []
    return sorted(root.glob("*/recovery.json"))


def _unfinished(workspace):
    records = []
    for path in _record_paths(workspace):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError, TypeError) as error:
            raise BuildError("invalid build recovery record {}: {}".format(path, error))
        if record.get("tool") == "workspace-build" and record.get("status") in ACTIVE_STATUSES:
            records.append((path.parent, record))
    return records


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _settled_failure_is_safe(directory, record):
    status = record.get("status")
    if status not in {"concretize_failed", "concretize_interrupted",
                      "resume_failed", "resume_interrupted"}:
        return True
    backup = directory / "spack.yaml.before"
    if (not backup.is_file()
            or _sha256(backup) != record.get("manifest_before_sha256")
            or record.get("rollback_manifest_sha256") != record.get("manifest_before_sha256")
            or not record.get("rollback_completed")):
        return False
    if record.get("action") == "concretize":
        if record.get("lock_existed"):
            lock_backup = directory / "spack.lock.before"
            if (not lock_backup.is_file()
                    or _sha256(lock_backup) != record.get("lock_before_sha256")
                    or record.get("rollback_lock_sha256") != record.get("lock_before_sha256")):
                return False
        elif record.get("rollback_lock_sha256") is not None:
            return False
    elif record.get("rollback_lock_sha256") != record.get("lock_before_sha256"):
        return False
    command = record.get("commands", [])[-1] if record.get("commands") else None
    if command and command.get("pid") is not None:
        if command.get("session_checked") is not True or command.get("workers_remaining"):
            return False
    return True


def require_recovery_idle(workspace):
    """Reject a workspace with a transaction that may still own live inputs.

    Settled failures have already restored transaction-owned bytes and may be
    superseded by a corrected recipe or spec followed by a new forced solve.
    """
    workspace = Path(workspace).resolve()
    active = _unfinished(workspace)
    if active:
        details = ", ".join(
            "{}:{} ({})".format(item[1].get("action"), item[1].get("environment"), item[0])
            for item in active
        )
        raise BuildError("unfinished workspace build operation must be recovered first: " + details)
    for path in _record_paths(workspace):
        record = json.loads(path.read_text())
        if record.get("tool") == "workspace-build" and not _settled_failure_is_safe(path.parent, record):
            raise BuildError("failed workspace operation is not safely rolled back: " + str(path.parent))
    return True


def _reject_unfinished_overlay(workspace):
    root = workspace / ".cse-overlay"
    if root.is_symlink():
        raise BuildError("overlay recovery directory is a symlink")
    terminal = {"applied", "restored", "cancelled"}
    for path in sorted(root.glob("*/record.json")) if root.exists() else []:
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError, TypeError) as error:
            raise BuildError("invalid overlay recovery record {}: {}".format(path, error))
        if record.get("status") not in terminal:
            raise BuildError("unfinished overlay operation must be resolved first: " + str(path.parent))


def _new_record(workspace, action, environment, spack, recovery):
    root = workspace / RECOVERY_DIRECTORY
    root.mkdir(mode=0o770, exist_ok=True)
    identifier = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-{}-{}".format(
        os.getpid(), secrets.token_hex(4)
    )
    directory = root / identifier
    directory.mkdir(mode=0o770)
    record = {
        "schema_version": 1,
        "tool": "workspace-build",
        "action": action,
        "environment": environment,
        "workspace": str(workspace),
        "record": str(directory),
        "status": action + "_preparing",
        "spack": str(Path(spack).resolve()),
        "spack_identity": recovery.spack_identity(spack),
        "commands": [],
        "created": time.time(),
    }
    recovery.save(directory, record)
    return directory, record


def _select_record(workspace, action, environment, spack, recovery):
    active = _unfinished(workspace)
    matching = [item for item in active if item[1].get("action") == action and item[1].get("environment") == environment]
    if len(active) > 1 or (active and not matching):
        details = ", ".join(
            "{}:{} ({})".format(item[1].get("action"), item[1].get("environment"), item[0])
            for item in active
        )
        raise BuildError("unfinished workspace operation must be resolved first: " + details)
    if matching:
        directory, record = matching[0]
        if Path(record.get("workspace", "")).resolve() != workspace:
            raise BuildError("recovery record belongs to another workspace")
        if Path(record.get("spack", "")).resolve() != Path(spack).resolve():
            raise BuildError("recovery record uses another Spack executable")
        if recovery.spack_identity(spack) != record.get("spack_identity"):
            raise BuildError("Spack identity changed since the interrupted operation")
        return directory, record
    return _new_record(workspace, action, environment, spack, recovery)


def _filtered_inputs(values, excluded):
    return {name: value for name, value in values.items() if name not in excluded}


def _restore_lock(record_dir, record, lock, recovery):
    backup = record_dir / "spack.lock.before"
    if record.get("lock_existed"):
        if not backup.is_file() or recovery.digest(backup.read_bytes()) != record["lock_before_sha256"]:
            raise BuildError("selected lock backup is missing or changed")
        recovery.atomic_write(lock, backup.read_bytes())
    else:
        if lock.exists():
            lock.unlink()


def _ensure_no_live_workers(record, recovery):
    command = record.get("commands", [])[-1] if record.get("commands") else None
    if recovery.process_is_running(command):
        raise BuildError("the interrupted Spack process session still has live workers")


def _resume_interrupted(record_dir, record, environment_path, recovery):
    _ensure_no_live_workers(record, recovery)
    status = record.get("status")
    if status in ("concretize_preparing", "resume_preparing") and not record.get("baseline"):
        return
    manifest_path = environment_path / "spack.yaml"
    current_manifest = _sha256(manifest_path)
    allowed_manifests = {
        record.get("manifest_before_sha256"), record.get("temporary_manifest_sha256")
    }
    if current_manifest not in allowed_manifests:
        raise BuildError(
            "selected manifest changed after interruption; preserving it instead of restoring old bytes"
        )
    if status in ("concretize_preparing", "resume_preparing"):
        return
    if (record["action"] == "concretize"
            and record.get("status") in ("concretizing", "concretize_recovery_required")):
        _restore_lock(record_dir, record, environment_path / "spack.lock", recovery)
        manifest_backup = record_dir / "spack.yaml.before"
        if not manifest_backup.is_file() or recovery.digest(manifest_backup.read_bytes()) != record["manifest_before_sha256"]:
            raise BuildError("selected manifest backup is missing or changed")
        recovery.atomic_write(environment_path / "spack.yaml", manifest_backup.read_bytes())
        record["status"] = "concretize_interrupted"
        _mark_rollback(record, environment_path)
        recovery.save(record_dir, record)
    if (record["action"] == "resume"
            and record.get("status") in ("resuming", "resume_recovery_required")):
        backup = record_dir / "spack.yaml.before"
        if not backup.is_file() or recovery.digest(backup.read_bytes()) != record["manifest_before_sha256"]:
            raise BuildError("selected manifest backup is missing or changed")
        recovery.atomic_write(environment_path / "spack.yaml", backup.read_bytes())
        record["status"] = "resume_interrupted"
        _mark_rollback(record, environment_path)
        recovery.save(record_dir, record)


def _verify_unchanged(workspace, baseline, excluded, recovery):
    current = recovery.inputs(workspace)
    if _filtered_inputs(current, excluded) != _filtered_inputs(baseline, excluded):
        raise BuildError("workspace inputs outside the selected transaction changed")


def _isolate_manifest(manifest, record_dir, recovery):
    """Disable presentation and force this transaction's private misc cache."""
    recovery.isolate_environment(manifest)
    document = recovery.read_yaml(manifest)
    body = document.get("spack") if isinstance(document, dict) else None
    if not isinstance(body, dict):
        raise BuildError("selected environment is not a Spack mapping")
    config_key = next((key for key in body if str(key).rstrip(":") == "config"), None)
    if config_key is None:
        config_key = "config"
        body[config_key] = {}
    if not isinstance(body[config_key], dict):
        raise BuildError("selected environment config is not a mapping")
    body[config_key]["misc_cache"] = str(record_dir / "state" / "misc")
    recovery.write_yaml(manifest, document)


def _failed_status(record, recovery, action):
    """Return a settled status only after the command session is proven gone."""
    command = record.get("commands", [])[-1] if record.get("commands") else None
    if not command or command.get("pid") is None:
        return action + "_failed"
    try:
        running = recovery.process_is_running(command)
    except Exception:
        running = True
    if (running or command.get("session_checked") is not True
            or command.get("workers_remaining")):
        return action + "_recovery_required"
    return action + "_failed"


def _mark_rollback(record, environment_path):
    manifest = environment_path / "spack.yaml"
    lock = environment_path / "spack.lock"
    record["rollback_manifest_sha256"] = _sha256(manifest)
    record["rollback_lock_sha256"] = _sha256(lock) if lock.is_file() else None
    record["rollback_completed"] = time.time()


def _latest_concretize(workspace, environment):
    candidates = []
    for path in _record_paths(workspace):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError, TypeError) as error:
            raise BuildError("invalid build recovery record {}: {}".format(path, error))
        if (record.get("tool") == "workspace-build"
                and record.get("action") == "concretize"
                and record.get("environment") == environment):
            candidates.append((record.get("created", 0), path, record))
    return max(candidates, key=lambda item: (item[0], str(item[1])))[2] if candidates else None


def _solve_intent(recovery, manifest):
    document = recovery.read_yaml(manifest)
    body = document.get("spack") if isinstance(document, dict) else None
    if not isinstance(body, dict):
        raise BuildError("selected environment is not a Spack mapping")
    normalized = {}
    operational = {"build_jobs", "build_stage", "misc_cache", "source_cache", "test_stage"}
    for key, value in body.items():
        name = str(key).rstrip(":")
        if name in ("view", "modules"):
            continue
        if name == "config" and isinstance(value, dict):
            value = {str(item).rstrip(":"): setting for item, setting in value.items()
                     if str(item).rstrip(":") not in operational}
            if not value:
                continue
        normalized[name] = value
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _require_latest_solve(workspace, environment, recovery=None, manifest=None):
    latest = _latest_concretize(workspace, environment)
    if latest and latest.get("status") != "concretized":
        raise BuildError(
            "the latest forced solve for {} failed; correct the input and reconcretize before resume"
            .format(environment)
        )
    if latest and recovery is not None and manifest is not None:
        if latest.get("solve_intent_sha256") != _solve_intent(recovery, manifest):
            raise BuildError(
                "selected solve inputs changed for {}; reconcretize before resume".format(environment)
            )


def _validate_concrete_roots(record, record_dir, environment_path, recovery):
    code = (
        "import json,spack.environment as e;"
        "x=e.active_environment();"
        "c={(g,s) for g in x.manifest.groups() for s in x.user_specs_by(group=g)};"
        "l={(r.group,r.root) for r in x.concretized_roots};"
        "f=lambda q:sorted(g+':'+str(s) for g,s in q);"
        "print('CSE_ROOT_CHECK='+json.dumps({'current_not_locked':f(c-l),"
        "'locked_not_current':f(l-c)}))"
    )
    output = recovery.command(
        record, record_dir,
        ["-e", str(environment_path), "python", "-c", code],
        "validate-locked-roots", capture=True,
    )
    marker = [line for line in output.splitlines() if line.startswith("CSE_ROOT_CHECK=")]
    if len(marker) != 1:
        raise BuildError("Spack did not report locked-root validation")
    result = json.loads(marker[0].split("=", 1)[1])
    if result.get("current_not_locked") or result.get("locked_not_current"):
        raise BuildError(
            "selected root intent is not represented by the lock; reconcretize before resume: "
            + json.dumps(result, sort_keys=True)
        )


def _graph_delta(before, after, recovery):
    if before is None:
        old_document, old_nodes = {"roots": []}, {}
    else:
        old_document, old_nodes = recovery.load_lock(before)
    new_document, new_nodes = recovery.load_lock(after)
    return {
        "roots_before": old_document.get("roots", []),
        "roots_after": new_document.get("roots", []),
        "removed": recovery.describe_nodes({key: value for key, value in old_nodes.items() if key not in new_nodes}),
        "added": recovery.describe_nodes({key: value for key, value in new_nodes.items() if key not in old_nodes}),
        "retained_hashes": sorted(set(old_nodes) & set(new_nodes)),
    }


def concretize(args):
    workspace = args.workspace.resolve()
    environment_path = _environment(workspace, args.environment)
    lock = environment_path / "spack.lock"
    if lock.is_symlink():
        raise BuildError("environment lock is a symlink")
    if lock.exists() and not args.reconcretize:
        require_recovery_idle(workspace)
        pending = _workspace_overlay().check_workspace(
            workspace, [args.environment], action="concretize"
        )
        if pending:
            raise BuildError("recipe changes require --reconcretize for " + args.environment)
        print("Keeping existing lock: " + args.environment)
        return

    recovery = _recovery()
    overlay = _workspace_overlay()
    overlay.check_workspace(workspace, [args.environment], action="concretize")
    record_dir, record = _select_record(workspace, "concretize", args.environment, args.spack, recovery)
    _resume_interrupted(record_dir, record, environment_path, recovery)
    if not record.get("baseline"):
        baseline = recovery.inputs(workspace)
        relative = lock.relative_to(workspace).as_posix()
        record["baseline"] = baseline
        record["selected_lock"] = relative
        manifest = environment_path / "spack.yaml"
        manifest_bytes = manifest.read_bytes()
        recovery.atomic_write(record_dir / "spack.yaml.before", manifest_bytes)
        record["selected_manifest"] = manifest.relative_to(workspace).as_posix()
        record["manifest_before_sha256"] = recovery.digest(manifest_bytes)
        record["lock_existed"] = lock.is_file()
        if lock.is_file():
            before = lock.read_bytes()
            recovery.atomic_write(record_dir / "spack.lock.before", before)
            record["lock_before_sha256"] = recovery.digest(before)
        else:
            record["lock_before_sha256"] = None
        recovery.save(record_dir, record)
    else:
        baseline = record["baseline"]
        _restore_lock(record_dir, record, lock, recovery)
    manifest = environment_path / "spack.yaml"
    manifest_before = (record_dir / "spack.yaml.before").read_bytes()
    excluded = {record["selected_lock"], record["selected_manifest"]}
    command = ["-e", str(environment_path), "concretize"]
    if record["lock_existed"]:
        command.append("-f")
    command += ["--fresh", "-j", "1"]
    try:
        recovery.atomic_write(manifest, manifest_before)
        _isolate_manifest(manifest, record_dir, recovery)
        record["temporary_manifest_sha256"] = _sha256(manifest)
        _verify_unchanged(workspace, baseline, excluded, recovery)
        record["status"] = "concretizing"
        recovery.save(record_dir, record)
        recovery.command(record, record_dir, command, "concretize")
        if not lock.is_file():
            raise BuildError("Spack concretize did not create the selected lock")
        _verify_unchanged(workspace, baseline, excluded, recovery)
        before_path = record_dir / "spack.lock.before" if record["lock_existed"] else None
        delta = _graph_delta(before_path, lock, recovery)
    except BaseException:
        _restore_lock(record_dir, record, lock, recovery)
        recovery.atomic_write(manifest, manifest_before)
        record["status"] = _failed_status(record, recovery, "concretize")
        if record["status"] == "concretize_failed":
            _mark_rollback(record, environment_path)
        raise
    finally:
        recovery.atomic_write(manifest, manifest_before)
        recovery.save(record_dir, record)
    _verify_unchanged(workspace, baseline, {record["selected_lock"]}, recovery)
    record["lock_after_sha256"] = recovery.digest(lock.read_bytes())
    record["graph_delta"] = delta
    record["solve_intent_sha256"] = _solve_intent(recovery, manifest)
    record["status"] = "concretized"
    recovery.save(record_dir, record)
    record["resolved_overlays"] = overlay.mark_resolved(workspace, args.environment)
    recovery.save(record_dir, record)
    print(
        "Concretized {}: +{} -{} ({} hashes retained)".format(
            args.environment, len(delta["added"]), len(delta["removed"]), len(delta["retained_hashes"])
        )
    )
    print("Recovery record: " + str(record_dir))


def resume(args):
    workspace = args.workspace.resolve()
    environment_path = _environment(workspace, args.environment)
    manifest = environment_path / "spack.yaml"
    lock = environment_path / "spack.lock"
    if lock.is_symlink() or not lock.is_file():
        raise BuildError("resume requires the selected environment lock")
    recovery = _recovery()
    _require_latest_solve(workspace, args.environment, recovery, manifest)
    overlay = _workspace_overlay()
    overlay.check_workspace(workspace, [args.environment], action="build")
    record_dir, record = _select_record(workspace, "resume", args.environment, args.spack, recovery)
    _resume_interrupted(record_dir, record, environment_path, recovery)
    if not record.get("baseline"):
        baseline = recovery.inputs(workspace)
        manifest_bytes = manifest.read_bytes()
        recovery.atomic_write(record_dir / "spack.yaml.before", manifest_bytes)
        record["baseline"] = baseline
        record["selected_manifest"] = manifest.relative_to(workspace).as_posix()
        record["selected_lock"] = lock.relative_to(workspace).as_posix()
        record["manifest_before_sha256"] = recovery.digest(manifest_bytes)
        record["lock_before_sha256"] = recovery.digest(lock.read_bytes())
        recovery.save(record_dir, record)
    else:
        baseline = record["baseline"]
    excluded = {record["selected_manifest"]}
    _verify_unchanged(workspace, baseline, excluded, recovery)
    if recovery.digest(lock.read_bytes()) != record["lock_before_sha256"]:
        raise BuildError("selected lock changed since resume preparation")

    original = (record_dir / "spack.yaml.before").read_bytes()
    try:
        recovery.atomic_write(manifest, original)
        _isolate_manifest(manifest, record_dir, recovery)
        record["temporary_manifest_sha256"] = _sha256(manifest)
        record["status"] = "resuming"
        recovery.save(record_dir, record)
        _validate_concrete_roots(record, record_dir, environment_path, recovery)
        recovery.command(
            record,
            record_dir,
            ["-e", str(environment_path), "install", "--only-concrete", "--no-add", "--fail-fast"],
            "resume",
        )
    except BaseException:
        recovery.atomic_write(manifest, original)
        record["status"] = _failed_status(record, recovery, "resume")
        if record["status"] == "resume_failed":
            _mark_rollback(record, environment_path)
        raise
    finally:
        recovery.atomic_write(manifest, original)
        recovery.save(record_dir, record)
    _verify_unchanged(workspace, baseline, set(), recovery)
    if recovery.digest(lock.read_bytes()) != record["lock_before_sha256"]:
        raise BuildError("resume changed the selected environment lock")
    record["status"] = "resumed"
    recovery.save(record_dir, record)
    print("Resumed all locked roots: " + args.environment)
    print("Recovery record: " + str(record_dir))


def guard(args):
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise BuildError("guard requires a command")
    workspace = args.workspace.resolve()
    with maintenance_lock(workspace) as fd:
        os.set_inheritable(fd, True)
        environment = os.environ.copy()
        environment[LOCK_FD_ENV] = str(fd)
        os.execvpe(command[0], command, environment)


def check_environments(args):
    workspace = args.workspace.resolve()
    require_recovery_idle(workspace)
    recovery = _recovery()
    for environment in args.environment:
        path = _environment(workspace, environment)
        _require_latest_solve(workspace, environment, recovery, path / "spack.yaml")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    for action in ("concretize", "resume"):
        child = sub.add_parser(action)
        child.add_argument("--workspace", type=Path, required=True)
        child.add_argument("--environment", required=True)
        child.add_argument("--spack", default=shutil.which("spack"))
        if action == "concretize":
            child.add_argument("--reconcretize", action="store_true")
    guard_parser = sub.add_parser("guard")
    guard_parser.add_argument("--workspace", type=Path, required=True)
    guard_parser.add_argument("command", nargs=argparse.REMAINDER)
    check = sub.add_parser("check-lock")
    check.add_argument("--workspace", type=Path, required=True)
    journal_check = sub.add_parser("check")
    journal_check.add_argument("--workspace", type=Path, required=True)
    journal_check.add_argument("--environment", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "guard":
            guard(args)
        elif args.action == "check-lock":
            if _inherited_lock_fd(args.workspace.resolve()) is None:
                raise BuildError("no inherited workspace maintenance lock")
        elif args.action == "check":
            with maintenance_lock(args.workspace):
                check_environments(args)
        elif args.action in ("concretize", "resume"):
            if not args.spack:
                raise BuildError("run this action with spack python in the prepared build shell")
            with maintenance_lock(args.workspace):
                recovery = _recovery()
                previous = signal.getsignal(signal.SIGTERM)

                def terminate(signum, frame):
                    del signum, frame
                    raise recovery.TerminationRequested()

                signal.signal(signal.SIGTERM, terminate)
                try:
                    if args.action == "concretize":
                        concretize(args)
                    else:
                        resume(args)
                finally:
                    signal.signal(signal.SIGTERM, previous)
        else:
            parser.error("select concretize, resume, guard, check-lock or check")
        return 0
    except (BuildError, OSError, ValueError, KeyError, TypeError) as error:
        print("workspace-build: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("workspace-build: interrupted; recovery record retained", file=sys.stderr)
        return 130
    except BaseException as error:
        if error.__class__.__name__ == "TerminationRequested":
            print("workspace-build: terminated; selected input restored and record retained", file=sys.stderr)
            return 143
        raise


if __name__ == "__main__":
    sys.exit(main())
