from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

import pytest
import yaml

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "refresh-workspace-controls.py"
)
SPEC = importlib.util.spec_from_file_location("refresh_workspace_controls", SCRIPT_PATH)
REFRESH = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(REFRESH)


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def manifest(system: str = "raider") -> dict:
    return {
        "schema_version": 1,
        "kind": "initialized-workspace",
        "blueprint": "cse-initial-conversion-trials",
        "catalog": {"system": system, "release": "catalog-001"},
    }


def test_refreshes_declared_controls_and_preserves_build_inputs(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint.yaml"
    write_yaml(
        blueprint,
        {
            "control_files": [
                "cse-build",
                "configs/common/config.yaml",
                "env/share-generated-permissions.sh",
                "env/setup-build-env.sh",
                "scripts/verify-lockfiles.py",
            ]
        },
    )
    workspace = tmp_path / "workspace"
    staged = tmp_path / "staged"
    for root in (workspace, staged):
        write_yaml(root / "workspace-manifest.yaml", manifest())
        (root / "env").mkdir()
        (root / "configs" / "common").mkdir(parents=True)
        (root / "scripts").mkdir()
    for relative in (
        Path("cse-build"),
        Path("configs/common/config.yaml"),
        Path("env/share-generated-permissions.sh"),
        Path("env/setup-build-env.sh"),
        Path("scripts/verify-lockfiles.py"),
    ):
        if relative != Path("env/share-generated-permissions.sh"):
            (workspace / relative).write_text("old\n", encoding="utf-8")
        (staged / relative).write_text("new\n", encoding="utf-8")
        (staged / relative).chmod(0o770)

    lock = workspace / "environments/gcc/core/spack.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("locked\n", encoding="utf-8")
    environment = workspace / "environments/gcc/core/spack.yaml"
    environment.write_text("spack: {}\n", encoding="utf-8")

    refreshed = REFRESH.refresh_control_files(
        blueprint_path=blueprint,
        staged_workspace=staged,
        workspace=workspace,
    )

    assert refreshed == [
        Path("cse-build"),
        Path("configs/common/config.yaml"),
        Path("env/share-generated-permissions.sh"),
        Path("env/setup-build-env.sh"),
        Path("scripts/verify-lockfiles.py"),
    ]
    assert (workspace / "cse-build").read_text(encoding="utf-8") == "new\n"
    assert (workspace / "configs/common/config.yaml").read_text(
        encoding="utf-8"
    ) == "new\n"
    assert (workspace / "env/share-generated-permissions.sh").read_text(
        encoding="utf-8"
    ) == "new\n"
    assert stat.S_IMODE((workspace / "cse-build").stat().st_mode) == 0o770
    assert lock.read_text(encoding="utf-8") == "locked\n"
    assert environment.read_text(encoding="utf-8") == "spack: {}\n"


def test_rejects_controls_for_another_system(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint.yaml"
    write_yaml(blueprint, {"control_files": ["cse-build"]})
    workspace = tmp_path / "workspace"
    staged = tmp_path / "staged"
    write_yaml(workspace / "workspace-manifest.yaml", manifest("raider"))
    write_yaml(staged / "workspace-manifest.yaml", manifest("blueback"))
    (workspace / "cse-build").write_text("old\n", encoding="utf-8")
    (staged / "cse-build").write_text("new\n", encoding="utf-8")

    with pytest.raises(REFRESH.RefreshError, match="do not match"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint,
            staged_workspace=staged,
            workspace=workspace,
        )

    assert (workspace / "cse-build").read_text(encoding="utf-8") == "old\n"


def test_rejects_control_path_escape(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint.yaml"
    write_yaml(blueprint, {"control_files": ["../cse-build"]})

    with pytest.raises(REFRESH.RefreshError, match="invalid control file path"):
        REFRESH._control_files(REFRESH._load_mapping(blueprint, "blueprint"))


def test_rejects_values_for_another_trial_release(tmp_path: Path) -> None:
    workspace = tmp_path / "raider-trial-001"

    with pytest.raises(REFRESH.RefreshError, match="workspace directory"):
        REFRESH._validate_values_identity(
            values={
                "system": {"name": "raider"},
                "release": "raider-trial-002",
            },
            workspace=workspace,
            existing_manifest=manifest("raider"),
        )
