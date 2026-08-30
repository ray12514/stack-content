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
OPENMPI_POLICY_PATH = Path(__file__).resolve().parents[1] / "openmpi-policy.yaml"
MPI_CONSUMER_PREPEND_PATH_VARIABLES = {"LD_LIBRARY_PATH", "LIBRARY_PATH"}
COMPILER_ACTIVATION_COMMANDS = {
    "aocc": {"c": "clang", "cxx": "clang++", "fortran": "flang"},
    "cce": {"c": "craycc", "cxx": "crayCC", "fortran": "crayftn"},
    "gcc": {"c": "gcc", "cxx": "g++", "fortran": "gfortran"},
    "intel": {"c": "icc", "cxx": "icpc", "fortran": "ifort"},
    "intel-oneapi-compilers": {"c": "icx", "cxx": "icpx", "fortran": "ifx"},
    "intel-oneapi-compilers-classic": {
        "c": "icc",
        "cxx": "icpc",
        "fortran": "ifort",
    },
    "llvm": {"c": "clang", "cxx": "clang++", "fortran": "flang"},
    "nvhpc": {"c": "nvc", "cxx": "nvc++", "fortran": "nvfortran"},
    "oneapi": {"c": "icx", "cxx": "icpx", "fortran": "ifx"},
    "rocmcc": {"c": "amdclang", "cxx": "amdclang++", "fortran": "amdflang"},
}
MPI_ACTIVATION_COMMANDS = {
    "cray-mpich": {"c": "cc", "cxx": "CC", "fortran": "ftn"},
    "intel-mpi": {"c": "mpiicc", "cxx": "mpiicpc", "fortran": "mpiifort"},
    "intel-oneapi-mpi": {"c": "mpiicx", "cxx": "mpiicpx", "fortran": "mpiifx"},
    "mpich": {"c": "mpicc", "cxx": "mpicxx", "fortran": "mpifort"},
    "mvapich2": {"c": "mpicc", "cxx": "mpicxx", "fortran": "mpifort"},
    "openmpi": {"c": "mpicc", "cxx": "mpicxx", "fortran": "mpifort"},
}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise InputError(f"required environment variable {name} is not set")
    return value


def required_absolute_path(name: str) -> Path:
    path = Path(required(name)).expanduser()
    if not path.is_absolute():
        raise InputError(f"{name} must be an absolute path; got {str(path)!r}")
    return path


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


def platform_runtime_compiler_scope(
    provider_name: str, shared_seed_scope_path: str
) -> str | None:
    """Return a compiler scope needed only to satisfy a platform runtime DAG."""
    if provider_name == "oneapi":
        return shared_seed_scope_path
    return None


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


def public_compiler_module_names() -> tuple[str, str]:
    shared = safe_path_segment(
        os.environ.get("CSE_SHARED_COMPILER_PUBLIC_NAME", "GCC"),
        "CSE_SHARED_COMPILER_PUBLIC_NAME",
    )
    platform = safe_path_segment(
        required("CSE_PLATFORM_COMPILER_PUBLIC_NAME"),
        "CSE_PLATFORM_COMPILER_PUBLIC_NAME",
    )
    if shared == platform:
        raise InputError(
            "CSE shared and platform compiler public names must be distinct; "
            f"both resolve to cse/{shared}"
        )
    return shared, platform


def compiler_activation_commands(name: str, modules: list[str]) -> dict[str, str]:
    if any(module.split("/", 1)[0].startswith("PrgEnv-") for module in modules):
        return {"c": "cc", "cxx": "CC", "fortran": "ftn"}
    commands = COMPILER_ACTIVATION_COMMANDS.get(name)
    if commands is None:
        raise InputError(
            f"no CSE compiler activation command policy exists for {name!r}"
        )
    return dict(commands)


def mpi_activation_commands(name: str) -> dict[str, str]:
    commands = MPI_ACTIVATION_COMMANDS.get(name)
    if commands is None:
        raise InputError(f"no CSE MPI activation command policy exists for {name!r}")
    return dict(commands)


def namespaced_stage_path(
    path: str, *, system_name: str, release: str, context: str
) -> str:
    base = path.rstrip("/")
    components = {component for component in base.split("/") if component}
    username = os.environ.get("USER", "").strip()
    user_tokens = {"$USER", "${USER}"}
    if not components.intersection(user_tokens) and (
        not username or username not in components
    ):
        base = f"{base}/${{USER}}"
    if base.rsplit("/", 1)[-1] != "spack-stage":
        base = f"{base}/spack-stage"
    return f"{base}/{system_name}/{release}/{context}"


