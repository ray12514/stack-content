#!/usr/bin/env python3
"""Refresh generated pilot controls without replacing build inputs or locks."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml


STARTUP_CONTROL_FILES = tuple(Path(name) for name in (
    "cse-build", "env/share-generated-permissions.sh", "env/workspace-shell.rc",
    "env/setup-build-env.sh", "scripts/verify-overlay-inputs.py",
    "scripts/verify-workspace-inputs.py", "scripts/workspace-build.py",
    "scripts/workspace-overlay.py", "scripts/overlay-recovery.py",
    "scripts/module-preview.py",
    "scripts/workspace-permissions.py", "BUILDER-HANDOFF.md",
))
STARTUP_INVENTORY = Path("package-repos/overlay-inventory.json")
STARTUP_CONFIG = Path("configs/common/config.yaml")
# These are the inputs consumed by the startup templates, not the full build
# blueprint. In particular, refreshing controls must not resolve a repository
# tag or fabricate a package commit just to render an unused repos.yaml.
STARTUP_REQUIRED_VALUES = (
    "workspace.role", "system.name", "release", "architecture.target", "build_jobs",
    "permissions.group", "permissions.read", "permissions.write",
    "spack.source", "spack.version", "spack.tag", "spack.commit",
    "spack.default_mode", "spack.shared_root", "spack.initial_root",
    "paths.install_tree", "paths.source_cache", "paths.misc_cache",
    "paths.views_root", "paths.modules_root", "buildcache.url",
    "shared.compiler.name", "shared.compiler.version",
    "shared.compiler.public_name", "shared.compiler.source",
    "shared.mpi.name", "shared.mpi.version", "shared.mpi.source",
    "platform.compiler.name", "platform.compiler.version",
    "platform.compiler.public_name", "platform.compiler.source",
    "platform.mpi.name", "platform.mpi.version", "platform.mpi.source",
)


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
    *,
    path_policy: str = "controls",
    guards: dict[str, Any] | None = None,
    missing_environments: set[str] | None = None,
) -> Path:
    _validate_transaction_paths([p for p, _ in entries], path_policy)
    if guards is not None:
        _check_guards(workspace, guards, missing_environments)
        _validate_policy_payload(entries, path_policy, guards)
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
        "path_policy": path_policy,
        "guards": guards,
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
        if guards is not None:
            _check_guards(workspace, guards, missing_environments)
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
        if guards is not None:
            _check_guards(workspace, guards)
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
                # Retain the promoted state intact. Recursive removal can fail
                # halfway through a tree, making later recovery mistake our own
                # partial deletion for an unrelated operator edit.
                if destination.exists() or destination.is_symlink():
                    destination.replace(slot / "failed")
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


def _validate_transaction_paths(paths: list[Path], policy: str) -> None:
    if policy == "controls":
        _validate_paths(
            [p for p in paths if p not in (Path("modulefiles"), Path("presentation"))],
            [p for p in paths if p in (Path("modulefiles"), Path("presentation"))],
        )
    elif policy == "startup":
        allowed = set(STARTUP_CONTROL_FILES) | {STARTUP_INVENTORY, STARTUP_CONFIG}
        if not paths or len(set(paths)) != len(paths) or not set(paths).issubset(allowed):
            raise RefreshError("startup refresh may change only its runtime controls, inventory, and cache selector")
    elif policy == "module-policy":
        environments, modules = set(), set()
        for path in paths:
            name = str(path)
            match = re.fullmatch(
                r"environments/([^/.][^/]*)/([^/.][^/]*)/spack.yaml", name
            )
            module = re.fullmatch(
                r"configs/environments/([^/.][^/]*)/([^/.][^/]*)/modules.yaml", name
            )
            if match:
                environments.add(match.groups())
            elif module:
                modules.add(module.groups())
            else:
                raise RefreshError(f"invalid module-policy path: {path}")
        if (
            not environments
            or environments != modules
            or len(paths) != 2 * len(environments)
        ):
            raise RefreshError(
                "module-policy requires one environment/module configuration pair per environment"
            )
    elif policy == "overlay-admission":
        if (
            set(paths)
            != {
                Path("package-repos/overlay-inventory.json"),
                Path("scripts/verify-overlay-inputs.py"),
            }
            or len(paths) != 2
        ):
            raise RefreshError("overlay admission may change only inventory and helper")
    else:
        raise RefreshError(f"unsupported transaction path policy: {policy}")


def _environment_document(path: Path) -> dict[str, Any]:
    document = _load_mapping(path, "environment")
    if set(document) != {"spack"}:
        raise RefreshError(f"unsupported environment mapping: {path}")
    _mapping(document["spack"], "environment spack")
    return document


def _without_view(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["spack"].pop("view", None)
    return result


def _configuration_fingerprint(path: Path, workspace: Path, ignored: set[str]) -> Any:
    if path.is_symlink():
        raise RefreshError(f"unsafe symlink in configuration: {path}")
    if not path.is_dir():
        return _fingerprint(path)
    return {
        "mode": path.stat().st_mode & 0o7777,
        "children": {
            p.name: _configuration_fingerprint(p, workspace, ignored)
            for p in sorted(path.iterdir())
            if str(p.relative_to(workspace)) not in ignored
        },
    }


def _input_guards(
    workspace: Path, module_policy_paths: list[str] | None = None,
    startup_config: list[Any] | None = None,
) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    ignored = set(module_policy_paths or [])
    if startup_config is not None:
        ignored.add(str(STARTUP_CONFIG))
    for relative in (
        Path("workspace-manifest.yaml"),
        Path("catalog"),
        Path("configs/common"),
        Path("configs/surfaces"),
    ):
        path = _safe_path(workspace, relative)
        if relative == Path("configs/common") and startup_config is not None:
            paths[str(relative)] = _configuration_fingerprint(path, workspace, ignored)
        else:
            paths[str(relative)] = _fingerprint(path)
    repositories = _safe_path(workspace, Path("package-repos"))
    if repositories.exists():
        for child in sorted(repositories.iterdir()):
            if child.name != "overlay-inventory.json":
                paths[str(child.relative_to(workspace))] = _fingerprint(child)
    environments = {}
    for path in sorted(workspace.glob("environments/*/*/spack.yaml")):
        relative = path.relative_to(workspace)
        _safe_path(workspace, relative)
        environments[str(relative)] = _without_view(_environment_document(path))
        lock = relative.with_name("spack.lock")
        paths[str(lock)] = _fingerprint(_safe_path(workspace, lock))
    result = {
        "paths": paths,
        "environments": environments,
        "module_policy_paths": sorted(module_policy_paths or []),
        "configuration": _configuration_fingerprint(
            _safe_path(workspace, Path("configs")),
            workspace,
            ignored,
        ),
        "repository_entries": sorted(
            p.name for p in repositories.iterdir() if p.name != "overlay-inventory.json"
        )
        if repositories.exists()
        else None,
    }
    if startup_config is not None:
        result["startup_config"] = startup_config
    return result


def _check_guards(
    workspace: Path,
    expected: dict[str, Any],
    missing_environments: set[str] | None = None,
) -> None:
    startup_config = expected.get("startup_config")
    if startup_config is not None and _fingerprint(
        _safe_path(workspace, STARTUP_CONFIG)
    ) not in startup_config:
        raise RefreshError("workspace cache configuration changed during startup refresh")
    actual = _input_guards(workspace, expected.get("module_policy_paths"), startup_config)
    # Earlier records predate per-environment configuration fingerprints.
    if "configuration" not in expected:
        actual.pop("configuration")
        actual.pop("module_policy_paths")
    for name in missing_environments or ():
        if (
            name in expected.get("environments", {})
            and not _safe_path(workspace, Path(name)).exists()
        ):
            actual["environments"][name] = expected["environments"][name]
            lock = str(Path(name).with_name("spack.lock"))
            actual["paths"][lock] = _fingerprint(_safe_path(workspace, Path(lock)))
    if actual != expected:
        raise RefreshError(
            "protected workspace inputs changed; locks, configuration, catalog and recipes must match the recorded upgrade"
        )


def _validate_policy_payload(entries, policy, guards) -> None:
    if policy == "startup":
        for relative, source in entries:
            if relative == STARTUP_CONFIG and (
                source is None or _fingerprint(source) not in guards.get("startup_config", [])
            ):
                raise RefreshError("startup refresh cache selector does not match the guarded configuration")
        return
    if policy != "module-policy":
        return
    for relative, source in entries:
        if relative.name == "spack.yaml":
            if source is None or _without_view(
                _environment_document(source)
            ) != guards.get("environments", {}).get(str(relative)):
                raise RefreshError(
                    f"module-policy cannot change non-view environment semantics: {relative}"
                )
        elif source is not None:
            modules = _load_mapping(source, "module policy")
            if set(modules) != {"modules"} or not isinstance(modules["modules"], dict):
                raise RefreshError(
                    f"module policy must contain only a modules mapping: {relative}"
                )


def upgrade_module_policy(
    *,
    workspace: Path,
    candidate: Path,
    environments: list[str] | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Adopt reviewed module settings and named views without changing a solve."""
    with _refresh_access(workspace, dry_run):
        identity = _workspace_identity(
            _load_mapping(workspace / "workspace-manifest.yaml", "workspace manifest")
        )
        if identity != _workspace_identity(
            _load_mapping(candidate / "workspace-manifest.yaml", "candidate manifest")
        ):
            raise RefreshError("candidate and workspace identities do not match")
        old_environments = {
            str(p.parent.relative_to(workspace / "environments"))
            for p in workspace.glob("environments/*/*/spack.yaml")
        }
        candidate_environments = {
            str(p.parent.relative_to(candidate / "environments"))
            for p in candidate.glob("environments/*/*/spack.yaml")
        }
        candidate_modules = {
            str(p.parent.relative_to(candidate / "configs/environments"))
            for p in candidate.glob("configs/environments/*/*/modules.yaml")
        }
        selected = sorted(old_environments if environments is None else environments)
        if (
            not selected
            or len(selected) != len(set(selected))
            or not set(selected) <= old_environments
        ):
            raise RefreshError(
                "selected environments must be distinct existing workspace environments"
            )
        if environments is None and (
            candidate_environments != old_environments
            or candidate_modules != old_environments
        ):
            raise RefreshError(
                "candidate environment and module sets must match the workspace"
            )
        if not set(selected) <= candidate_environments & candidate_modules:
            raise RefreshError(
                "selected candidate environments require module configuration"
            )
        guards = _input_guards(
            workspace,
            [f"configs/environments/{name}/modules.yaml" for name in selected],
        )
        paths: list[Path] = []
        with tempfile.TemporaryDirectory(prefix="cse-module-policy-") as directory:
            entries = []
            for environment in selected:
                relative = Path("environments") / environment / "spack.yaml"
                module_relative = (
                    Path("configs/environments") / environment / "modules.yaml"
                )
                paths.extend((relative, module_relative))
                _validate_transaction_paths(
                    [relative, module_relative], "module-policy"
                )
                old_path = _safe_path(workspace, relative)
                lock = _safe_path(workspace, relative.with_name("spack.lock"))
                if not lock.is_file():
                    raise RefreshError(
                        f"module-policy requires an existing lock: {lock}"
                    )
                old = _environment_document(old_path)
                proposed = _environment_document(_safe_path(candidate, relative))
                module_source = _safe_path(candidate, module_relative)
                modules = _load_mapping(module_source, "candidate module policy")
                if set(modules) != {"modules"} or not isinstance(
                    modules["modules"], dict
                ):
                    raise RefreshError(
                        "module policy must contain only a modules mapping"
                    )
                includes = old["spack"].get("include:", old["spack"].get("include"))
                if not isinstance(includes, list) or not all(
                    isinstance(p, str) for p in includes
                ):
                    raise RefreshError(
                        "module-policy requires explicit ordered string includes"
                    )
                destination = _safe_path(workspace, module_relative)
                active = {(old_path.parent / p).resolve() for p in includes}
                if (
                    destination.resolve() not in active
                    and destination.parent.resolve() not in active
                ):
                    raise RefreshError(
                        f"module scope is not active in old environment: {module_relative}"
                    )
                if not destination.parent.is_dir():
                    raise RefreshError(
                        f"existing module directory is missing: {destination.parent}"
                    )
                views = old["spack"].get("view", {})
                if views is False:
                    views = {}
                views = copy.deepcopy(_mapping(views, "existing named views"))
                proposed_views = _mapping(
                    proposed["spack"].get("view"), "candidate named views"
                )
                specs = old["spack"].get("specs")
                if not isinstance(specs, list):
                    raise RefreshError("old environment specs must be a list")
                groups = {
                    item["group"]
                    for item in specs
                    if isinstance(item, dict) and isinstance(item.get("group"), str)
                }
                for name, view in proposed_views.items():
                    view = _mapping(view, "candidate named view")
                    if (
                        not isinstance(name, str)
                        or not name
                        or not isinstance(view.get("root"), str)
                        or not view["root"]
                    ):
                        raise RefreshError(
                            "candidate view requires a name and string root"
                        )
                    if "group" in view and (
                        not isinstance(view["group"], str)
                        or view["group"] not in groups
                    ):
                        raise RefreshError(
                            f"view {name} refers to a missing spec group: {view['group']}"
                        )
                    views[name] = view
                for name, module in modules["modules"].items():
                    if (
                        isinstance(module, dict)
                        and isinstance(module.get("use_view"), str)
                        and module["use_view"] not in views
                    ):
                        raise RefreshError(
                            f"module set {name} refers to a missing named view"
                        )
                old["spack"]["view"] = views
                staged = Path(directory) / str(len(entries))
                staged.write_text(
                    yaml.safe_dump(old, sort_keys=False), encoding="utf-8"
                )
                shutil.copymode(old_path, staged)
                entries.extend(((relative, staged), (module_relative, module_source)))
            _validate_policy_payload(entries, "module-policy", guards)
            if not dry_run:
                _apply_transaction(
                    workspace,
                    entries,
                    identity,
                    "module-policy",
                    path_policy="module-policy",
                    guards=guards,
                )
        return paths


