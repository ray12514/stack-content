#!/usr/bin/env python3
"""Refresh generated pilot controls without replacing build inputs or locks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml


class RefreshError(ValueError):
    """Raised when a control-only refresh cannot be performed safely."""


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RefreshError(f"{label} must be a YAML mapping")
    return value


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), label)
    except OSError as error:
        raise RefreshError(f"cannot read {label} {path}: {error}") from error
    except yaml.YAMLError as error:
        raise RefreshError(f"invalid YAML in {label} {path}: {error}") from error


def _absolute_path(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RefreshError(f"{label} must be an absolute path: {value}")
    return path.resolve()


def _control_files(blueprint: dict[str, Any]) -> list[Path]:
    entries = blueprint.get("control_files")
    if not isinstance(entries, list) or not entries:
        raise RefreshError("blueprint.control_files must be a non-empty list")

    controls: list[Path] = []
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            raise RefreshError("every blueprint.control_files entry must be a path")
        path = Path(entry)
        if path.is_absolute() or ".." in path.parts or path == Path("."):
            raise RefreshError(f"invalid control file path: {entry}")
        controls.append(path)
    return controls


def _control_trees(blueprint: dict[str, Any]) -> list[Path]:
    entries = blueprint.get("control_trees") or []
    if not isinstance(entries, list):
        raise RefreshError("blueprint.control_trees must be a list")

    trees: list[Path] = []
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            raise RefreshError("every blueprint.control_trees entry must be a path")
        path = Path(entry)
        if path.is_absolute() or ".." in path.parts or path == Path("."):
            raise RefreshError(f"invalid control tree path: {entry}")
        trees.append(path)
    return trees


def _workspace_identity(manifest: dict[str, Any]) -> tuple[str, str, str]:
    catalog = _mapping(manifest.get("catalog"), "workspace manifest catalog")
    identity = (
        str(manifest.get("blueprint") or ""),
        str(catalog.get("system") or ""),
        str(catalog.get("release") or ""),
    )
    if not all(identity):
        raise RefreshError(
            "workspace manifest must record blueprint, catalog system, and release"
        )
    return identity


def _validate_values_identity(
    *, values: dict[str, Any], workspace: Path, existing_manifest: dict[str, Any]
) -> None:
    system = _mapping(values.get("system"), "values.system")
    system_name = str(system.get("name") or "")
    release = str(values.get("release") or "")
    manifest_system = _workspace_identity(existing_manifest)[1]
    if not system_name or not release:
        raise RefreshError("values must record system.name and release")
    if system_name != manifest_system:
        raise RefreshError(
            f"values system {system_name!r} does not match workspace system "
            f"{manifest_system!r}"
        )
    if release != workspace.name:
        raise RefreshError(
            f"values release {release!r} does not match workspace directory "
            f"{workspace.name!r}"
        )


def _safe_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise RefreshError(f"invalid refresh path: {relative}")
    path = root
    for part in ("", *relative.parts):
        path = path / part
        if path.is_symlink():
            raise RefreshError(f"unsafe symlink in refresh path: {path}")
    return path


def _fingerprint(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise RefreshError(f"unsafe symlink in control: {path}")
    if not path.exists():
        return None
    if not path.is_file() and not path.is_dir():
        raise RefreshError(f"unsupported control type: {path}")
    result: dict[str, Any] = {"mode": path.stat().st_mode & 0o7777}
    if path.is_file():
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        result["children"] = {p.name: _fingerprint(p) for p in sorted(path.iterdir())}
    return result


def _validate_paths(files: list[Path], trees: list[Path]) -> None:
    protected_roots = {
        "envs",
        "environments",
        "package-repos",
        "catalog",
        "store",
        "install",
        "installs",
        "cache",
        "caches",
        "views",
        "modules",
    }
    protected_names = {
        "spack.yaml",
        "spack.lock",
        "workspace-manifest.yaml",
        "manifest.yaml",
        "repos.yaml",
        "packages.yaml",
        "compilers.yaml",
        "concretizer.yaml",
    }
    paths = [*files, *trees]
    for path in paths:
        if (
            path.parts[0] in protected_roots
            or path.parts[0].startswith(".")
            or path.name in protected_names
            or (
                path.parts[0] == "configs"
                and path != Path("configs/common/config.yaml")
            )
        ):
            raise RefreshError(f"protected build input cannot be refreshed: {path}")
    for tree in trees:
        if tree not in (Path("modulefiles"), Path("presentation")):
            raise RefreshError(f"protected tree outside presentation scope: {tree}")
    for index, path in enumerate(paths):
        for other in paths[index + 1 :]:
            if path == other or path in other.parents or other in path.parents:
                raise RefreshError(f"overlapping refresh paths: {path}, {other}")


def _journal(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _copy(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


@contextmanager
def _refresh_lock(workspace: Path):
    lock = workspace / ".cse-refresh.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise RefreshError(
            f"workspace refresh lock exists: {lock}; check its owner before recovery"
        ) from error
    try:
        (lock / "owner.json").write_text(
            json.dumps({"pid": os.getpid()}), encoding="utf-8"
        )
        yield
    finally:
        shutil.rmtree(lock)


def _check_pending(workspace: Path, exclude: Path | None = None) -> None:
    history = _safe_path(workspace, Path(".cse-control-refresh"))
    recovering_sequence = None
    if exclude is not None:
        recovering_sequence = _load_mapping(exclude, "recovery record").get(
            "created_at_ns"
        )
        if not isinstance(recovering_sequence, int):
            raise RefreshError("recovery record is missing its creation sequence")
    for record in history.glob("*/record.json"):
        _safe_path(workspace, record.relative_to(workspace))
        if exclude is not None and record.absolute() == exclude.absolute():
            continue
        data = _load_mapping(record, "refresh record")
        if data.get("status") not in ("applied", "restored", "rolled-back"):
            if recovering_sequence is not None and isinstance(
                data.get("created_at_ns"), int
            ):
                if data["created_at_ns"] < recovering_sequence:
                    continue
            raise RefreshError(
                f"unfinished refresh requires recovery before another update (newest unfinished first): {record}"
            )


def _apply_transaction(
    workspace: Path,
    entries: list[tuple[Path, Path | None]],
    identity: tuple[str, str, str],
    scope: str,
) -> Path:
    history = _safe_path(workspace, Path(".cse-control-refresh"))
    history.mkdir(exist_ok=True)
    directory = history / uuid.uuid4().hex
    directory.mkdir()
    record_path = directory / "record.json"
    record: dict[str, Any] = {
        "schema_version": 1,
        "created_at_ns": time.time_ns(),
        "workspace": str(workspace.resolve()),
        "identity": list(identity),
        "scope": scope,
        "status": "preparing",
        "entries": [],
    }
    _journal(record_path, record)
    touched: list[int] = []
    try:
        for index, (relative, source) in enumerate(entries):
            destination = _safe_path(workspace, relative)
            old = _fingerprint(destination)
            new = _fingerprint(source) if source is not None else None
            slot = directory / str(index)
            slot.mkdir()
            if old is not None:
                _copy(destination, slot / "old")
            if source is not None:
                _copy(source, slot / "new")
            if _fingerprint(slot / "old") != old or _fingerprint(slot / "new") != new:
                raise RefreshError(f"control changed while staging refresh: {relative}")
            record["entries"].append({"path": str(relative), "old": old, "new": new})
        record["status"] = "applying"
        _journal(record_path, record)
        for index, (relative, source) in enumerate(entries):
            destination = _safe_path(workspace, relative)
            touched.append(index)
            slot = directory / str(index)
            if destination.is_dir():
                destination.replace(slot / "displaced")
            if source is None:
                _remove(destination)
            else:
                (slot / "new").replace(destination)
        record["status"] = "applied"
        _journal(record_path, record)
    except Exception as original:
        errors = []
        for index in reversed(touched):
            relative = entries[index][0]
            destination = workspace / relative
            slot = directory / str(index)
            try:
                if (slot / "old").exists():
                    _copy(slot / "old", slot / "rollback")
                _remove(destination)
                if (slot / "rollback").exists():
                    (slot / "rollback").replace(destination)
            except Exception as error:
                errors.append(f"{relative}: {error}")
        record["status"] = "recovery-required" if errors else "rolled-back"
        record["error"] = str(original)
        record["rollback_errors"] = errors
        _journal(record_path, record)
        if errors:
            raise RefreshError(
                f"refresh failed and rollback needs recovery: {record_path}: {'; '.join(errors)}"
            ) from original
        raise
    return record_path


def _refresh_control_files(
    *,
    blueprint_path: Path,
    staged_workspace: Path,
    workspace: Path,
    scope: str = "all",
    dry_run: bool = False,
) -> list[Path]:
    """Refresh selected controls, retaining a rollback record; never re-solve a DAG.

    Quiesce workspace users first: the set is rolled back on ordinary failures,
    but concurrent readers and power loss cannot see an atomic directory switch.
    """
    if scope not in ("all", "controls", "presentation"):
        raise RefreshError(f"unknown refresh scope: {scope}")
    blueprint = _load_mapping(blueprint_path, "blueprint")
    files, trees = _control_files(blueprint), _control_trees(blueprint)
    _validate_paths(files, trees)
    selected = (files if scope != "presentation" else []) + (
        trees if scope != "controls" else []
    )
    existing = _workspace_identity(
        _load_mapping(
            workspace / "workspace-manifest.yaml", "existing workspace manifest"
        )
    )
    staged = _workspace_identity(
        _load_mapping(
            staged_workspace / "workspace-manifest.yaml", "staged workspace manifest"
        )
    )
    if existing != staged:
        raise RefreshError(
            "staged controls do not match the existing blueprint, system, and release"
        )
    for relative in selected:
        source = _safe_path(staged_workspace, relative)
        destination = _safe_path(workspace, relative)
        expected = source.is_dir() if relative in trees else source.is_file()
        if not expected:
            raise RefreshError(f"staged control is missing or unsafe: {relative}")
        _fingerprint(source)
        _fingerprint(destination)
        if destination.exists() and source.is_dir() != destination.is_dir():
            raise RefreshError(f"existing control type differs: {relative}")
        if not destination.parent.is_dir():
            raise RefreshError(
                f"existing control directory is missing: {relative.parent}"
            )
    dependencies = _mapping(
        blueprint.get("control_file_dependencies", {}), "control_file_dependencies"
    )
    for control, requirements in dependencies.items():
        if Path(control) not in selected:
            continue
        if not isinstance(requirements, list) or not all(
            isinstance(p, str) for p in requirements
        ):
            raise RefreshError(f"invalid dependencies for control: {control}")
        for requirement in requirements:
            path = Path(requirement)
            source_root = (
                staged_workspace
                if any(p == path or p in path.parents for p in selected)
                else workspace
            )
            required = _safe_path(source_root, path)
            if not required.is_file():
                raise RefreshError(
                    f"{control} requires {requirement}; explicit candidate preparation required before controls refresh"
                )
    if not dry_run:
        _apply_transaction(
            workspace, [(p, staged_workspace / p) for p in selected], existing, scope
        )
    return selected


def _restore_control_files(
    *, workspace: Path, record_path: Path, dry_run: bool = False, recover: bool = False
) -> list[Path]:
    """Restore a successful refresh, refusing to overwrite subsequent edits."""
    history = _safe_path(workspace, Path(".cse-control-refresh"))
    record_path = record_path.absolute()
    if (
        record_path.parent.parent != history.absolute()
        or record_path.name != "record.json"
    ):
        raise RefreshError(
            "restore record must belong to this workspace's refresh history"
        )
    _safe_path(workspace, record_path.relative_to(workspace.absolute()))
    record = _load_mapping(record_path, "refresh record")
    identity = _workspace_identity(
        _load_mapping(workspace / "workspace-manifest.yaml", "workspace manifest")
    )
    if (
        record.get("schema_version") != 1
        or record.get("workspace") != str(workspace.resolve())
        or record.get("identity") != list(identity)
        or record.get("status")
        not in (
            {"preparing", "applying", "recovery-required", "restoring", "recovering"}
            if recover
            else {"applied"}
        )
    ):
        raise RefreshError(
            "restore/recovery requires a matching record status for this workspace and identity"
        )
    raw_entries = record.get("entries")
    if not isinstance(raw_entries, list) or not all(
        isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and "old" in e
        and "new" in e
        for e in raw_entries
    ):
        raise RefreshError("invalid refresh record entries")
    files, trees = [], []
    for entry in raw_entries:
        relative = Path(entry["path"])
        _safe_path(workspace, relative)
        is_tree = any(
            isinstance(entry[key], dict) and "children" in entry[key]
            for key in ("old", "new")
        )
        (trees if is_tree else files).append(relative)
    _validate_paths(files, trees)
    entries = []
    for index, entry in enumerate(record["entries"]):
        relative = Path(entry["path"])
        current = _safe_path(workspace, relative)
        backup = _safe_path(record_path.parent, Path(str(index)) / "old")
        expected = (entry["new"], entry["old"], None) if recover else (entry["new"],)
        if _fingerprint(current) not in expected:
            raise RefreshError(
                f"control changed since refresh: {relative}; reconcile later edits first"
            )
        if _fingerprint(backup) != entry["old"]:
            raise RefreshError(
                f"refresh backup no longer matches recorded content: {relative}"
            )
        entries.append((relative, backup if entry["old"] is not None else None))
    if not dry_run:
        previous_status = record["status"]
        record["status"] = "recovering" if recover else "restoring"
        _journal(record_path, record)
        try:
            recovery = _apply_transaction(
                workspace, entries, identity, "recovery" if recover else "restore"
            )
        except Exception:
            record["status"] = previous_status
            _journal(record_path, record)
            raise
        record["status"] = "rolled-back" if recover else "restored"
        record["restored_by"] = str(recovery)
        try:
            _journal(record_path, record)
        except OSError as error:
            raise RefreshError(
                f"controls restored, but the source record could not be finalized: {record_path}; "
                f"restoration evidence and undo are retained at {recovery}"
            ) from error
    return [p for p, _ in entries]


@contextmanager
def _refresh_access(workspace: Path, dry_run: bool, recover_record: Path | None = None):
    if dry_run:
        if (workspace / ".cse-refresh.lock").exists():
            raise RefreshError(
                f"workspace refresh lock exists: {workspace / '.cse-refresh.lock'}"
            )
        _check_pending(workspace, exclude=recover_record)
        yield
    else:
        with _refresh_lock(workspace):
            _check_pending(workspace, exclude=recover_record)
            yield


def refresh_control_files(
    *,
    blueprint_path: Path,
    staged_workspace: Path,
    workspace: Path,
    scope: str = "all",
    dry_run: bool = False,
) -> list[Path]:
    """Validate and refresh under one workspace lock; dry-run does not mutate it."""
    with _refresh_access(workspace, dry_run):
        return _refresh_control_files(
            blueprint_path=blueprint_path,
            staged_workspace=staged_workspace,
            workspace=workspace,
            scope=scope,
            dry_run=dry_run,
        )


def restore_control_files(
    *, workspace: Path, record_path: Path, dry_run: bool = False
) -> list[Path]:
    """Check for later edits and restore a successful refresh under one lock."""
    with _refresh_access(workspace, dry_run):
        return _restore_control_files(
            workspace=workspace, record_path=record_path, dry_run=dry_run
        )


def recover_control_files(
    *, workspace: Path, record_path: Path, dry_run: bool = False
) -> list[Path]:
    """Finish rolling an interrupted refresh back to its recorded prior controls."""
    with _refresh_access(workspace, dry_run, recover_record=record_path):
        return _restore_control_files(
            workspace=workspace, record_path=record_path, dry_run=dry_run, recover=True
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh generated workspace controls, presentation modulefiles, and "
            "common configuration while "
            "preserving environment YAML, lockfiles, caches, views, and installed "
            "packages."
        )
    )
    parser.add_argument("--composer")
    parser.add_argument("--blueprint")
    parser.add_argument("--values")
    parser.add_argument("--workspace", required=True)
    parser.add_argument(
        "--scope", choices=("presentation", "controls", "all"), default="all"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and list paths without changing the workspace",
    )
    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument(
        "--restore-from",
        help="restore a retained record.json instead of rendering controls",
    )
    recovery.add_argument(
        "--recover-from",
        help="roll an unfinished refresh back using its retained record.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    staged_workspace: Path | None = None
    staging_parent: Path | None = None
    try:
        workspace = _absolute_path(args.workspace, "workspace")
        if args.restore_from or args.recover_from:
            restore = (
                recover_control_files if args.recover_from else restore_control_files
            )
            restored = restore(
                workspace=workspace,
                record_path=_absolute_path(
                    args.restore_from or args.recover_from, "restore record"
                ),
                dry_run=args.dry_run,
            )
            print("Would restore:" if args.dry_run else "Restored:")
            for relative in restored:
                print(f"  {relative}")
            return 0
        if not all((args.composer, args.blueprint, args.values)):
            raise RefreshError(
                "--composer, --blueprint, and --values are required for refresh"
            )
        composer = _absolute_path(args.composer, "composer")
        blueprint_dir = _absolute_path(args.blueprint, "blueprint")
        values = _absolute_path(args.values, "values")
        workspace = _absolute_path(args.workspace, "workspace")
        catalog = workspace / "catalog"

        if not composer.is_file():
            raise RefreshError(f"Stack Composer entry point is missing: {composer}")
        if not (blueprint_dir / "blueprint.yaml").is_file():
            raise RefreshError(f"blueprint is missing: {blueprint_dir}")
        if not values.is_file():
            raise RefreshError(f"values file is missing: {values}")
        if not workspace.is_dir():
            raise RefreshError(f"workspace is missing: {workspace}")
        if not (catalog / "manifest.yaml").is_file():
            raise RefreshError(f"workspace catalog snapshot is missing: {catalog}")

        _validate_values_identity(
            values=_load_mapping(values, "values"),
            workspace=workspace,
            existing_manifest=_load_mapping(
                workspace / "workspace-manifest.yaml",
                "existing workspace manifest",
            ),
        )

        staging_parent = Path(
            tempfile.mkdtemp(
                prefix=f".{workspace.name}.control-refresh-", dir=workspace.parent
            )
        )
        staged_workspace = staging_parent / "workspace"

        command = [
            sys.executable,
            str(composer),
            "init-workspace",
            "--blueprint",
            str(blueprint_dir),
            "--catalog",
            str(catalog),
            "--values",
            str(values),
            "--output",
            str(staged_workspace),
        ]
        subprocess.run(command, check=True)
        refreshed = refresh_control_files(
            blueprint_path=blueprint_dir / "blueprint.yaml",
            staged_workspace=staged_workspace,
            workspace=workspace,
            scope=args.scope,
            dry_run=args.dry_run,
        )
    except (RefreshError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        if staging_parent is not None and staging_parent.exists():
            shutil.rmtree(staging_parent)

    print(
        "Would refresh workspace controls:"
        if args.dry_run
        else "Refreshed workspace controls:"
    )
    for relative in refreshed:
        print(f"  {relative}")
    if not args.dry_run:
        print(f"Restore records: {workspace / '.cse-control-refresh'}/*/record.json")
    print("Preserved environment YAML, lockfiles, caches, views, and installs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
