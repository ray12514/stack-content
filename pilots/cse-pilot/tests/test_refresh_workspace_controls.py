from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

import pytest
import yaml

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "refresh-workspace-controls.py"
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
            ],
            "control_trees": ["modulefiles", "presentation"],
        },
    )
    workspace = tmp_path / "workspace"
    staged = tmp_path / "staged"
    for root in (workspace, staged):
        write_yaml(root / "workspace-manifest.yaml", manifest())
        (root / "env").mkdir()
        (root / "configs" / "common").mkdir(parents=True)
        (root / "scripts").mkdir()
    old_module = workspace / "modulefiles/cse/old-GCC"
    old_module.parent.mkdir(parents=True)
    old_module.write_text("old module\n", encoding="utf-8")
    new_module = staged / "modulefiles/cse/init-GCC"
    new_module.parent.mkdir(parents=True)
    new_module.write_text("new module\n", encoding="utf-8")
    old_presentation = workspace / "presentation/mpi-consumer-candidates.yaml"
    old_presentation.parent.mkdir()
    old_presentation.write_text("status: old\n", encoding="utf-8")
    new_presentation = staged / "presentation/mpi-consumer-candidates.yaml"
    new_presentation.parent.mkdir()
    new_presentation.write_text("status: new\n", encoding="utf-8")
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
        Path("modulefiles"),
        Path("presentation"),
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
    assert not old_module.exists()
    assert (workspace / "modulefiles/cse/init-GCC").read_text(
        encoding="utf-8"
    ) == "new module\n"
    assert old_presentation.read_text(encoding="utf-8") == "status: new\n"


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


def test_rejects_control_tree_path_escape(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint.yaml"
    write_yaml(
        blueprint,
        {"control_files": ["cse-build"], "control_trees": ["../modulefiles"]},
    )

    with pytest.raises(REFRESH.RefreshError, match="invalid control tree path"):
        REFRESH._control_trees(REFRESH._load_mapping(blueprint, "blueprint"))


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


def refresh_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    blueprint = tmp_path / "blueprint.yaml"
    write_yaml(
        blueprint,
        {
            "control_files": ["cse-build", "env/setup.sh"],
            "control_trees": ["modulefiles", "presentation"],
        },
    )
    workspace, staged = tmp_path / "workspace", tmp_path / "staged"
    for root, label in ((workspace, "old"), (staged, "new")):
        write_yaml(root / "workspace-manifest.yaml", manifest())
        for relative in (
            "cse-build",
            "env/setup.sh",
            "modulefiles/lane",
            "presentation/lanes.yaml",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(label)
            path.chmod(0o750 if label == "old" else 0o770)
    write_yaml(
        workspace / "environments/gcc/core/spack.yaml",
        {"spack": {"specs": ["example"]}},
    )
    (workspace / "environments/gcc/core/spack.lock").write_bytes(b"frozen lock\n")
    return blueprint, staged, workspace


def visible_snapshot(workspace: Path) -> dict:
    return {
        str(p.relative_to(workspace)): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
        for p in workspace.rglob("*")
        if p.is_file() and not p.relative_to(workspace).parts[0].startswith(".cse-")
    }


def test_presentation_refresh_and_restore_preserve_completed_inputs(
    tmp_path: Path,
) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    before = visible_snapshot(workspace)
    refreshed = REFRESH.refresh_control_files(
        blueprint_path=blueprint,
        staged_workspace=staged,
        workspace=workspace,
        scope="presentation",
    )
    assert refreshed == [Path("modulefiles"), Path("presentation")]
    after = visible_snapshot(workspace)
    for path in before:
        if not path.startswith(("modulefiles/", "presentation/")):
            assert after[path] == before[path]
    assert after["modulefiles/lane"][0] == b"new"
    records = list((workspace / ".cse-control-refresh").glob("*/record.json"))
    assert len(records) == 1
    REFRESH.restore_control_files(workspace=workspace, record_path=records[0])
    assert visible_snapshot(workspace) == before
    assert json.loads(records[0].read_text())["status"] == "restored"


def test_dry_run_leaves_workspace_completely_untouched(tmp_path: Path) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    before = visible_snapshot(workspace)
    paths_before = sorted(p.relative_to(workspace) for p in workspace.rglob("*"))
    assert REFRESH.refresh_control_files(
        blueprint_path=blueprint,
        staged_workspace=staged,
        workspace=workspace,
        dry_run=True,
    )
    assert visible_snapshot(workspace) == before
    assert (
        sorted(p.relative_to(workspace) for p in workspace.rglob("*")) == paths_before
    )


@pytest.mark.parametrize("failed_path", ["env/setup.sh", "presentation"])
def test_late_failure_rolls_back_all_selected_controls(
    tmp_path: Path, monkeypatch, failed_path: str
) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    before = visible_snapshot(workspace)
    replace = Path.replace
    failed = False

    def fail_once(source, destination):
        nonlocal failed
        if Path(destination) == workspace / failed_path and not failed:
            failed = True
            raise OSError("injected disk failure")
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_once)
    with pytest.raises(OSError, match="injected disk failure"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
        )
    assert failed
    assert visible_snapshot(workspace) == before


def test_restore_rejects_later_control_edits(tmp_path: Path) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    REFRESH.refresh_control_files(
        blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
    )
    record = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    (workspace / "cse-build").write_text("later operator edit")
    before = visible_snapshot(workspace)
    with pytest.raises(REFRESH.RefreshError, match="changed since"):
        REFRESH.restore_control_files(workspace=workspace, record_path=record)
    assert visible_snapshot(workspace) == before


@pytest.mark.parametrize(
    "path",
    ["environments/gcc/core/spack.lock", "package-repos", "catalog", "spack.lock"],
)
def test_rejects_build_inputs_in_refresh_allowlist(tmp_path: Path, path: str) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    write_yaml(blueprint, {"control_files": [path]})
    with pytest.raises(REFRESH.RefreshError, match="protected"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
        )


def test_rejects_symlink_ancestor_without_changing_target(tmp_path: Path) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    outside = tmp_path / "outside"
    (workspace / "env").rename(outside)
    (workspace / "env").symlink_to(outside, target_is_directory=True)
    with pytest.raises(REFRESH.RefreshError, match="symlink"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
        )
    assert (outside / "setup.sh").read_text() == "old"


def test_missing_new_verifier_dependency_does_not_block_presentation(
    tmp_path: Path,
) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    write_yaml(
        blueprint,
        {
            "control_files": ["cse-build"],
            "control_trees": ["modulefiles"],
            "control_file_dependencies": {"cse-build": ["scripts/new-verifier.py"]},
        },
    )
    with pytest.raises(REFRESH.RefreshError, match="candidate preparation"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
        )
    REFRESH.refresh_control_files(
        blueprint_path=blueprint,
        staged_workspace=staged,
        workspace=workspace,
        scope="presentation",
    )
    assert (workspace / "cse-build").read_text() == "old"


def test_concurrent_refresh_fails_without_mutation(tmp_path: Path) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    before = visible_snapshot(workspace)
    (workspace / ".cse-refresh.lock").mkdir()
    with pytest.raises(REFRESH.RefreshError, match="refresh lock"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
        )
    assert visible_snapshot(workspace) == before


def test_restore_removes_files_introduced_by_refresh(tmp_path: Path) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    (workspace / "env/setup.sh").unlink()
    before = visible_snapshot(workspace)
    REFRESH.refresh_control_files(
        blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
    )
    record = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    REFRESH.restore_control_files(workspace=workspace, record_path=record)
    assert visible_snapshot(workspace) == before


def test_incomplete_rollback_retains_record_and_blocks_next_refresh(
    tmp_path: Path, monkeypatch
) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    replace = Path.replace

    def fail_persistently(source, destination):
        if Path(destination) == workspace / "env/setup.sh":
            raise OSError("disk unavailable")
        return replace(source, destination)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "replace", fail_persistently)
        with pytest.raises(REFRESH.RefreshError, match="rollback needs recovery"):
            REFRESH.refresh_control_files(
                blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
            )
    record = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    assert json.loads(record.read_text())["status"] == "recovery-required"
    assert (record.parent / "1/old").read_text() == "old"
    with pytest.raises(REFRESH.RefreshError, match="unfinished refresh"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
        )
    REFRESH.recover_control_files(workspace=workspace, record_path=record, dry_run=True)
    assert not (workspace / "env/setup.sh").exists()
    REFRESH.recover_control_files(workspace=workspace, record_path=record)
    assert (workspace / "env/setup.sh").read_text() == "old"
    assert (workspace / "cse-build").read_text() == "old"
    assert json.loads(record.read_text())["status"] == "rolled-back"
    REFRESH.refresh_control_files(
        blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
    )