def admit_overlay_inventory(
    *, workspace: Path, inventory_path: Path, helper_path: Path, dry_run: bool = False
) -> list[Path]:
    """Admit a reviewed inventory of existing recipes, retaining their exact bytes.

    The helper is trusted executable tooling explicitly selected by the operator;
    recipe files and inventory content are data and are never imported.
    """
    with _refresh_access(workspace, dry_run):
        identity = _workspace_identity(
            _load_mapping(workspace / "workspace-manifest.yaml", "workspace manifest")
        )
        guards = _input_guards(workspace)
        for source in (inventory_path, helper_path):
            if source.is_symlink() or not source.is_file():
                raise RefreshError(f"admission input must be a regular file: {source}")
        repository = _safe_path(workspace, Path("package-repos"))
        if not repository.is_dir():
            raise RefreshError(
                "existing package-repos directory is required for admission"
            )
        paths = [
            Path("package-repos/overlay-inventory.json"),
            Path("scripts/verify-overlay-inputs.py"),
        ]
        for relative in paths:
            destination = _safe_path(workspace, relative)
            if not destination.parent.is_dir():
                raise RefreshError(
                    f"existing admission directory is missing: {destination.parent}"
                )
        with tempfile.TemporaryDirectory(prefix="cse-overlay-admission-") as directory:
            snapshot = Path(directory) / "package-repos"
            shutil.copytree(repository, snapshot)
            inventory = snapshot / "overlay-inventory.json"
            shutil.copy2(inventory_path, inventory)
            helper = Path(directory) / "verify-overlay-inputs.py"
            shutil.copy2(helper_path, helper)
            try:
                verified = subprocess.run(
                    [sys.executable, str(helper), "--root", str(snapshot), "--check"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=60,
                )
            except subprocess.TimeoutExpired as error:
                raise RefreshError(
                    "overlay inventory verification timed out"
                ) from error
            if verified.returncode:
                raise RefreshError(
                    f"reviewed overlay inventory does not match existing recipes: {verified.stdout.strip()}"
                )
            _check_guards(workspace, guards)
            if not dry_run:
                _apply_transaction(
                    workspace,
                    [(paths[0], inventory), (paths[1], helper)],
                    identity,
                    "overlay-admission",
                    path_policy="overlay-admission",
                    guards=guards,
                )
        return paths


def _startup_bindings(launcher: Path) -> dict[str, str]:
    # Compare rendered shell assignments as data, without sourcing either file.
    names = {"CSE_INSTALL_TREE_ROOT", "CSE_SHARED_SOURCE_CACHE_ROOT", "CSE_SHARED_MISC_CACHE_ROOT",
             "CSE_VIEWS_ROOT", "CSE_MODULES_ROOT", "CSE_BUILDCACHE_URL"}
    bindings = {}
    for line in launcher.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"(?:readonly|export) ([A-Z_]+)=(.+)", line)
        if match and (match[1].startswith("CSE_RECORDED_") or match[1] in names):
            bindings[match[1]] = match[2]
    if not names.issubset(bindings) or "CSE_RECORDED_SPACK_COMMIT" not in bindings:
        raise RefreshError("cannot verify recorded startup roots/identity in " + str(launcher))
    return bindings