def is_temporary_stage(path: str, record: dict[str, Any]) -> bool:
    return (
        "$tempdir" in path
        or path == "/tmp"
        or path.startswith("/tmp/")
        or path == "/var/tmp"
        or path.startswith("/var/tmp/")
        or record.get("visibility") == "node-local"
    )


def stage_paths_for_node(
    manifest: dict[str, Any],
    *,
    node_type_name: str,
    system_name: str,
    release: str,
    context: str,
) -> list[str]:
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
            context=safe_path_segment(context, "build context"),
        )
        destination = temporary if is_temporary_stage(path, record) else scratch
        destination.append(rendered)
    workdir = Path(required("WORKDIR")).expanduser()
    if not workdir.is_absolute():
        raise InputError(f"WORKDIR must be absolute; got {str(workdir)!r}")
    if not workdir.is_dir():
        raise InputError(f"WORKDIR does not exist or is not a directory: {workdir}")
    if not os.access(workdir, os.W_OK | os.X_OK):
        raise InputError(f"WORKDIR is not writable and searchable: {workdir}")
    work_fallback = (
        f"${{WORKDIR}}/cse-spack-stage/{system_name}/{release}/{context}"
    )

    ordered: list[str] = []
    for path in [*temporary, *scratch, work_fallback]:
        if path not in ordered:
            ordered.append(path)
    return ordered


def build_contexts(
    manifest: dict[str, Any], *, system_name: str, release: str
) -> dict[str, dict[str, Any]]:
    node_types = (manifest.get("profile_facts") or {}).get("node_types") or {}
    if not isinstance(node_types, dict):
        raise InputError("catalog profile_facts.node_types must be a mapping")

    contexts: dict[str, dict[str, Any]] = {}
    for context, variable in (
        ("login", "CSE_LOGIN_NODE_TYPE"),
        ("compute", "CSE_COMPUTE_NODE_TYPE"),
    ):
        node_type_name = required(variable)
        if node_type_name not in node_types:
            available = ", ".join(sorted(str(name) for name in node_types)) or "none"
            raise InputError(
                f"catalog has no {context} node type {node_type_name!r}; "
                f"available node types: {available}; set {variable} to the "
                f"reviewed {context} node key"
            )
        contexts[context] = {
            "node_type": node_type_name,
            "stages": stage_paths_for_node(
                manifest,
                node_type_name=node_type_name,
                system_name=system_name,
                release=release,
                context=context,
            ),
        }
    return contexts


def portable_cpu_target(manifest: dict[str, Any]) -> tuple[str, list[str]]:
    """Select one portable CPU target for every environment on the system."""
    node_types = (manifest.get("profile_facts") or {}).get("node_types") or {}
    if not isinstance(node_types, dict):
        raise InputError("catalog manifest profile_facts.node_types is not a mapping")

    supported_by_node: dict[str, set[str]] = {}
    for name, node_type in node_types.items():
        if not isinstance(node_type, dict):
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
            "catalog has no build/runtime node CPU architecture facts; "
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
                f"CSE_CPU_TARGET={requested} is not supported by build/runtime "
                "node type(s): "
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
        "build/runtime node types have no common portable x86_64 trial target; "
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