def test_restore_rejects_protected_paths_in_damaged_record(tmp_path: Path) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    REFRESH.refresh_control_files(
        blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
    )
    record_path = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    record = json.loads(record_path.read_text())
    record["entries"][0]["path"] = "environments/gcc/core/spack.lock"
    record["entries"][0]["new"] = REFRESH._fingerprint(
        workspace / "environments/gcc/core/spack.lock"
    )
    record_path.write_text(json.dumps(record))
    with pytest.raises(REFRESH.RefreshError, match="protected"):
        REFRESH.restore_control_files(workspace=workspace, record_path=record_path)
    assert (
        workspace / "environments/gcc/core/spack.lock"
    ).read_bytes() == b"frozen lock\n"


def test_restore_checks_later_edits_after_acquiring_lock(
    tmp_path: Path, monkeypatch
) -> None:
    from contextlib import contextmanager

    blueprint, staged, workspace = refresh_fixture(tmp_path)
    REFRESH.refresh_control_files(
        blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
    )
    record = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    lock = REFRESH._refresh_lock

    @contextmanager
    def intervening_update(root):
        (root / "cse-build").write_text("intervening update")
        with lock(root):
            yield

    monkeypatch.setattr(REFRESH, "_refresh_lock", intervening_update)
    with pytest.raises(REFRESH.RefreshError, match="changed since"):
        REFRESH.restore_control_files(workspace=workspace, record_path=record)
    assert (workspace / "cse-build").read_text() == "intervening update"


def test_restore_reports_completed_controls_when_final_receipt_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    blueprint, staged, workspace = refresh_fixture(tmp_path)
    before = visible_snapshot(workspace)
    REFRESH.refresh_control_files(
        blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
    )
    record = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    journal = REFRESH._journal

    def fail_final_receipt(path, data):
        if path == record and data["status"] == "restored":
            raise OSError("receipt write failed")
        return journal(path, data)

    monkeypatch.setattr(REFRESH, "_journal", fail_final_receipt)
    with pytest.raises(
        REFRESH.RefreshError, match="controls restored.*could not be finalized"
    ):
        REFRESH.restore_control_files(workspace=workspace, record_path=record)
    assert visible_snapshot(workspace) == before
    assert json.loads(record.read_text())["status"] == "restoring"
    with pytest.raises(REFRESH.RefreshError, match="unfinished refresh"):
        REFRESH.refresh_control_files(
            blueprint_path=blueprint, staged_workspace=staged, workspace=workspace
        )