def _setup_bindings(path: Path) -> dict[str, str]:
    names = {
        "CSE_GROUP", "CSE_CPU_TARGET", "CSE_SYSTEM_NAME", "CSE_TRIAL_RELEASE",
        "SHARED_COMPILER_NAME", "SHARED_MPI_NAME", "PLATFORM_COMPILER_NAME",
        "PLATFORM_MPI_NAME", "BUILD_JOBS", "CSE_SPACK_SOURCE", "CSE_SPACK_VERSION",
        "CSE_SPACK_TAG", "CSE_SPACK_COMMIT", "CSE_SPACK_DEFAULT_MODE",
        "CSE_SPACK_SHARED_ROOT", "CSE_SPACK_INITIAL_ROOT",
    }
    bindings = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"export ([A-Z_]+)=(.+)", line)
        if match and match[1] in names:
            try:
                tokens = shlex.split(match[2])
            except ValueError as error:
                raise RefreshError(f"invalid recorded setup assignment in {path}") from error
            if len(tokens) != 1 or match[1] in bindings:
                raise RefreshError(f"ambiguous recorded setup assignment in {path}")
            bindings[match[1]] = tokens[0]
    if set(bindings) != names:
        raise RefreshError(f"cannot verify recorded setup identity in {path}")
    return bindings