def external_mpi_consumer(
    *,
    catalog: Path,
    scope_path: str,
    package_name: str,
    version: str,
) -> dict[str, Any] | None:
    """Normalize consumer-only facts for an external MPI implementation.

    These values describe a module-facing candidate interface. They are kept
    separate from ``spec`` and ``provider_constraint`` so adding them cannot
    change any Spack root or concrete DAG.
    """
    if package_name != "cray-mpich":
        return None

    path = catalog / scope_path / "packages.yaml"
    data = load_mapping(path)
    packages = data.get("packages") or {}
    if not isinstance(packages, dict):
        raise InputError(f"expected packages mapping in {path}")
    package = packages.get(package_name)
    if not isinstance(package, dict):
        raise InputError(f"{path} has no {package_name} package mapping")

    variants = package.get("variants") or ""
    variant_tokens = (
        {str(token) for token in variants}
        if isinstance(variants, list)
        else set(str(variants).split())
    )
    if "+wrappers" not in variant_tokens:
        raise InputError(
            f"{path} must enable +wrappers before {package_name} can expose a "
            "candidate consumer interface"
        )

    pattern = re.compile(
        rf"^{re.escape(package_name)}@{re.escape(version)}(?:[+~%\s]|$)"
    )
    candidates = [
        external
        for external in package.get("externals") or []
        if isinstance(external, dict)
        and pattern.match(str(external.get("spec") or ""))
    ]
    if len(candidates) != 1:
        raise InputError(
            f"{path} must contain exactly one {package_name}@{version} external; "
            f"found {len(candidates)}"
        )
    external = candidates[0]

    prefix_value = str(external.get("prefix") or "").rstrip("/")
    prefix = Path(prefix_value)
    if not prefix_value or not prefix.is_absolute():
        raise InputError(
            f"{package_name}@{version} consumer prefix must be absolute in {path}"
        )

    extra_attributes = external.get("extra_attributes") or {}
    if not isinstance(extra_attributes, dict):
        raise InputError(
            f"{package_name}@{version} extra_attributes must be a mapping in {path}"
        )
    unknown_extra = sorted(set(extra_attributes) - {"environment"})
    if unknown_extra:
        raise InputError(
            f"unsupported {package_name}@{version} consumer extra_attributes in "
            f"{path}: {', '.join(unknown_extra)}"
        )
    environment = extra_attributes.get("environment") or {}
    if not isinstance(environment, dict):
        raise InputError(
            f"{package_name}@{version} consumer environment must be a mapping in {path}"
        )
    unknown_operations = sorted(set(environment) - {"prepend_path"})
    if unknown_operations:
        raise InputError(
            f"unsupported {package_name}@{version} consumer environment operation(s) "
            f"in {path}: {', '.join(unknown_operations)}"
        )
    prepend_path = environment.get("prepend_path") or {}
    if not isinstance(prepend_path, dict):
        raise InputError(
            f"{package_name}@{version} prepend_path must be a mapping in {path}"
        )
    normalized_prepend: dict[str, list[str]] = {}
    for variable, raw_paths in prepend_path.items():
        variable_name = str(variable)
        if variable_name not in MPI_CONSUMER_PREPEND_PATH_VARIABLES:
            allowed = ", ".join(sorted(MPI_CONSUMER_PREPEND_PATH_VARIABLES))
            raise InputError(
                f"unsupported {package_name}@{version} consumer path variable "
                f"{variable_name!r} in {path}; allowed: {allowed}"
            )
        paths = raw_paths if isinstance(raw_paths, list) else [raw_paths]
        normalized: list[str] = []
        for raw_path in paths:
            value = str(raw_path or "").rstrip("/")
            if not value or not Path(value).is_absolute():
                raise InputError(
                    f"{package_name}@{version} {variable_name} entry must be "
                    f"absolute in {path}: {value!r}"
                )
            if value not in normalized:
                normalized.append(value)
        normalized_prepend[variable_name] = normalized

    return {
        "status": "multi-node-validation-required",
        "interface": "vendor-wrapper",
        "wrapper_provider": "cray-mpich-simple-wrapper",
        "prefix": prefix_value,
        "wrappers": {
            "c": f"{prefix_value}/bin/mpicc",
            "cxx": f"{prefix_value}/bin/mpicxx",
            "fortran": f"{prefix_value}/bin/mpifort",
            "fortran90": f"{prefix_value}/bin/mpif90",
            "fortran77": f"{prefix_value}/bin/mpif77",
        },
        "runtime_environment": {"prepend_path": normalized_prepend},
    }


def selected_external_spec(
    name: str,
    specs: list[str],
    *,
    required_variant: str | None = None,
) -> str:
    candidates = [
        spec
        for spec in specs
        if required_variant is None or required_variant in spec.split()
    ]
    if not candidates:
        requirement = f" with {required_variant}" if required_variant else ""
        raise InputError(
            f"no verified {name} external{requirement} exists in the static common scope"
        )

    def external_version(spec: str) -> tuple[tuple[int, Any], ...]:
        match = re.match(rf"^{re.escape(name)}@([^+~%\s]+)", spec)
        if not match:
            raise InputError(f"cannot read {name} version from external spec {spec!r}")
        return version_key(match.group(1))

    selected = max(candidates, key=external_version)
    return "".join(selected.split())


def selected_profile_external(
    manifest: dict[str, Any], name: str, selected_spec: str
) -> dict[str, Any]:
    match = re.match(rf"^{re.escape(name)}@([^+~%\s]+)", selected_spec)
    if not match:
        raise InputError(
            f"cannot match selected {name} spec {selected_spec!r} to profile facts"
        )
    version = match.group(1)
    facts = (manifest.get("profile_facts") or {}).get("system_externals") or []
    candidates = [
        fact
        for fact in facts
        if isinstance(fact, dict)
        and fact.get("name") == name
        and str(fact.get("version")) == version
    ]
    if len(candidates) != 1:
        raise InputError(
            f"static manifest must contain exactly one {name}@{version} profile fact; "
            f"found {len(candidates)}"
        )
    return candidates[0]


