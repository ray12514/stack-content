from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/refresh-workspace-controls.py"
SPEC = importlib.util.spec_from_file_location("legacy_refresh", SCRIPT)
REFRESH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFRESH)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def fixture(tmp_path):
    workspace, candidate = tmp_path / "old", tmp_path / "candidate"
    manifest = {
        "blueprint": "trial",
        "catalog": {"system": "lab", "release": "catalog-1"},
    }
    old = {
        "spack": {
            "include:": [
                "../../../configs/common",
                "../../../configs/environments/gcc/core",
            ],
            "specs": [{"group": "payload", "specs": ["tiny@1.0"]}],
            "concretizer": {"reuse": False},
            "view": {"site": {"root": "/old/site"}},
        }
    }
    for root in (workspace, candidate):
        write(root / "workspace-manifest.yaml", manifest)
        write(root / "environments/gcc/core/spack.yaml", old)
        (root / "configs/environments/gcc/core").mkdir(parents=True)
    write(
        workspace / "configs/common/repos.yaml", {"repos": {"builtin": {"tag": "old"}}}
    )
    (workspace / "environments/gcc/core/spack.lock").write_bytes(
        b"original exact lock\n"
    )
    proposed = {
        "spack": {
            "specs": ["never-copy-me@2.0"],
            "view": {"cse_modules": {"root": "/old/modules-view", "group": "payload"}},
        }
    }
    write(candidate / "environments/gcc/core/spack.yaml", proposed)
    write(
        candidate / "configs/environments/gcc/core/modules.yaml",
        {
            "modules": {
                "default": {
                    "enable": ["tcl"],
                    "use_view": "cse_modules",
                    "roots": {"tcl": "/old/modulefiles"},
                }
            }
        },
    )
    return workspace, candidate


def test_upgrade_and_restore_preserve_installed_graph_and_unrelated_views(tmp_path):
    workspace, candidate = fixture(tmp_path)
    env = workspace / "environments/gcc/core/spack.yaml"
    original = env.read_bytes()
    lock = workspace / "environments/gcc/core/spack.lock"
    selected = REFRESH.upgrade_module_policy(
        workspace=workspace, candidate=candidate, dry_run=True
    )
    assert env.read_bytes() == original
    assert not (workspace / ".cse-control-refresh").exists()
    assert set(selected) == {
        Path("environments/gcc/core/spack.yaml"),
        Path("configs/environments/gcc/core/modules.yaml"),
    }
    REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    new = yaml.safe_load(env.read_text())["spack"]
    assert new["specs"] == [{"group": "payload", "specs": ["tiny@1.0"]}]
    assert new["concretizer"] == {"reuse": False}
    assert new["include:"] == [
        "../../../configs/common",
        "../../../configs/environments/gcc/core",
    ]
    assert set(new["view"]) == {"site", "cse_modules"}
    assert lock.read_bytes() == b"original exact lock\n"
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    REFRESH.restore_control_files(workspace=workspace, record_path=record)
    assert env.read_bytes() == original
    assert not (workspace / "configs/environments/gcc/core/modules.yaml").exists()


def test_admit_existing_recipe_inventory_without_changing_tag_pin_then_restore(
    tmp_path,
):
    workspace, _ = fixture(tmp_path)
    helper = SCRIPT.parents[1] / "templates/scripts/verify-overlay-inputs.py"
    repository = workspace / "package-repos/spack_repo/legacy"
    (repository / "packages/tiny").mkdir(parents=True)
    (repository / "repo.yaml").write_text("repo:\n  namespace: legacy\n  api: v2.0\n")
    recipe = repository / "packages/tiny/package.py"
    recipe.write_text("from spack.package import *\nclass Tiny(Package):\n    pass\n")
    (workspace / "scripts").mkdir()
    import subprocess
    import sys

    inventory = tmp_path / "reviewed.json"
    subprocess.run(
        [
            sys.executable,
            str(helper),
            "--root",
            str(workspace / "package-repos"),
            "--candidate",
            str(inventory),
        ],
        check=True,
    )
    frozen = {
        str(p.relative_to(workspace)): p.read_bytes()
        for p in [
            recipe,
            repository / "repo.yaml",
            workspace / "configs/common/repos.yaml",
        ]
    }
    REFRESH.admit_overlay_inventory(
        workspace=workspace, inventory_path=inventory, helper_path=helper, dry_run=True
    )
    assert not (workspace / "package-repos/overlay-inventory.json").exists()
    REFRESH.admit_overlay_inventory(
        workspace=workspace, inventory_path=inventory, helper_path=helper
    )
    assert (
        workspace / "package-repos/overlay-inventory.json"
    ).read_bytes() == inventory.read_bytes()
    assert all((workspace / p).read_bytes() == data for p, data in frozen.items())
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    REFRESH.restore_control_files(workspace=workspace, record_path=record)
    assert not (workspace / "package-repos/overlay-inventory.json").exists()
    assert not (workspace / "scripts/verify-overlay-inputs.py").exists()


