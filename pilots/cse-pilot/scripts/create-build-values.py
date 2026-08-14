#!/usr/bin/env python3
"""Create the CSE trial build-values file from reviewed shell selections.

This is intentionally a pilot adapter. Stack Composer still receives one
explicit YAML file and never reads the operator's environment itself.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml


class InputError(ValueError):
    pass


PORTABLE_CPU_TARGETS = ("x86_64_v3", "x86_64_v2", "x86_64")
GENERIC_BINARY_TARGETS = {
    "x86_64_v3": "x86_64",
    "x86_64_v2": "x86_64",
    "x86_64": "x86_64",
}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise InputError(f"required environment variable {name} is not set")
    return value


def parse_ref(value: str, label: str) -> tuple[str, str]:
    if "@" not in value:
        raise InputError(f"{label} must use name@version syntax; got {value!r}")
    name, version = value.split("@", 1)
    if not name or not version:
        raise InputError(f"{label} must use name@version syntax; got {value!r}")
    return name, version


def version_key(value: str) -> tuple[tuple[int, Any], ...]:
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.lower())
        for token in re.findall(r"[0-9]+|[A-Za-z]+", value)
    )


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError(f"expected a YAML mapping in {path}")
    return data


def modules_by_scope(plan: dict[str, Any]) -> dict[str, list[str]]:
    records = []
    for key in ("compiler_scopes", "mpi_scopes", "gpu_scopes"):
        records.extend(plan.get(key) or [])
    return {
        str(item["path"]): [str(module) for module in item.get("modules") or []]
        for item in records
        if isinstance(item, dict) and item.get("path")
    }


def one_scope(
    scopes: list[dict[str, Any]],
    *,
    kind: str,
    name: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    matches = [
        scope
        for scope in scopes
        if scope.get("kind") == kind
        and (name is None or scope.get("name") == name)
        and (version is None or str(scope.get("version")) == version)
    ]
    if len(matches) != 1:
        detail = f"kind={kind!r}, name={name!r}, version={version!r}"
        raise InputError(
            f"catalog must contain exactly one scope for {detail}; found {len(matches)}"
        )
    return matches[0]


def shared_compiler_seed_scope(
    scopes: list[dict[str, Any]], *, target_name: str, target_version: str
) -> dict[str, Any]:
    requested = os.environ.get("CSE_SHARED_COMPILER_SEED_REF", "").strip()
    if requested:
        seed_name, seed_version = parse_ref(requested, "CSE_SHARED_COMPILER_SEED_REF")
        return one_scope(scopes, kind="compiler", name=seed_name, version=seed_version)

    target_key = version_key(target_version)
    candidates = [
        scope
        for scope in scopes
        if scope.get("kind") == "compiler"
        and str(scope.get("package") or scope.get("name")) == target_name
        and version_key(str(scope.get("version"))) < target_key
    ]
    if not candidates:
        raise InputError(
            f"catalog has no verified {target_name} compiler older than {target_version} "
            "to build the CSE compiler; set CSE_SHARED_COMPILER_SEED_REF to an "
            "explicit reviewed compiler from the catalog"
        )
    return max(candidates, key=lambda scope: version_key(str(scope.get("version"))))


def mpi_scope(
    scopes: list[dict[str, Any]], *, name: str, version: str, compiler_ref: str
) -> dict[str, Any]:
    compiler_name, compiler_version = parse_ref(compiler_ref, "compiler reference")
    candidates = []
    for scope in scopes:
        if scope.get("kind") != "mpi" or scope.get("name") != name:
            continue
        if str(scope.get("version")) != version or not scope.get("compiler_ref"):
            continue
        scope_name, scope_version = parse_ref(
            str(scope["compiler_ref"]), "catalog compiler_ref"
        )
        if scope_name != compiler_name:
            continue
        if name == "cray-mpich":
            if version_key(scope_version) <= version_key(compiler_version):
                candidates.append(scope)
        elif scope_version == compiler_version:
            candidates.append(scope)
    if not candidates:
        raise InputError(
            f"catalog has no {name}@{version} scope compatible with {compiler_ref}; "
            "fix or regenerate the static catalog instead of inventing a path"
        )
    return max(
        candidates,
        key=lambda scope: version_key(
            parse_ref(str(scope["compiler_ref"]), "compiler_ref")[1]
        ),
    )


def existing_scope(catalog: Path, scope: dict[str, Any]) -> str:
    relative = str(scope["path"])
    if not (catalog / relative).is_dir():
        raise InputError(f"catalog scope directory is missing: {catalog / relative}")
    return relative


def safe_path_segment(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value) or value in {".", ".."}:
        raise InputError(
            f"{label} must contain only letters, numbers, '.', '_', or '-'; got {value!r}"
        )
    return value


def namespaced_stage_path(path: str, *, system_name: str, release: str) -> str:
    base = path.rstrip("/")
    components = {component for component in base.split("/") if component}
    username = os.environ.get("USER", "").strip()
    if "$user" not in components and (not username or username not in components):
        base = f"{base}/$user"
    if base.rsplit("/", 1)[-1] != "spack-stage":
        base = f"{base}/spack-stage"
    return f"{base}/{system_name}/{release}"


def is_temporary_stage(path: str, record: dict[str, Any]) -> bool:
    return (
        "$tempdir" in path
        or path == "/tmp"
        or path.startswith("/tmp/")
        or path == "/var/tmp"
        or path.startswith("/var/tmp/")
        or record.get("visibility") == "node-local"
    )


def build_stage_paths(
    manifest: dict[str, Any], *, system_name: str, release: str
) -> tuple[str, list[str]]:
    node_type_name = required("CSE_BUILD_NODE_TYPE")
    node_types = (manifest.get("profile_facts") or {}).get("node_types") or {}
    if not isinstance(node_types, dict) or node_type_name not in node_types:
        available = ", ".join(sorted(str(name) for name in node_types)) or "none"
        raise InputError(
            f"catalog has no node type {node_type_name!r}; available node types: {available}"
        )
    node_type = node_types[node_type_name]
    if not isinstance(node_type, dict):
        raise InputError(f"catalog node type {node_type_name!r} is not a mapping")

    temporary: list[str] = []
    scratch: list[str] = []
    for record in node_type.get("build_stage") or []:
        if not isinstance(record, dict) or record.get("writable") is not True:
            continue
        mount_opts = {str(option).lower() for option in record.get("mount_opts") or []}
        if "noexec" in mount_opts or record.get("free_gb") == 0:
            continue
        if record.get("free_inodes") == 0:
            continue
        path = str(record.get("path") or "").strip()
        if not path:
            continue
        rendered = namespaced_stage_path(
            path,
            system_name=safe_path_segment(system_name, "SYSTEM_NAME"),
            release=safe_path_segment(release, "TRIAL_RELEASE"),
        )
        destination = temporary if is_temporary_stage(path, record) else scratch
        destination.append(rendered)
    if not temporary and not scratch:
        raise InputError(
            f"catalog node type {node_type_name!r} has no writable executable build-stage "
            "candidate; re-probe the intended build node or choose another reviewed node type"
        )

    workdir = Path(required("WORKDIR")).expanduser()
    if not workdir.is_absolute():
        raise InputError(f"WORKDIR must be absolute; got {str(workdir)!r}")
    if not workdir.is_dir():
        raise InputError(f"WORKDIR does not exist or is not a directory: {workdir}")
    if not os.access(workdir, os.W_OK | os.X_OK):
        raise InputError(f"WORKDIR is not writable and searchable: {workdir}")
    work_fallback = f"${{WORKDIR}}/cse-spack-stage/{system_name}/{release}"

    ordered: list[str] = []
    for path in [*temporary, *scratch, work_fallback]:
        if path not in ordered:
            ordered.append(path)
    return node_type_name, ordered


def portable_cpu_target(manifest: dict[str, Any]) -> tuple[str, list[str]]:
    """Select one portable CPU target for every environment on the system."""
    node_types = (manifest.get("profile_facts") or {}).get("node_types") or {}
    if not isinstance(node_types, dict):
        raise InputError("catalog manifest profile_facts.node_types is not a mapping")

    supported_by_node: dict[str, set[str]] = {}
    for name, node_type in node_types.items():
        if not isinstance(node_type, dict) or node_type.get("gpu") is not None:
            continue
        if node_type.get("role") not in {"build_host", "runtime", "both"}:
            continue
        cpu = node_type.get("cpu") or {}
        supported = {
            str(target)
            for target in (
                cpu.get("detected"),
                cpu.get("preferred"),
                *(cpu.get("alternates") or []),
            )
            if target
        }
        if supported:
            supported_by_node[str(name)] = supported

    if not supported_by_node:
        raise InputError(
            "catalog has no CPU-only build/runtime node architecture facts; "
            "re-probe the system before initializing the workspace"
        )

    common = set.intersection(*supported_by_node.values())
    requested = os.environ.get("CSE_CPU_TARGET", "").strip()
    if requested:
        if requested not in PORTABLE_CPU_TARGETS:
            allowed = ", ".join(PORTABLE_CPU_TARGETS)
            raise InputError(
                f"CSE_CPU_TARGET must be one portable trial target ({allowed}); "
                f"got {requested!r}"
            )
        missing = sorted(
            name
            for name, supported in supported_by_node.items()
            if requested not in supported
        )
        if missing:
            raise InputError(
                f"CSE_CPU_TARGET={requested} is not supported by CPU-only node type(s): "
                f"{', '.join(missing)}"
            )
        return requested, sorted(supported_by_node)

    for target in PORTABLE_CPU_TARGETS:
        if target in common:
            return target, sorted(supported_by_node)
    details = "; ".join(
        f"{name}={','.join(sorted(targets))}"
        for name, targets in sorted(supported_by_node.items())
    )
    raise InputError(
        "CPU-only node types have no common portable x86_64 trial target; "
        f"review the profile or set a supported CSE_CPU_TARGET ({details})"
    )


def scope_external_specs(catalog: Path, relative: str) -> dict[str, list[str]]:
    data = load_mapping(catalog / relative / "packages.yaml")
    packages = data.get("packages") or {}
    if not isinstance(packages, dict):
        raise InputError(
            f"expected packages mapping in {catalog / relative / 'packages.yaml'}"
        )
    result: dict[str, list[str]] = {}
    for name, package in packages.items():
        if not isinstance(package, dict):
            continue
        result[str(name)] = [
            str(external["spec"])
            for external in package.get("externals") or []
            if isinstance(external, dict) and external.get("spec")
        ]
    return result


def openmpi_build_spec(name: str, version: str, externals: dict[str, list[str]]) -> str:
    if name != "openmpi":
        return f"{name}@{version}"

    fabrics = os.environ.get("CSE_OPENMPI_FABRICS", "").strip()
    if not fabrics:
        compatible_ucx = any(
            "+thread_multiple" in spec.split() for spec in externals.get("ucx", [])
        )
        if compatible_ucx:
            fabrics = "ucx"
        elif externals.get("libfabric"):
            fabrics = "ofi"
        else:
            raise InputError(
                "build-sourced OpenMPI needs either verified ucx+thread_multiple or "
                "a verified libfabric external in the static common scope"
            )
    if fabrics == "auto":
        raise InputError(
            "CSE_OPENMPI_FABRICS=auto is not reproducible; select explicit fabrics"
        )
    for fabric in fabrics.split(","):
        package = {"ofi": "libfabric", "ucx": "ucx"}.get(fabric, fabric)
        if package not in externals:
            raise InputError(
                f"OpenMPI fabric {fabric!r} has no verified development external in "
                "the static common scope"
            )
        if fabric == "ucx" and not any(
            "+thread_multiple" in spec.split() for spec in externals.get("ucx", [])
        ):
            raise InputError(
                "OpenMPI 4.1.8 requires ucx+thread_multiple, but the static common "
                "scope has no UCX external with that verified capability"
            )

    scheduler = os.environ.get("CSE_OPENMPI_SCHEDULER", "").strip()
    if not scheduler:
        scheduler_externals = sorted(
            {name for name in ("slurm", "pbs") if name in externals}
        )
        if len(scheduler_externals) != 1:
            raise InputError(
                "build-sourced OpenMPI needs exactly one verified slurm or pbs external; "
                "set CSE_OPENMPI_SCHEDULER only to resolve a reviewed ambiguity"
            )
        scheduler = scheduler_externals[0]
    scheduler_variant = {"slurm": "slurm", "pbs": "tm"}.get(scheduler)
    if not scheduler_variant:
        raise InputError("CSE_OPENMPI_SCHEDULER must be slurm or pbs")
    if scheduler not in externals:
        raise InputError(
            f"OpenMPI scheduler {scheduler!r} has no verified development external in "
            "the static common scope"
        )

    variants = [f"fabrics={fabrics}", f"schedulers={scheduler_variant}", "~rsh"]
    if "lustre" in externals:
        variants.extend(["+lustre", "+romio", "romio-filesystem=lustre"])
    else:
        variants.extend(["~lustre", "+romio", "romio-filesystem=none"])
    if os.environ.get("CSE_OPENMPI_PMI", "disabled").strip() == "enabled":
        if scheduler != "slurm":
            raise InputError(
                "CSE_OPENMPI_PMI=enabled is valid only with the Slurm selection"
            )
        variants.append("+pmi")
    else:
        variants.append("~pmi")
    return " ".join((f"openmpi@{version}", *variants))


def mpi_values(
    *,
    surface: str,
    source: str,
    provider_ref: str,
    compiler_ref: str,
    scopes: list[dict[str, Any]],
    module_map: dict[str, list[str]],
    catalog: Path,
    common_externals: dict[str, list[str]],
) -> tuple[dict[str, Any], str | None]:
    if source not in {"build", "external"}:
        raise InputError(
            f"{surface} MPI source must be build or external; got {source!r}"
        )
    provider_name, provider_version = parse_ref(provider_ref, f"{surface} MPI")
    compiler_name, compiler_version = parse_ref(compiler_ref, f"{surface} compiler")
    package_name = provider_name
    modules: list[str] = []
    scope_path = None
    if source == "external":
        scope = mpi_scope(
            scopes,
            name=provider_name,
            version=provider_version,
            compiler_ref=compiler_ref,
        )
        package_name = str(scope.get("package") or provider_name)
        scope_path = existing_scope(catalog, scope)
        modules = module_map.get(scope_path, [])
    spec = (
        openmpi_build_spec(package_name, provider_version, common_externals)
        if source == "build"
        else f"{package_name}@{provider_version}"
    )
    return (
        {
            "name": package_name,
            "version": provider_version,
            "source": source,
            "modules": modules,
            "spec": spec,
        },
        scope_path,
    )


def main() -> int:
    try:
        catalog = Path(required("CATALOG")).resolve()
        output = Path(required("BUILD_VALUES")).resolve()
        manifest = load_mapping(catalog / "manifest.yaml")
        plan = load_mapping(catalog / "reports" / "static-plan.yaml")
        scopes = [
            item for item in manifest.get("scopes") or [] if isinstance(item, dict)
        ]
        module_map = modules_by_scope(plan)

        system_name = required("SYSTEM_NAME")
        catalog_system = str((manifest.get("system") or {}).get("name") or "")
        if catalog_system != system_name:
            raise InputError(
                f"catalog system {catalog_system!r} does not match SYSTEM_NAME {system_name!r}"
            )

        shared_compiler_ref = os.environ.get("CSE_SHARED_COMPILER_REF", "gcc@12.5.0")
        shared_compiler_name, shared_compiler_version = parse_ref(
            shared_compiler_ref, "CSE_SHARED_COMPILER_REF"
        )
        shared_seed_scope = shared_compiler_seed_scope(
            scopes,
            target_name=shared_compiler_name,
            target_version=shared_compiler_version,
        )
        shared_seed_scope_path = existing_scope(catalog, shared_seed_scope)
        shared_seed_name = str(
            shared_seed_scope.get("package") or shared_seed_scope.get("name")
        )
        shared_seed_version = str(shared_seed_scope["version"])
        platform_provider, platform_version = parse_ref(
            required("CSE_PLATFORM_COMPILER_REF"), "CSE_PLATFORM_COMPILER_REF"
        )
        platform_scope = one_scope(
            scopes, kind="compiler", name=platform_provider, version=platform_version
        )
        platform_scope_path = existing_scope(catalog, platform_scope)
        platform_package = str(platform_scope.get("package") or platform_provider)

        common_scope = one_scope(scopes, kind="common")
        common_scope_path = existing_scope(catalog, common_scope)
        common_externals = scope_external_specs(catalog, common_scope_path)

        shared_mpi, shared_mpi_scope = mpi_values(
            surface="cse",
            source=required("CSE_SHARED_MPI_SOURCE"),
            provider_ref=required("CSE_SHARED_MPI_REF"),
            compiler_ref=shared_compiler_ref,
            scopes=scopes,
            module_map=module_map,
            catalog=catalog,
            common_externals=common_externals,
        )
        platform_compiler_ref = f"{platform_provider}@{platform_version}"
        platform_mpi, platform_mpi_scope = mpi_values(
            surface="platform",
            source=required("CSE_PLATFORM_MPI_SOURCE"),
            provider_ref=required("CSE_PLATFORM_MPI_REF"),
            compiler_ref=platform_compiler_ref,
            scopes=scopes,
            module_map=module_map,
            catalog=catalog,
            common_externals=common_externals,
        )
        platform_scopes = [scope for scope in scopes if scope.get("kind") == "platform"]
        platform_common_path = (
            existing_scope(catalog, platform_scopes[0])
            if len(platform_scopes) == 1
            else None
        )
        if len(platform_scopes) > 1:
            raise InputError("catalog contains more than one platform scope")

        release = required("TRIAL_RELEASE")
        build_node_type, build_stages = build_stage_paths(
            manifest, system_name=system_name, release=release
        )
        cpu_target, target_node_types = portable_cpu_target(manifest)
        generic_binary_target = GENERIC_BINARY_TARGETS[cpu_target]
        release_root = required("BUILD_RELEASE_ROOT").rstrip("/")
        restricted_root = required("CSE_RESTRICTED_ROOT").rstrip("/")
        values = {
            "schema_version": 1,
            "workspace": {"role": "build"},
            "system": {"name": system_name},
            "release": release,
            "stack": {"name": "cse-initial-conversion-trials"},
            "build": {"node_type": build_node_type},
            "architecture": {
                "target": cpu_target,
                "binary_target": generic_binary_target,
                "node_types": target_node_types,
            },
            "shared": {
                "compiler": {
                    "name": shared_compiler_name,
                    "version": shared_compiler_version,
                    "public_name": os.environ.get(
                        "CSE_SHARED_COMPILER_PUBLIC_NAME", "GCC"
                    ),
                    "source": "build",
                    "modules": [],
                    "build_with": {
                        "name": shared_seed_name,
                        "version": shared_seed_version,
                    },
                },
                "mpi": shared_mpi,
                "catalog_scopes": {
                    "compiler": shared_seed_scope_path,
                    "mpi": shared_mpi_scope,
                },
            },
            "platform": {
                "compiler": {
                    "name": platform_package,
                    "version": platform_version,
                    "public_name": required("CSE_PLATFORM_COMPILER_PUBLIC_NAME"),
                    "source": "external",
                    "modules": module_map.get(platform_scope_path, []),
                },
                "mpi": platform_mpi,
                "catalog_scopes": {
                    "compiler": platform_scope_path,
                    "mpi": platform_mpi_scope,
                },
            },
            "catalog_scopes": {
                "common": common_scope_path,
                "platform": platform_common_path,
            },
            "paths": {
                "install_tree": f"{release_root}/spack/opt",
                "build_stage": build_stages,
                "source_cache": f"{restricted_root}/cache/source",
                "misc_cache": f"{restricted_root}/cache/misc",
                "views_root": f"{release_root}/views",
                "modules_root": f"{release_root}/modules",
            },
            "buildcache": {
                "name": "cse-initial-conversion-trials",
                "url": required("BUILDCACHE_URL"),
            },
            "permissions": {
                "group": os.environ.get("CSE_GROUP", "cse"),
                "read": "group",
                "write": "user",
            },
            "build_jobs": int(required("BUILD_JOBS")),
            "package_repo": {
                "git": "https://github.com/spack/spack-packages.git",
                "tag": "v2026.06.0",
            },
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
        print(output)
        print(f"build node type: {build_node_type}")
        print(f"CPU target: {cpu_target} (common to {', '.join(target_node_types)})")
        for stage in build_stages:
            print(f"build stage: {stage}")
        print(
            f"shared surface: {shared_compiler_ref} + {required('CSE_SHARED_MPI_REF')}"
        )
        print(
            f"platform surface: {platform_compiler_ref} + {required('CSE_PLATFORM_MPI_REF')}"
        )
        return 0
    except (InputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