def openmpi_launch_policy(policy: dict[str, Any]) -> list[str]:
    launch = policy.get("launch")
    if not isinstance(launch, dict) or launch.get("mpirun") != "required":
        raise InputError("the CSE OpenMPI policy must retain mpirun")
    direct = launch.get("slurm_direct")
    if not isinstance(direct, dict) or direct.get("support") != "when_verified":
        raise InputError(
            "the CSE OpenMPI policy must enable Slurm direct launch when verified"
        )
    priority = direct.get("interface_priority")
    if priority != ["pmi2"]:
        raise InputError(
            "the current OpenMPI 4.1.8 policy must use interface_priority: [pmi2]"
        )
    return priority


def slurm_direct_launch_interface(
    priority: list[str], manifest: dict[str, Any], slurm_spec: str
) -> str | None:
    slurm = selected_profile_external(manifest, "slurm", slurm_spec)
    mpi_launch = ((slurm.get("capabilities") or {}).get("mpi_launch") or {})
    if mpi_launch.get("command") != "srun":
        raise InputError(
            "selected Slurm external has no Cluster Inspector verified srun capability; "
            "re-probe the system and re-render the static catalog"
        )
    plugins = {str(plugin) for plugin in mpi_launch.get("plugins") or []}
    development = {
        str(interface)
        for interface in mpi_launch.get("development_interfaces") or []
    }
    for interface in priority:
        if interface in plugins and interface in development:
            return interface
    return None


