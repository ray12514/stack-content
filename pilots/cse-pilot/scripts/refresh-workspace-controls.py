#!/usr/bin/env python3
"""Refresh generated pilot controls without replacing build inputs or locks."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
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


def refresh_control_files(
    *,
    blueprint_path: Path,
    staged_workspace: Path,
    workspace: Path,
) -> list[Path]:
    """Replace only blueprint-declared control files in an existing workspace."""
    blueprint = _load_mapping(blueprint_path, "blueprint")
    controls = _control_files(blueprint)
    existing_manifest = _load_mapping(
        workspace / "workspace-manifest.yaml", "existing workspace manifest"
    )
    staged_manifest = _load_mapping(
        staged_workspace / "workspace-manifest.yaml", "staged workspace manifest"
    )
    if _workspace_identity(existing_manifest) != _workspace_identity(staged_manifest):
        raise RefreshError(
            "staged controls do not match the existing blueprint, system, and release"
        )

    for relative in controls:
        source = staged_workspace / relative
        destination = workspace / relative
        if not source.is_file() or source.is_symlink():
            raise RefreshError(f"staged control file is missing or unsafe: {relative}")
        if not destination.parent.is_dir():
            raise RefreshError(
                f"existing control directory is missing: {relative.parent}"
            )

    pending: list[tuple[Path, Path]] = []
    try:
        for relative in controls:
            source = staged_workspace / relative
            destination = workspace / relative
            temporary = destination.with_name(f".{destination.name}.cse-refresh")
            if temporary.exists():
                raise RefreshError(f"stale control refresh file exists: {temporary}")
            shutil.copyfile(source, temporary)
            os.chmod(temporary, source.stat().st_mode & 0o7777)
            pending.append((temporary, destination))
        for temporary, destination in pending:
            temporary.replace(destination)
    finally:
        for temporary, _destination in pending:
            temporary.unlink(missing_ok=True)
    return controls


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh generated workspace controls and common configuration while "
            "preserving environment YAML, lockfiles, caches, views, and installed "
            "packages."
        )
    )
    parser.add_argument("--composer", required=True)
    parser.add_argument("--blueprint", required=True)
    parser.add_argument("--values", required=True)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    staged_workspace: Path | None = None
    try:
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

        staged_workspace = workspace.with_name(f".{workspace.name}.control-refresh")
        if staged_workspace.exists():
            raise RefreshError(f"stale staged workspace exists: {staged_workspace}")

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
        )
    except (RefreshError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        if staged_workspace is not None and staged_workspace.exists():
            shutil.rmtree(staged_workspace)

    print("Refreshed workspace controls:")
    for relative in refreshed:
        print(f"  {relative}")
    print("Preserved environment YAML, lockfiles, caches, views, and installs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
