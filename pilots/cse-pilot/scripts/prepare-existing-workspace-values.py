#!/usr/bin/env python3
"""Prepare current values from a recorded trial workspace."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml


class InputError(ValueError):
    """Raised when control-refresh inputs are incomplete or invalid."""


GENERIC_BINARY_TARGETS = {
    "x86_64_v3": "x86_64",
    "x86_64_v2": "x86_64",
    "x86_64": "x86_64",
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be a YAML mapping")
    return value


def _provider_constraint(mpi: dict[str, Any], label: str) -> str:
    existing = mpi.get("provider_constraint")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    spec = mpi.get("spec")
    if not isinstance(spec, str) or not spec.strip():
        raise InputError(
            f"{label}.provider_constraint is missing and {label}.spec "
            "cannot be used to derive it"
        )

    constraint = spec.split("^", 1)[0].strip()
    if not constraint:
        raise InputError(f"could not derive {label}.provider_constraint")
    return constraint


def prepare_values(
    values: dict[str, Any],
    *,
    spack_source: str,
    spack_version: str,
    spack_tag: str,
    spack_commit: str,
    spack_mode: str,
    shared_spack_root: str,
    initial_spack_root: str,
) -> dict[str, Any]:
    """Return current control-render values without changing recorded values."""
    prepared = copy.deepcopy(_mapping(values, "values"))

    architecture = _mapping(prepared.get("architecture"), "architecture")
    binary_target = architecture.get("binary_target")
    if not isinstance(binary_target, str) or not binary_target.strip():
        target = architecture.get("target")
        if target not in GENERIC_BINARY_TARGETS:
            raise InputError(
                "architecture.binary_target is missing and cannot be derived "
                f"from architecture.target {target!r}"
            )
        architecture["binary_target"] = GENERIC_BINARY_TARGETS[target]

    paths = _mapping(prepared.get("paths"), "paths")
    build_stages = paths.get("build_stage")
    if not isinstance(build_stages, list) or not build_stages:
        raise InputError("paths.build_stage must be a non-empty YAML list")
    valid_stages = all(
        isinstance(stage, str) and stage.strip() for stage in build_stages
    )
    if not valid_stages:
        raise InputError("every paths.build_stage entry must be a non-empty string")
    paths["build_stage"] = [
        stage.replace("$user/", "${USER}/") for stage in build_stages
    ]

    permissions = _mapping(prepared.get("permissions"), "permissions")
    permissions["read"] = "group"
    permissions["write"] = "group"

    for surface_name in ("shared", "platform"):
        surface = _mapping(prepared.get(surface_name), surface_name)
        mpi = _mapping(surface.get("mpi"), f"{surface_name}.mpi")
        mpi["provider_constraint"] = _provider_constraint(
            mpi, f"{surface_name}.mpi"
        )

    if spack_mode not in {"shared", "local"}:
        raise InputError("spack mode must be 'shared' or 'local'")

    spack_values = {
        "source": spack_source,
        "version": spack_version,
        "tag": spack_tag,
        "commit": spack_commit,
        "default_mode": spack_mode,
        "shared_root": shared_spack_root,
        "initial_root": initial_spack_root,
    }
    for key, value in spack_values.items():
        if not isinstance(value, str) or not value.strip():
            raise InputError(f"spack.{key} must be a non-empty string")
    prepared["spack"] = spack_values
    return prepared


def _absolute_path(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise InputError(f"{label} must be an absolute path: {value}")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a temporary current values copy from recorded trial values."
        )
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--spack-source", required=True)
    parser.add_argument("--spack-version", required=True)
    parser.add_argument("--spack-tag", required=True)
    parser.add_argument("--spack-commit", required=True)
    parser.add_argument("--spack-mode", choices=("shared", "local"), required=True)
    parser.add_argument("--shared-spack-root", required=True)
    parser.add_argument("--initial-spack-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source = _absolute_path(args.source, "source")
        output = _absolute_path(args.output, "output")
        if source == output:
            raise InputError("source and output must be different files")

        values = _mapping(
            yaml.safe_load(source.read_text(encoding="utf-8")), "values"
        )
        prepared = prepare_values(
            values,
            spack_source=args.spack_source,
            spack_version=args.spack_version,
            spack_tag=args.spack_tag,
            spack_commit=args.spack_commit,
            spack_mode=args.spack_mode,
            shared_spack_root=args.shared_spack_root,
            initial_spack_root=args.initial_spack_root,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            yaml.safe_dump(prepared, sort_keys=False), encoding="utf-8"
        )
    except (InputError, OSError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