def openmpi_build_specs(
    name: str,
    version: str,
    externals: dict[str, list[str]],
    manifest: dict[str, Any],
) -> tuple[str, str]:
    if name != "openmpi":
        raise InputError(
            "source-built MPI is supported only for openmpi in the current "
            f"CSE trial policy; select source=external for {name}@{version}"
        )

    policy_data = load_mapping(OPENMPI_POLICY_PATH)
    if policy_data.get("schema_version") != 1:
        raise InputError(f"unsupported OpenMPI policy in {OPENMPI_POLICY_PATH}")
    policy = policy_data.get("openmpi")
    if not isinstance(policy, dict):
        raise InputError(f"missing openmpi mapping in {OPENMPI_POLICY_PATH}")
    if str(policy.get("version")) != version:
        raise InputError(
            f"OpenMPI request {version} does not match trial policy version "
            f"{policy.get('version')}"
        )

    fabrics = policy.get("fabrics")
    if fabrics != ["ucx"]:
        raise InputError("the current CSE trial policy must select exactly fabrics: [ucx]")
    ucx_spec = selected_external_spec(
        "ucx", externals.get("ucx", []), required_variant="+thread_multiple"
    )

    if policy.get("scheduler") != "verified_external_or_none":
        raise InputError(
            "the current CSE trial policy requires verified_external_or_none"
        )
    scheduler_externals = sorted(
        {external for external in ("slurm", "pbs") if external in externals}
    )
    if len(scheduler_externals) > 1:
        raise InputError(
            "build-sourced OpenMPI found both verified slurm and pbs externals; "
            "select one scheduler before creating build values"
        )
    scheduler = scheduler_externals[0] if scheduler_externals else None

    expected_policy = {
        "cuda": False,
        "fortran": True,
        "lustre": False,
        "romio": True,
        "romio_filesystems": [],
    }
    for key, expected in expected_policy.items():
        if policy.get(key) != expected:
            raise InputError(
                f"the current CSE trial policy requires openmpi.{key}={expected!r}"
            )
    slurm_interface_priority = openmpi_launch_policy(policy)

    variants = [
        "fabrics=ucx",
        "~cuda",
        "+fortran",
        "~lustre",
        "+romio",
        "romio-filesystem=none",
    ]
    dependencies = [f"^{ucx_spec}"]
    if scheduler == "slurm":
        scheduler_spec = selected_external_spec("slurm", externals["slurm"])
        variants.extend(("schedulers=slurm", "~rsh"))
        slurm_interface = slurm_direct_launch_interface(
            slurm_interface_priority, manifest, scheduler_spec
        )
        variants.append("+legacylaunchers")
        variants.append("+pmi" if slurm_interface == "pmi2" else "~pmi")
        dependencies.append(f"^{scheduler_spec}")
    elif scheduler == "pbs":
        scheduler_spec = selected_external_spec("pbs", externals["pbs"])
        variants.extend(("schedulers=tm", "~rsh"))
        dependencies.append(f"^{scheduler_spec}")
    else:
        variants.extend(("schedulers=none", "+rsh"))
    provider_constraint = " ".join((f"openmpi@{version}", *variants))
    return (
        " ".join((provider_constraint, *dependencies)),
        provider_constraint,
    )


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
    manifest: dict[str, Any],
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
    if source == "build":
        spec, provider_constraint = openmpi_build_specs(
            package_name, provider_version, common_externals, manifest
        )
    else:
        spec = f"{package_name}@{provider_version}"
        provider_constraint = spec
    values = {
        "name": package_name,
        "version": provider_version,
        "source": source,
        "modules": modules,
        "spec": spec,
        "provider_constraint": provider_constraint,
        "commands": mpi_activation_commands(package_name),
    }
    if source == "external":
        consumer = external_mpi_consumer(
            catalog=catalog,
            scope_path=str(scope_path),
            package_name=package_name,
            version=provider_version,
        )
        if consumer is not None:
            values["consumer"] = consumer
    return values, scope_path


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
            manifest=manifest,
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
            manifest=manifest,
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
        contexts = build_contexts(
            manifest, system_name=system_name, release=release
        )
        cpu_target, target_node_types = portable_cpu_target(manifest)
        generic_binary_target = GENERIC_BINARY_TARGETS[cpu_target]
        release_root = required("BUILD_RELEASE_ROOT").rstrip("/")
        restricted_root = required("CSE_RESTRICTED_ROOT").rstrip("/")
        spack_source = required("SPACK_SOURCE")
        spack_version = required("SPACK_VERSION")
        spack_tag = required("SPACK_TAG")
        spack_runtime_mode = required("SPACK_RUNTIME_MODE")
        if spack_runtime_mode not in {"shared", "local"}:
            raise InputError(
                "SPACK_RUNTIME_MODE must be 'shared' or 'local'; "
                f"got {spack_runtime_mode!r}"
            )
        shared_spack_root = (
            required_absolute_path("CSE_TOOLS_ROOT") / "spack" / spack_version
        )
        initial_spack_root = required_absolute_path("SPACK_ROOT")
        shared_public_name, platform_public_name = public_compiler_module_names()
        values = {
            "schema_version": 1,
            "workspace": {"role": "build"},
            "system": {"name": system_name},
            "release": release,
            "stack": {"name": "cse-initial-conversion-trials"},
            "build": {"contexts": contexts},
            "architecture": {
                "target": cpu_target,
                "binary_target": generic_binary_target,
                "node_types": target_node_types,
            },
            "shared": {
                "compiler": {
                    "name": shared_compiler_name,
                    "version": shared_compiler_version,
                    "public_name": shared_public_name,
                    "source": "build",
                    "modules": [],
                    "commands": compiler_activation_commands(
                        shared_compiler_name, []
                    ),
                    "build_with": {
                        "name": shared_seed_name,
                        "version": shared_seed_version,
                        "modules": module_map.get(shared_seed_scope_path, []),
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
                    "public_name": platform_public_name,
                    "source": "external",
                    "modules": module_map.get(platform_scope_path, []),
                    "commands": compiler_activation_commands(
                        platform_provider,
                        module_map.get(platform_scope_path, []),
                    ),
                },
                "mpi": platform_mpi,
                "catalog_scopes": {
                    "compiler": platform_scope_path,
                    "runtime_compiler": platform_runtime_compiler_scope(
                        platform_provider, shared_seed_scope_path
                    ),
                    "mpi": platform_mpi_scope,
                },
            },
            "catalog_scopes": {
                "common": common_scope_path,
                "platform": platform_common_path,
            },
            "paths": {
                "install_tree": f"{release_root}/spack/opt",
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
                "group": required("CSE_GROUP"),
                "read": "group",
                "write": "group",
            },
            "build_jobs": int(required("BUILD_JOBS")),
            "spack": {
                "source": spack_source,
                "version": spack_version,
                "tag": spack_tag,
                "commit": required("SPACK_COMMIT"),
                "default_mode": spack_runtime_mode,
                "shared_root": str(shared_spack_root),
                "initial_root": str(initial_spack_root),
            },
            "package_repo": {
                "git": "https://github.com/spack/spack-packages.git",
                "tag": "v2026.06.0",
            },
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
        print(output)
        for context, context_values in contexts.items():
            print(f"{context} node type: {context_values['node_type']}")
            for stage in context_values["stages"]:
                print(f"{context} build stage candidate: {stage}")
        print(f"CPU target: {cpu_target} (common to {', '.join(target_node_types)})")
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
