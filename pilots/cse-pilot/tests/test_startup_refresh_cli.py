"""Exercise startup refresh through the real Composer CLI and pilot templates."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

pytest.importorskip("stack_composer")

PILOT = Path(__file__).resolve().parents[1]
REFRESH = PILOT / "scripts/refresh-workspace-controls.py"
STARTUP_FILES = {
    "cse-build", "env/share-generated-permissions.sh", "env/workspace-shell.rc",
    "scripts/workspace-permissions.py", "BUILDER-HANDOFF.md",
}


def yaml_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def make_workspace(tmp_path):
    values = yaml.safe_load((PILOT / "site-values.example.yaml").read_text())
    recorded = tmp_path / "recorded-values.yaml"
    yaml_file(recorded, values)
    catalog = tmp_path / "catalog"
    yaml_file(catalog / "manifest.yaml", {
        "schema_version": 1, "kind": "static-platform-catalog",
        "system": values["system"], "release": "catalog-001", "scope_root": "scopes", "scopes": [],
    })
    (catalog / "scopes").mkdir()
    blueprint = yaml.safe_load((PILOT / "blueprint.yaml").read_text())
    for dotted in blueprint["catalog_scope_values"]:
        value = values
        for part in dotted.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value:
            (catalog / value).mkdir(parents=True, exist_ok=True)
    composer = tmp_path / "composer.py"
    composer.write_text("from stack_composer.cli import main\nmain()\n")
    workspace = tmp_path / values["release"]
    result = subprocess.run([sys.executable, str(composer), "init-workspace", "--blueprint", str(PILOT),
                             "--catalog", str(catalog), "--values", str(recorded), "--output", str(workspace)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return workspace, recorded, composer, values


def refresh(workspace, recorded, composer, *extra):
    return subprocess.run([sys.executable, str(REFRESH), "--composer", str(composer),
                           "--blueprint", str(PILOT), "--values", str(recorded),
                           "--workspace", str(workspace), "--scope", "startup", *extra],
                          text=True, capture_output=True)


def snapshot(paths):
    return {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in paths}


def tag_only_values(recorded, values):
    values["package_repo"].pop("commit")
    yaml_file(recorded, values)


@pytest.mark.parametrize("stage", ["empty", "partial", "complete"])
def test_startup_refresh_accepts_recorded_tag_without_commit(tmp_path, stage):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    tag_only_values(recorded, values)
    repo_file = workspace / "configs/common/repos.yaml"
    repositories = yaml.safe_load(repo_file.read_text())
    repositories["repos"]["builtin"] = {"git": values["package_repo"]["git"], "tag": values["package_repo"]["tag"]}
    yaml_file(repo_file, repositories)
    for index, environment in enumerate(sorted((workspace / "environments").rglob("spack.yaml"))):
        if stage == "complete" or (stage == "partial" and index < 3):
            environment.with_suffix(".lock").write_text('{"locked": "existing package graph"}\n')
            prefix = workspace / "store" / str(index) / "lib.so"
            prefix.parent.mkdir(parents=True)
            prefix.write_bytes(b"installed package")
    for name in STARTUP_FILES:
        path = workspace / name
        path.write_text(path.read_text() + "\n# Previous startup control\n")
    paths = [path for path in workspace.rglob("*") if path.is_file()]
    before = snapshot([recorded, PILOT / "blueprint.yaml", *paths])
    result = refresh(workspace, recorded, composer, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Would refresh" in result.stdout
    assert snapshot(before) == before
    result = refresh(workspace, recorded, composer)
    assert result.returncode == 0, result.stdout + result.stderr
    protected = {path: state for path, state in before.items()
                 if path not in {workspace / name for name in STARTUP_FILES}}
    assert snapshot(protected) == protected
    assert all((workspace / name).read_bytes() != before[workspace / name][0]
               for name in STARTUP_FILES)
    record = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    assert {entry["path"] for entry in json.loads(record.read_text())["entries"]} == STARTUP_FILES
    assert not list(tmp_path.glob(".trial-001.control-refresh-*"))


def test_full_refresh_still_requires_exact_package_commit(tmp_path):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    tag_only_values(recorded, values)
    before = snapshot([path for path in workspace.rglob("*") if path.is_file()])
    result = refresh(workspace, recorded, composer, "--scope", "controls", "--dry-run")
    assert result.returncode != 0
    assert "missing-value at values.package_repo.commit: required" in result.stderr
    assert snapshot(before) == before


@pytest.mark.parametrize("field,value", [
    (("paths", "install_tree"), "/different/store"),
    (("spack", "commit"), "a" * 40),
    (("permissions", "group"), "different-group"),
])
def test_startup_refresh_rejects_changed_recorded_identity(tmp_path, field, value):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    tag_only_values(recorded, values)
    values[field[0]][field[1]] = value
    yaml_file(recorded, values)
    before = snapshot([path for path in workspace.rglob("*") if path.is_file()])
    result = refresh(workspace, recorded, composer)
    assert result.returncode != 0
    assert "startup refresh would change recorded roots or runtime identity" in result.stderr
    assert snapshot(before) == before


def test_startup_refresh_still_requires_runtime_identity(tmp_path):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    tag_only_values(recorded, values)
    values["spack"].pop("commit")
    yaml_file(recorded, values)
    result = refresh(workspace, recorded, composer, "--dry-run")
    assert result.returncode != 0
    assert "missing-value at values.spack.commit: required" in result.stderr
    assert "missing-value at values.package_repo.commit" not in result.stderr


def test_startup_refresh_checks_existing_dependencies_before_promotion(tmp_path):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    tag_only_values(recorded, values)
    (workspace / "package-repos/overlay-inventory.json").unlink()
    before = snapshot([path for path in workspace.rglob("*") if path.is_file()])
    result = refresh(workspace, recorded, composer)
    assert result.returncode != 0
    assert "cse-build requires package-repos/overlay-inventory.json" in result.stderr
    assert snapshot(before) == before