@pytest.mark.parametrize(
    "failure",
    [
        "missing-group",
        "inactive-include",
        "missing-view",
        "smuggled-packages",
        "missing-lock",
    ],
)
def test_invalid_module_policy_is_rejected_without_partial_update(tmp_path, failure):
    workspace, candidate = fixture(tmp_path)
    env = workspace / "environments/gcc/core/spack.yaml"
    module = candidate / "configs/environments/gcc/core/modules.yaml"
    if failure == "missing-group":
        write(
            candidate / "environments/gcc/core/spack.yaml",
            {"spack": {"view": {"cse_modules": {"root": "/view", "group": "absent"}}}},
        )
    elif failure == "inactive-include":
        data = yaml.safe_load(env.read_text())
        data["spack"]["include:"] = ["../../../configs/common"]
        write(env, data)
    elif failure == "missing-view":
        write(module, {"modules": {"default": {"use_view": "absent"}}})
    elif failure == "smuggled-packages":
        write(module, {"modules": {}, "packages": {"all": {"target": ["new"]}}})
    else:
        env.with_name("spack.lock").unlink()
    before = env.read_bytes()
    with pytest.raises(REFRESH.RefreshError):
        REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    assert env.read_bytes() == before
    assert not (workspace / ".cse-control-refresh").exists()


@pytest.mark.parametrize("changed", ["lock", "repo", "non-view"])
def test_restore_refuses_protected_inputs_changed_after_upgrade(tmp_path, changed):
    workspace, candidate = fixture(tmp_path)
    REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    if changed == "lock":
        (workspace / "environments/gcc/core/spack.lock").write_text("different lock")
    elif changed == "repo":
        (workspace / "configs/common/repos.yaml").write_text(
            "repos: {builtin: {tag: new}}"
        )
    else:
        path = workspace / "environments/gcc/core/spack.yaml"
        data = yaml.safe_load(path.read_text())
        data["spack"]["specs"] = ["different-package"]
        write(path, data)
    with pytest.raises(
        REFRESH.RefreshError, match="protected workspace inputs changed"
    ):
        REFRESH.restore_control_files(workspace=workspace, record_path=record)


def test_partial_module_upgrade_failure_rolls_back_all_selected_files(
    tmp_path, monkeypatch
):
    workspace, candidate = fixture(tmp_path)
    env = workspace / "environments/gcc/core/spack.yaml"
    original = env.read_bytes()
    replace = Path.replace

    def fail(self, target):
        if (
            self.name == "new"
            and Path(target) == workspace / "configs/environments/gcc/core/modules.yaml"
        ):
            raise OSError("simulated disk failure")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="simulated disk failure"):
        REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    assert env.read_bytes() == original
    assert not (workspace / "configs/environments/gcc/core/modules.yaml").exists()
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    assert json.loads(record.read_text())["status"] == "rolled-back"


def test_recover_after_module_upgrade_rollback_leaves_environment_temporarily_missing(
    tmp_path, monkeypatch
):
    workspace, candidate = fixture(tmp_path)
    env = workspace / "environments/gcc/core/spack.yaml"
    original = env.read_bytes()
    replace = Path.replace

    def fail(self, target):
        if (self.name == "new" and Path(target).name == "modules.yaml") or (
            self.name == "rollback" and Path(target) == env
        ):
            raise OSError("simulated disk failure")
        return replace(self, target)

    with monkeypatch.context() as context:
        context.setattr(Path, "replace", fail)
        with pytest.raises(REFRESH.RefreshError, match="needs recovery"):
            REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    assert not env.exists()
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    REFRESH.recover_control_files(workspace=workspace, record_path=record)
    assert env.read_bytes() == original
    assert not (workspace / "configs/environments/gcc/core/modules.yaml").exists()


