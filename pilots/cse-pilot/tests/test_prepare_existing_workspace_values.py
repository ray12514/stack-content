from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


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


def prepare_command(source: Path, output: Path) -> list[str]:
    return [
        sys.executable, str(SCRIPT_PATH), "--source", str(source), "--output", str(output),
        "--spack-source", "https://github.com/spack/spack.git",
        "--spack-version", "1.2.2", "--spack-tag", "v1.2.2",
        "--spack-commit", "3e19345b6e12f5ff1b874f4059622fc6a1fd804a",
        "--spack-mode", "shared", "--shared-spack-root", "/shared/spack",
        "--initial-spack-root", "/shared/spack",
    ]


@pytest.mark.parametrize("alias", ["symlink", "hardlink", "parent", "directory-symlink"])
def test_refuses_aliased_output_without_overwriting_recorded_values(tmp_path, alias):
    source = tmp_path / "recorded.yaml"
    source.write_bytes((SCRIPT_PATH.parents[1] / "site-values.example.yaml").read_bytes())
    before = source.read_bytes()
    output = tmp_path / "render-only.yaml"
    if alias == "symlink":
        output.symlink_to(source)
    elif alias == "hardlink":
        os.link(source, output)
    elif alias == "parent":
        (tmp_path / "nested").mkdir()
        output = tmp_path / "nested/../recorded.yaml"
    else:
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
        output = tmp_path / "alias/recorded.yaml"

    result = subprocess.run(prepare_command(source, output), text=True, capture_output=True)

    assert source.read_bytes() == before
    assert result.returncode == 2
    assert "output already exists" in result.stderr


@pytest.mark.parametrize("existing", ["reviewed-file", "dangling-symlink"])
def test_refuses_existing_output_without_replacing_or_following_it(tmp_path, existing):
    source = tmp_path / "recorded.yaml"
    source.write_bytes((SCRIPT_PATH.parents[1] / "site-values.example.yaml").read_bytes())
    before = source.read_bytes()
    output = tmp_path / "render-only.yaml"
    target = tmp_path / "unexpected-target.yaml"
    reviewed = b"# Already reviewed candidate; retain exact bytes.\nreviewed: true\n"
    if existing == "reviewed-file":
        output.write_bytes(reviewed)
        output.chmod(0o640)
    else:
        output.symlink_to(target)

    result = subprocess.run(prepare_command(source, output), text=True, capture_output=True)

    assert result.returncode == 2
    assert "output already exists" in result.stderr
    assert source.read_bytes() == before
    assert not target.exists()
    if existing == "reviewed-file":
        assert output.read_bytes() == reviewed
        assert output.stat().st_mode & 0o777 == 0o640
    else:
        assert output.is_symlink()
        assert output.readlink() == target


@pytest.mark.parametrize("existing,explicit,success", [
    (None, None, False),
    (None, "d4f7c711a6a42f1c4d551c8fd10fce9a11340a81", True),
    ("0e093dad700a9be836b0d4aefc4bb5183e4990bd", None, True),
    (None, "v2026.06.0", False),
    ("0e093dad700a9be836b0d4aefc4bb5183e4990bd", "d4f7c711a6a42f1c4d551c8fd10fce9a11340a81", False),
])
def test_control_render_values_require_an_explicit_builtin_identity(tmp_path, existing, explicit, success):
    values = yaml.safe_load((SCRIPT_PATH.parents[1] / "site-values.example.yaml").read_text())
    if existing is None:
        values["package_repo"].pop("commit", None)
    else:
        values["package_repo"]["commit"] = existing
    source = tmp_path / "recorded.yaml"
    source.write_text(yaml.safe_dump(values))
    before = source.read_bytes()
    output = tmp_path / "render-only.yaml"
    arguments = [sys.executable, str(SCRIPT_PATH), "--source", str(source), "--output", str(output)]
    for key, value in {
        "spack-source": "https://github.com/spack/spack.git",
        "spack-version": "1.2.2", "spack-tag": "v1.2.2",
        "spack-commit": "3e19345b6e12f5ff1b874f4059622fc6a1fd804a",
        "spack-mode": "shared", "shared-spack-root": "/shared/spack",
        "initial-spack-root": "/shared/spack",
    }.items():
        arguments.extend(["--" + key, value])
    if explicit is not None:
        arguments.extend(["--builtin-commit", explicit])
    result = subprocess.run(arguments, text=True, capture_output=True)
    assert source.read_bytes() == before
    if success:
        assert result.returncode == 0, result.stderr
        assert yaml.safe_load(output.read_text())["package_repo"]["commit"] == (existing or explicit)
    else:
        assert result.returncode == 2
        assert "builtin" in result.stderr
        assert not output.exists()


def test_prepares_historical_values_for_current_control_render() -> None:
    historical = {
        "package_repo": {"commit": "d4f7c711a6a42f1c4d551c8fd10fce9a11340a81"},
        "system": {"name": "blueback"},
        "release": "trial-001",
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
    assert "build_stage" not in prepared["paths"]
    assert prepared["build"] == {
        "contexts": {
            "login": {
                "node_type": "login",
                "stages": [
                    "${WORKDIR}/cse-spack-stage/blueback/trial-001/login"
                ],
            },
            "compute": {
                "node_type": "cpu_compute",
                "stages": [
                    "${WORKDIR}/cse-spack-stage/blueback/trial-001/compute"
                ],
            },
        }
    }
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
        "package_repo": {"commit": "d4f7c711a6a42f1c4d551c8fd10fce9a11340a81"},
        "system": {"name": "raider"},
        "release": "trial-001",
        "architecture": {
            "target": "x86_64_v3",
            "binary_target": "x86_64",
            "node_types": ["login", "cpu_compute"],
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
