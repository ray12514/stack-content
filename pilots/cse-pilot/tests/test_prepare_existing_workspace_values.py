from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "prepare-existing-workspace-values.py"
)
SPEC = importlib.util.spec_from_file_location(
    "prepare_control_refresh_values", SCRIPT_PATH
)
PREPARE_CONTROL_REFRESH_VALUES = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PREPARE_CONTROL_REFRESH_VALUES)


def test_prepares_historical_values_for_current_control_render() -> None:
    historical = {
        "architecture": {
            "target": "x86_64_v3",
            "node_types": ["cpu_compute", "login"],
        },
        "paths": {
            "build_stage": [
                "$tempdir/$user/spack-stage/blueback/trial-001",
                "${WORKDIR}/cse-spack-stage/blueback/trial-001",
            ]
        },
        "permissions": {"group": "cse", "read": "group", "write": "user"},
        "shared": {
            "mpi": {
                "name": "openmpi",
                "spec": "openmpi@4.1.8 fabrics=ucx ^ucx@1.18.0 ^slurm@23.02.7",
            }
        },
        "platform": {
            "mpi": {
                "name": "cray-mpich",
                "spec": "cray-mpich@9.1.0",
            }
        },
    }

    prepared = PREPARE_CONTROL_REFRESH_VALUES.prepare_values(
        historical,
        spack_source="https://github.com/spack/spack.git",
        spack_version="1.2.2",
        spack_tag="v1.2.2",
        spack_commit="3e19345b6e12f5ff1b874f4059622fc6a1fd804a",
        spack_mode="shared",
        shared_spack_root="/p/app/CSE/tools/spack/1.2.2",
        initial_spack_root="/p/app/CSE/tools/spack/1.2.2",
    )

    assert prepared["shared"]["mpi"]["provider_constraint"] == (
        "openmpi@4.1.8 fabrics=ucx"
    )
    assert prepared["platform"]["mpi"]["provider_constraint"] == (
        "cray-mpich@9.1.0"
    )
    assert prepared["architecture"]["binary_target"] == "x86_64"
    assert prepared["paths"]["build_stage"] == [
        "$tempdir/${USER}/spack-stage/blueback/trial-001",
        "${WORKDIR}/cse-spack-stage/blueback/trial-001",
    ]
    assert prepared["permissions"] == {
        "group": "cse",
        "read": "group",
        "write": "group",
    }
    assert prepared["spack"] == {
        "source": "https://github.com/spack/spack.git",
        "version": "1.2.2",
        "tag": "v1.2.2",
        "commit": "3e19345b6e12f5ff1b874f4059622fc6a1fd804a",
        "default_mode": "shared",
        "shared_root": "/p/app/CSE/tools/spack/1.2.2",
        "initial_root": "/p/app/CSE/tools/spack/1.2.2",
    }
    assert "provider_constraint" not in historical["shared"]["mpi"]


def test_preserves_reviewed_provider_constraint() -> None:
    values = {
        "architecture": {
            "target": "x86_64_v3",
            "binary_target": "x86_64",
        },
        "paths": {"build_stage": ["/scratch/${USER}/spack-stage"]},
        "permissions": {"group": "cse", "read": "group", "write": "group"},
        "shared": {
            "mpi": {
                "spec": "openmpi@4.1.8 ^ucx@1.18.0",
                "provider_constraint": "openmpi@4.1.8 fabrics=ucx",
            }
        },
        "platform": {
            "mpi": {
                "spec": "openmpi@4.1.8 ^ucx@1.18.0",
                "provider_constraint": "openmpi@4.1.8 fabrics=ucx",
            }
        },
    }

    prepared = PREPARE_CONTROL_REFRESH_VALUES.prepare_values(
        values,
        spack_source="https://github.com/spack/spack.git",
        spack_version="1.2.2",
        spack_tag="v1.2.2",
        spack_commit="3e19345b6e12f5ff1b874f4059622fc6a1fd804a",
        spack_mode="shared",
        shared_spack_root="/shared/tools/spack/1.2.2",
        initial_spack_root="/shared/tools/spack/1.2.2",
    )

    assert prepared["shared"]["mpi"]["provider_constraint"] == (
        "openmpi@4.1.8 fabrics=ucx"
    )