def test_module_policy_cli_accepts_explicit_candidate_and_environment(tmp_path, capsys):
    workspace, candidate = fixture(tmp_path)
    assert (
        REFRESH.main(
            [
                "--workspace",
                str(workspace),
                "--candidate",
                str(candidate),
                "--scope",
                "module-policy",
                "--environment",
                "gcc/core",
                "--dry-run",
            ]
        )
        == 0
    )
    assert "Would upgrade module policy" in capsys.readouterr().out
    assert not (workspace / "configs/environments/gcc/core/modules.yaml").exists()


@pytest.mark.parametrize(
    "policy",
    [
        {"view": {"cse_modules": {"root": "/view", "group": ["payload"]}}},
        {"view": {"cse_modules": {"root": 7}}},
    ],
)
def test_unsupported_view_shape_returns_actionable_error(tmp_path, policy):
    workspace, candidate = fixture(tmp_path)
    write(candidate / "environments/gcc/core/spack.yaml", {"spack": policy})
    with pytest.raises(REFRESH.RefreshError, match="view"):
        REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)


def test_stale_inventory_cannot_admit_changed_existing_recipe(tmp_path):
    workspace, _ = fixture(tmp_path)
    helper = SCRIPT.parents[1] / "templates/scripts/verify-overlay-inputs.py"
    repository = workspace / "package-repos/spack_repo/legacy"
    (repository / "packages/tiny").mkdir(parents=True)
    (repository / "repo.yaml").write_text("repo:\n  namespace: legacy\n  api: v2.0\n")
    recipe = repository / "packages/tiny/package.py"
    recipe.write_text("class Tiny: pass\n")
    (workspace / "scripts").mkdir()
    import subprocess
    import sys

    inventory = tmp_path / "reviewed.json"
    subprocess.run(
        [
            sys.executable,
            str(helper),
            "--root",
            str(workspace / "package-repos"),
            "--candidate",
            str(inventory),
        ],
        check=True,
    )
    recipe.write_text("class Tiny: modified = True\n")
    assert (
        REFRESH.main(
            [
                "--workspace",
                str(workspace),
                "--admit-overlay-inventory",
                str(inventory),
                "--overlay-helper",
                str(helper),
            ]
        )
        == 2
    )
    assert not (workspace / "package-repos/overlay-inventory.json").exists()
    assert not (workspace / "scripts/verify-overlay-inputs.py").exists()
    assert recipe.read_text() == "class Tiny: modified = True\n"


def test_restore_cannot_smuggle_package_policy_through_module_backup(tmp_path):
    workspace, candidate = fixture(tmp_path)
    old_module = workspace / "configs/environments/gcc/core/modules.yaml"
    write(old_module, {"modules": {}})
    REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    # A valid old record cannot be relabeled as a generic controls operation.
    data = json.loads(record.read_text())
    data["path_policy"] = "controls"
    record.write_text(json.dumps(data))
    with pytest.raises(REFRESH.RefreshError, match="protected build input"):
        REFRESH.restore_control_files(workspace=workspace, record_path=record)


def test_restore_refuses_changed_environment_package_scope(tmp_path):
    workspace, candidate = fixture(tmp_path)
    packages = workspace / "configs/environments/gcc/core/packages.yaml"
    write(packages, {"packages": {"all": {"target": ["x86_64"]}}})
    REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    write(packages, {"packages": {"all": {"target": ["zen4"]}}})
    with pytest.raises(
        REFRESH.RefreshError, match="protected workspace inputs changed"
    ):
        REFRESH.restore_control_files(workspace=workspace, record_path=record)


def test_interruption_before_staging_finishes_can_be_recovered(tmp_path, monkeypatch):
    workspace, candidate = fixture(tmp_path)
    original = (workspace / "environments/gcc/core/spack.yaml").read_bytes()
    import shutil

    copy = shutil.copy2

    def interrupt(source, destination, *args, **kwargs):
        if Path(destination).name == "old":
            raise KeyboardInterrupt("interrupted staging")
        return copy(source, destination, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(shutil, "copy2", interrupt)
        with pytest.raises(KeyboardInterrupt):
            REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
    (record,) = (workspace / ".cse-control-refresh").glob("*/record.json")
    assert REFRESH.recover_control_files(workspace=workspace, record_path=record) == []
    assert (workspace / "environments/gcc/core/spack.yaml").read_bytes() == original
    REFRESH.upgrade_module_policy(workspace=workspace, candidate=candidate)