def _stage_startup_blueprint(blueprint_dir: Path, destination: Path) -> Path:
    """Give Composer only the startup templates and their value requirements.

    The derived blueprint and its manifest live in disposable staging. Neither
    the recorded values nor the original blueprint's full-render contract is
    changed. This render does not produce repository or environment configuration.
    """
    blueprint = _load_mapping(blueprint_dir / "blueprint.yaml", "blueprint")
    files = _control_files(blueprint)
    _validate_paths(files, _control_trees(blueprint))
    if any(path not in files for path in STARTUP_CONTROL_FILES):
        raise RefreshError("blueprint does not declare the complete startup control set")
    template_root = _safe_path(
        blueprint_dir, Path(str(blueprint.get("template_root") or "."))
    )
    for relative in STARTUP_CONTROL_FILES:
        source = _safe_path(template_root, Path(str(relative) + ".j2"))
        if not source.is_file():
            source = _safe_path(template_root, relative)
        if not source.is_file():
            raise RefreshError(f"startup template is missing: {relative}")
        target = destination / "templates" / source.relative_to(template_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    blueprint.update(
        template_root="templates",
        snapshot_catalog=False,
        required_values=list(STARTUP_REQUIRED_VALUES),
        allowed_values={
            key: value
            for key, value in _mapping(
                blueprint.get("allowed_values", {}), "blueprint.allowed_values"
            ).items()
            if key in STARTUP_REQUIRED_VALUES
        },
        catalog_scope_values=[],
        data_files={},
    )
    (destination / "blueprint.yaml").write_text(
        yaml.safe_dump(blueprint, sort_keys=False), encoding="utf-8"
    )
    return destination


def _prepare_startup_inputs(workspace: Path, staged: Path) -> tuple[list[Path], dict[str, Any]]:
    """Complete the runtime bundle from existing inputs, never newer recipes."""
    guards = _input_guards(workspace)
    selected: list[Path] = []
    inventory = _safe_path(workspace, STARTUP_INVENTORY)
    helper = _safe_path(staged, Path("scripts/verify-overlay-inputs.py"))
    command = [sys.executable, str(helper), "--root", str(workspace / "package-repos")]
    if inventory.exists():
        command.append("--check")
    else:
        candidate = staged / STARTUP_INVENTORY
        candidate.parent.mkdir(parents=True, exist_ok=True)
        command.extend(("--candidate", str(candidate)))
        selected.append(STARTUP_INVENTORY)
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise RefreshError("startup overlay inventory preparation timed out") from error
    if result.returncode:
        if not inventory.exists():
            raise RefreshError("existing workspace overlay inputs are invalid: " + result.stdout.strip())
        print("WARNING: keeping the existing overlay inventory unchanged while updating "
              "repair controls. Register intentional recipe changes separately.\n"
              + result.stdout.strip(), file=sys.stderr)
    if STARTUP_INVENTORY in selected:
        shutil.copymode(workspace / "workspace-manifest.yaml", staged / STARTUP_INVENTORY)

    config = _safe_path(workspace, STARTUP_CONFIG)
    original = config.read_bytes().decode("utf-8")
    selector = "  misc_cache: ${SPACK_MISC_CACHE_PATH}"
    if selector not in original.splitlines():
        document = _load_mapping(config, "workspace configuration")
        settings = _mapping(document.get("config"), "workspace config")
        root = yaml.safe_load(_startup_bindings(workspace / "cse-build")["CSE_SHARED_MISC_CACHE_ROOT"])
        if settings.get("misc_cache") not in (root, "${SPACK_MISC_CACHE_PATH}"):
            raise RefreshError("workspace misc_cache differs from the recorded launcher root")
        lines = original.splitlines(keepends=True)
        indexes = [i for i, line in enumerate(lines) if line.startswith("  misc_cache:")]
        if len(indexes) != 1:
            raise RefreshError("workspace configuration must contain one misc_cache scalar")
        index = indexes[0]
        ending = ""
        if lines[index].endswith("\n"):
            ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
        lines[index] = selector + ending
        rendered = "".join(lines)
        expected = copy.deepcopy(document)
        expected["config"]["misc_cache"] = "${SPACK_MISC_CACHE_PATH}"
        if yaml.safe_load(rendered) != expected:
            raise RefreshError("startup cache selector would change other configuration")
        candidate = staged / STARTUP_CONFIG
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(rendered, encoding="utf-8")
        shutil.copymode(config, candidate)
        selected.append(STARTUP_CONFIG)
    _check_guards(workspace, guards)
    if STARTUP_CONFIG in selected:
        guards = _input_guards(workspace, startup_config=[
            _fingerprint(config), _fingerprint(staged / STARTUP_CONFIG)
        ])
    return selected, guards


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
    if scope not in ("all", "controls", "presentation", "startup"):
        raise RefreshError(f"unknown refresh scope: {scope}")
    blueprint = _load_mapping(blueprint_path, "blueprint")
    files, trees = _control_files(blueprint), _control_trees(blueprint)
    _validate_paths(files, trees)
    selected = (files if scope != "presentation" else []) + (
        trees if scope != "controls" else []
    )
    if scope == "startup":
        selected = list(STARTUP_CONTROL_FILES)
        if any(path not in files for path in selected):
            raise RefreshError("blueprint does not declare the complete startup control set")
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
    guards = None
    if scope == "startup":
        if _startup_bindings(workspace / "cse-build") != _startup_bindings(staged_workspace / "cse-build"):
            raise RefreshError("startup refresh would change recorded roots or runtime identity; use this workspace's recorded values")
        setup = Path("env/setup-build-env.sh")
        if _setup_bindings(_safe_path(workspace, setup)) != _setup_bindings(_safe_path(staged_workspace, setup)):
            raise RefreshError("startup refresh would change recorded setup identity; use this workspace's recorded values")
        additions, guards = _prepare_startup_inputs(workspace, staged_workspace)
        selected.extend(additions)
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
    missing_dependencies = []
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
                missing_dependencies.append(f"{control} requires {requirement}")
    if missing_dependencies:
        detail = "; ".join(missing_dependencies)
        if scope == "startup":
            raise RefreshError("startup bundle is missing recorded workspace inputs: " + detail)
        raise RefreshError(detail + "; explicit candidate preparation required before controls refresh")
    if not dry_run:
        _apply_transaction(
            workspace, [(p, staged_workspace / p) for p in selected], existing, scope,
            path_policy="startup" if scope == "startup" else "controls", guards=guards,
        )
    elif guards is not None:
        _check_guards(workspace, guards)
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
    policy = record.get("path_policy", "controls")
    guards = record.get("guards")
    missing_environments = (
        {str(p) for p in files if p.name == "spack.yaml"} if recover else None
    )
    if policy != "controls" and not isinstance(guards, dict):
        raise RefreshError("upgrade recovery requires recorded protected input guards")
    if guards is not None:
        _check_guards(workspace, guards, missing_environments)
    if recover and record["status"] == "preparing" and not raw_entries:
        if policy not in ("controls", "module-policy", "overlay-admission", "startup"):
            raise RefreshError(f"unsupported transaction path policy: {policy}")
        if not dry_run:
            record["status"] = "rolled-back"
            record["recovery_note"] = (
                "staging was interrupted before any workspace mutation"
            )
            _journal(record_path, record)
        return []
    _validate_transaction_paths([*files, *trees], policy)
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
    if guards is not None:
        _validate_policy_payload(entries, policy, guards)
    if not dry_run:
        previous_status = record["status"]
        record["status"] = "recovering" if recover else "restoring"
        _journal(record_path, record)
        try:
            recovery = _apply_transaction(
                workspace,
                entries,
                identity,
                "recovery" if recover else "restore",
                path_policy=policy,
                guards=guards,
                missing_environments=missing_environments,
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
def _finite_operation_lock(workspace: Path, dry_run: bool):
    # Share the generated launcher's lock. Refresh's directory lock alone cannot
    # stop a build from opening a helper halfway through control replacement.
    path = _safe_path(workspace, Path(".cse-maintenance.lock"))
    flags = os.O_RDWR | os.O_NOFOLLOW
    if not dry_run:
        flags |= os.O_CREAT
    try:
        fd = os.open(path, flags, 0o660)
    except FileNotFoundError:
        if not dry_run:
            raise
        yield  # Read-only previews do not create a missing lock file.
        return
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RefreshError("workspace maintenance lock is not a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RefreshError("another finite workspace operation is active; refresh between commands") from error
        if not dry_run and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) != 0o660:
            os.fchmod(fd, 0o660)
        yield
    finally:
        os.close(fd)


@contextmanager
def _refresh_access(workspace: Path, dry_run: bool, recover_record: Path | None = None):
    if dry_run:
        if (workspace / ".cse-refresh.lock").exists():
            raise RefreshError(
                f"workspace refresh lock exists: {workspace / '.cse-refresh.lock'}"
            )
        with _finite_operation_lock(workspace, True):
            _check_pending(workspace, exclude=recover_record)
            yield
    else:
        with _finite_operation_lock(workspace, False), _refresh_lock(workspace):
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
        "--candidate",
        help="separately reviewed candidate workspace for module-policy migration",
    )
    parser.add_argument(
        "--environment",
        action="append",
        help="existing compiler/environment to upgrade; repeat to select several",
    )
    parser.add_argument(
        "--admit-overlay-inventory",
        help="explicitly reviewed inventory of this workspace's existing recipes",
    )
    parser.add_argument(
        "--overlay-helper",
        help="trusted overlay verification helper to admit with the inventory",
    )
    parser.add_argument(
        "--scope",
        choices=("presentation", "controls", "all", "module-policy", "startup"),
        default="all",
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
        if args.scope == "module-policy" or args.admit_overlay_inventory:
            if (
                args.restore_from
                or args.recover_from
                or any((args.composer, args.blueprint, args.values))
            ):
                raise RefreshError(
                    "explicit upgrade modes cannot be combined with render or recovery arguments"
                )
            if args.scope == "module-policy":
                if (
                    not args.candidate
                    or args.admit_overlay_inventory
                    or args.overlay_helper
                ):
                    raise RefreshError(
                        "module-policy requires --candidate and cannot include overlay admission"
                    )
                changed = upgrade_module_policy(
                    workspace=workspace,
                    candidate=_absolute_path(args.candidate, "candidate"),
                    environments=args.environment,
                    dry_run=args.dry_run,
                )
                operation = "upgrade module policy"
            else:
                if (
                    not args.overlay_helper
                    or args.candidate
                    or args.environment
                    or args.scope != "all"
                ):
                    raise RefreshError(
                        "overlay admission requires --overlay-helper and cannot include another scope"
                    )
                changed = admit_overlay_inventory(
                    workspace=workspace,
                    inventory_path=_absolute_path(
                        args.admit_overlay_inventory, "inventory"
                    ),
                    helper_path=_absolute_path(args.overlay_helper, "overlay helper"),
                    dry_run=args.dry_run,
                )
                operation = "admit overlay inventory and helper"
            print(("Would " if args.dry_run else "Completed ") + operation + ":")
            for relative in changed:
                print(f"  {relative}")
            if not args.dry_run:
                print(
                    f"Restore records: {workspace / '.cse-control-refresh'}/*/record.json"
                )
            print(
                "Preserved concrete inputs, lockfiles, repository pins and recipes, and installed packages."
            )
            return 0
        if args.candidate or args.environment or args.overlay_helper:
            raise RefreshError(
                "candidate/environment/helper arguments require their explicit upgrade mode"
            )
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
        render_blueprint = (
            _stage_startup_blueprint(blueprint_dir, staging_parent / "blueprint")
            if args.scope == "startup"
            else blueprint_dir
        )

        command = [
            sys.executable,
            str(composer),
            "init-workspace",
            "--blueprint",
            str(render_blueprint),
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
