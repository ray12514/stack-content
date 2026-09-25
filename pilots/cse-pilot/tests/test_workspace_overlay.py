"""Same-workspace overlays preserve the built state and block stale lock reuse."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "templates/scripts/workspace-overlay.py"
spec = importlib.util.spec_from_file_location("workspace_overlay", str(SCRIPT))
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("CSE_BUILD_WORKSPACE", raising=False)
    monkeypatch.delenv("CSE_MAINTENANCE_LOCK_FD", raising=False)
    root = tmp_path / "workspace"
    repo = root / "package-repos/spack_repo/cse_trials"
    write(repo / "repo.yaml", "repo:\n  namespace: cse_trials\n  api: v2.0\n")
    write(repo / "packages/tiny/package.py", "class Tiny:\n    old = True\n")
    write(repo / "packages/tiny/old.patch", "retained original support\n")
    write(root / "configs/common/repos.yaml", "repos:\n  cse_trials: ../../package-repos/spack_repo/cse_trials\n")
    write(root / "configs/common/config.yaml", "config:\n  install_tree: /accepted/store\n")
    write(root / "workspace-manifest.yaml", "schema_version: 1\n")
    write(root / "modulefiles/cse/init-GCC", "#%Module1.0\n# accepted entrance\n")
    for name, package in (("cce/common", "tiny"), ("cce/serial", "tiny"), ("gcc/core", "other")):
        env = root / "environments" / name
        write(env / "spack.yaml", "spack:\n  include:: [../../../configs/common]\n  specs: [" + package + "]\n")
        lock = {"_meta": {"lockfile-version": 6}, "roots": [{"hash": "a" * 32}],
                "concrete_specs": {"a" * 32: {"name": package, "version": "1.0"}}}
        write(env / "spack.lock", json.dumps(lock))
    write(root / "environments/cce/unlocked/spack.yaml", "spack:\n  specs: [tiny]\n")
    source = tmp_path / "correction/tiny"
    write(source / "package.py", "class Tiny:\n    patch('fixed.patch')\n")
    write(source / "fixed.patch", "reviewed correction support\n")
    return root, source


def fingerprints(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()
            and ".cse-overlay" not in path.parts and path.name != ".cse-maintenance.lock"}


def admit(root):
    (root / overlay.INVENTORY).write_bytes(overlay.recovery.json_bytes(overlay.gate.snapshot(root / "package-repos")))


def test_reconcile_registers_new_netlib_and_reports_already_recorded_gsl(workspace):
    root, _ = workspace
    packages = root / "package-repos/spack_repo/cse_trials/packages"
    write(packages / "gsl/package.py", "class Gsl:\n    pass\n")
    admit(root)
    old_inventory = (root / overlay.INVENTORY).read_bytes()
    write(packages / "netlib_lapack/package.py", "class NetlibLapack:\n    patch('cce.patch')\n")
    write(packages / "netlib_lapack/cce.patch", "intentional CCE correction\n")
    before = fingerprints(root)
    preview = overlay.reconcile_overlay(root, ["netlib-lapack", "gsl"], dry_run=True)
    assert preview["packages"] == {"netlib-lapack": "new", "gsl": "already-recorded"}
    assert fingerprints(root) == before
    assert not (root / ".cse-overlay").exists()
    record = overlay.reconcile_overlay(root, ["netlib-lapack", "gsl"])
    assert record["status"] == "applied"
    assert record["affected"] == ["cce/common", "cce/serial", "gcc/core"]
    assert record["unlocked"] == ["cce/unlocked"]
    assert overlay.gate.check(root / "package-repos") == []
    assert {name: state for name, state in fingerprints(root).items() if name != overlay.INVENTORY} == {
        name: state for name, state in before.items() if name != overlay.INVENTORY}
    with pytest.raises(overlay.Error, match="explicit selected reconcretization"):
        overlay.check_workspace(root, ["cce/common"])
    assert overlay.reconcile_overlay(root, ["netlib-lapack", "gsl"])["status"] == "already-recorded"
    assert len(overlay.records(root)) == 1
    overlay.restore_overlay(root, record["id"])
    assert (root / overlay.INVENTORY).read_bytes() == old_inventory
    assert fingerprints(root) == before
    assert overlay.gate.check(root / "package-repos")


def test_reconcile_accepts_changed_recipe_and_removed_unreferenced_file(workspace):
    root, source = workspace
    admit(root)
    target = root / "package-repos/spack_repo/cse_trials/packages/tiny"
    (target / "package.py").write_text("class Tiny:\n    corrected = True\n")
    (target / "old.patch").unlink()
    record = overlay.reconcile_overlay(root, ["tiny"])
    assert record["packages"] == {"tiny": "changed"}
    overlay.mark_resolved(root, "cce/common")
    assert overlay.check_workspace(root, ["cce/common"]) == []
    with pytest.raises(overlay.Error, match="explicit selected reconcretization"):
        overlay.check_workspace(root, ["cce/serial"])
    (target / "package.py").write_text("# a later edit\n")
    with pytest.raises(overlay.Error, match="Later workspace/lock changes"):
        overlay.restore_overlay(root, record["id"])


def test_reconcile_failed_verification_restores_only_inventory(workspace, monkeypatch):
    root, _ = workspace
    admit(root)
    recipe = root / "package-repos/spack_repo/cse_trials/packages/tiny/package.py"
    recipe.write_text("class Tiny:\n    correction = True\n")
    before = fingerprints(root)
    monkeypatch.setattr(overlay.gate, "check", lambda root: ["simulated concurrent change"])
    with pytest.raises(overlay.Error, match="changed during overlay reconciliation"):
        overlay.reconcile_overlay(root, ["tiny"])
    assert fingerprints(root) == before
    assert overlay.records(root)[0]["status"] == "restored"


@pytest.mark.parametrize("problem", ["other-package", "repo-identity", "missing-patch", "absent-package"])
def test_reconcile_rejects_unselected_changes_or_incomplete_inputs(workspace, problem):
    root, _ = workspace
    repo = root / "package-repos/spack_repo/cse_trials"
    admit(root)
    write(repo / "packages/netlib_lapack/package.py", "class NetlibLapack:\n    pass\n")
    if problem == "other-package":
        write(repo / "packages/tiny/package.py", "# unrelated edit\n")
    elif problem == "repo-identity":
        write(repo / "repo.yaml", "repo:\n  namespace: different\n  api: v2.0\n")
    elif problem == "missing-patch":
        write(repo / "packages/netlib_lapack/package.py", "patch('missing.patch')\n")
    before = fingerprints(root)
    with pytest.raises((overlay.Error, ValueError)):
        overlay.reconcile_overlay(root, ["netlib-lapack"] + (["gsl"] if problem == "absent-package" else []))
    assert fingerprints(root) == before
    assert not (root / ".cse-overlay").exists()


def test_apply_changes_only_whole_recipe_and_inventory_and_restore_recovers_original(workspace):
    root, source = workspace
    admit(root)
    before = fingerprints(root)
    record = overlay.apply_overlay(root, source, environment="cce/common")
    assert record["status"] == "applied"
    assert record["affected"] == ["cce/common", "cce/serial"]
    assert record["unchanged"] == ["gcc/core"]
    assert record["unlocked"] == ["cce/unlocked"]
    target = root / record["target"]
    assert not (target / "old.patch").exists()
    assert (target / "fixed.patch").read_bytes() == (source / "fixed.patch").read_bytes()
    assert not overlay.gate.check(root / "package-repos")
    assert not any("candidate" in path.name for path in root.parent.iterdir())
    after = fingerprints(root)
    for name, value in before.items():
        if not name.startswith(record["target"] + "/") and name != overlay.INVENTORY:
            assert after[name] == value
    restored = overlay.restore_overlay(root, record["id"])
    assert restored["status"] == "restored"
    assert fingerprints(root) == before


def test_apply_admits_legacy_inventory_but_restore_preserves_original_absence(workspace):
    root, source = workspace
    record = overlay.apply_overlay(root, source)
    assert (root / overlay.INVENTORY).is_file()
    overlay.restore_overlay(root, record["id"])
    assert not (root / overlay.INVENTORY).exists()


def test_dry_run_validates_and_reports_all_locks_without_creating_record(workspace):
    root, source = workspace
    before = fingerprints(root)
    result = overlay.apply_overlay(root, source, dry_run=True)
    assert result["status"] == "dry-run"
    assert result["affected"] == ["cce/common", "cce/serial"]
    assert not (root / ".cse-overlay").exists()
    assert fingerprints(root) == before


@pytest.mark.parametrize("kind", ["missing-patch", "syntax", "symlink", "existing-unreviewed-edit"])
def test_bad_correction_or_unreviewed_live_inputs_fail_before_copy(workspace, kind):
    root, source = workspace
    if kind == "missing-patch":
        (source / "fixed.patch").unlink()
    elif kind == "syntax":
        (source / "package.py").write_text("this is not python !!!")
    elif kind == "symlink":
        (source / "bad").symlink_to(root / "workspace-manifest.yaml")
    else:
        admit(root)
        (root / "package-repos/spack_repo/cse_trials/packages/tiny/package.py").write_text("# not reviewed\n")
    before = fingerprints(root)
    with pytest.raises((overlay.Error, ValueError)):
        overlay.apply_overlay(root, source)
    assert fingerprints(root) == before
    assert not (root / ".cse-overlay").exists()


@pytest.mark.parametrize("kind", ["provider-added", "provider-removed", "old-import", "new-import"])
def test_old_and_new_imports_and_provider_changes_broaden_impact(workspace, kind):
    root, source = workspace
    old = root / "package-repos/spack_repo/cse_trials/packages/tiny/package.py"
    if kind == "provider-added":
        (source / "package.py").write_text("provides('mpi')\n")
    elif kind == "provider-removed":
        old.write_text("provides('mpi')\n")
    elif kind == "old-import":
        old.write_text("import importlib\nimportlib.import_module('dynamic')\n")
    else:
        (source / "package.py").write_text("from spack_repo.other.packages.helper.package import Helper\n")
    record = overlay.apply_overlay(root, source)
    assert record["affected"] == ["cce/common", "cce/serial", "gcc/core"]


@pytest.mark.parametrize("failure_at", ["package", "inventory"])
def test_write_failure_rolls_back_bytes_and_mtimes_and_retains_record(workspace, monkeypatch, failure_at):
    root, source = workspace
    admit(root)
    before = fingerprints(root)
    replace = os.replace

    def failing(source_path, destination):
        if Path(source_path).parent.name == "stage" and Path(source_path).name == failure_at:
            raise OSError("injected replacement failure")
        return replace(source_path, destination)

    monkeypatch.setattr(os, "replace", failing)
    with pytest.raises(OSError, match="injected"):
        overlay.apply_overlay(root, source)
    assert fingerprints(root) == before
    assert overlay.records(root)[0]["status"] == "restored"


def test_interrupted_staging_record_is_recoverable_noop_and_blocks_other_work(workspace, monkeypatch):
    root, source = workspace
    record = overlay.apply_overlay(root, source)
    overlay.restore_overlay(root, record["id"])
    record["status"] = "preparing"
    overlay.save(root, record)
    with pytest.raises(overlay.Error, match="Incomplete"):
        overlay.apply_overlay(root, source)
    with pytest.raises(overlay.Error, match="Incomplete"):
        overlay.check_workspace(root, ["gcc/core"])
    assert overlay.restore_overlay(root, record["id"])["status"] == "restored"


@pytest.mark.parametrize("path", ["recipe", "inventory", "lock", "modules", "config"])
def test_restore_refuses_later_edits_without_overwriting_them(workspace, path):
    root, source = workspace
    record = overlay.apply_overlay(root, source)
    paths = {"recipe": record["target"] + "/package.py", "inventory": overlay.INVENTORY,
             "lock": "environments/cce/common/spack.lock", "modules": "modulefiles/cse/init-GCC",
             "config": "configs/common/config.yaml"}
    target = root / paths[path]
    target.write_bytes(target.read_bytes() + b"\n# later change\n")
    changed = fingerprints(root)
    with pytest.raises(overlay.Error, match="Later"):
        overlay.restore_overlay(root, record["id"])
    assert fingerprints(root) == changed


def test_only_explicitly_resolved_environment_can_build_and_later_lock_drift_blocks(workspace):
    root, source = workspace
    record = overlay.apply_overlay(root, source)
    with pytest.raises(overlay.Error, match="selected reconcretization"):
        overlay.check_workspace(root, ["cce/common"])
    assert overlay.check_workspace(root, ["cce/common"], "concretize")
    assert overlay.check_workspace(root, ["gcc/core"]) == []
    assert overlay.mark_resolved(root, "cce/common") == [record["id"]]
    assert overlay.check_workspace(root, ["cce/common"]) == []
    with pytest.raises(overlay.Error, match="selected reconcretization"):
        overlay.check_workspace(root, ["cce/serial"])
    lock = root / "environments/cce/common/spack.lock"
    lock.write_text(lock.read_text() + "\n")
    with pytest.raises(overlay.Error, match="selected reconcretization"):
        overlay.check_workspace(root, ["cce/common"])


def test_new_recipe_iteration_invalidates_previously_resolved_selected_environment(workspace):
    root, source = workspace
    first = overlay.apply_overlay(root, source)
    overlay.mark_resolved(root, "cce/common")
    (source / "fixed.patch").write_text("second correction\n")
    second = overlay.apply_overlay(root, source)
    assert first["id"] != second["id"]
    with pytest.raises(overlay.Error, match="selected reconcretization"):
        overlay.check_workspace(root, ["cce/common"])
    overlay.mark_resolved(root, "cce/common")
    assert overlay.check_workspace(root, ["cce/common"]) == []


def test_editor_uses_retained_copy_and_applies_only_after_exit(workspace, monkeypatch, tmp_path):
    root, _ = workspace
    editor = tmp_path / "edit.py"
    editor.write_text("from pathlib import Path\nimport sys\np=Path(sys.argv[1])\np.write_text(p.read_text()+'# edited locally\\n')\n")
    record = overlay.edit_overlay(root, "tiny", "cce/common", None,
                                  editor='"' + sys.executable + '" "' + str(editor) + '"')
    assert record["status"] == "applied"
    assert (root / record["target"] / "package.py").read_text().endswith("# edited locally\n")
    assert (root / ".cse-overlay" / record["id"] / "edit-original/tiny/old.patch").is_file()
    overlay.restore_overlay(root, record["id"])
    assert not (root / record["target"] / "package.py").read_text().endswith("# edited locally\n")


def test_cancelled_editor_does_not_change_live_workspace(workspace):
    root, _ = workspace
    before = fingerprints(root)
    record = overlay.edit_overlay(root, "tiny", "cce/common", None, editor="true")
    assert record["status"] == "cancelled"
    assert fingerprints(root) == before


def test_namespace_override_and_python36_cli(workspace):
    root, source = workspace
    repo = root / "package-repos/spack_repo"
    (repo / "cse_trials").rename(repo / "recovery")
    (repo / "recovery/repo.yaml").write_text("repo:\n  namespace: recovery\n  api: v2.0\n")
    (root / "configs/common/repos.yaml").write_text("repos:\n  recovery: ../../package-repos/spack_repo/recovery\n")
    command = [sys.executable, str(SCRIPT), "apply", "--workspace", str(root), "--repository", "recovery",
               "--from", str(source), "--environment", "cce/common"]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "./cse-build login concretize --environment cce/common --reconcretize" in result.stdout
    assert overlay.records(root)[0]["repository"] == "recovery"
    ast.parse(SCRIPT.read_text(), feature_version=(3, 6))


@pytest.mark.parametrize("changed_tag", [False, True])
def test_editor_copies_pinned_builtin_with_provenance_and_local_support(workspace, monkeypatch, tmp_path, changed_tag):
    root, _ = workspace
    builtin = tmp_path / "builtin"
    write(builtin / "packages/other/package.py", "class Other:\n    patch('upstream.patch')\n")
    write(builtin / "packages/other/upstream.patch", "keep support\n")
    config = root / "configs/common/repos.yaml"
    config.write_text(config.read_text() + "  builtin:\n    git: https://example.invalid/packages.git\n    tag: v-test\n")
    before = fingerprints(builtin)
    monkeypatch.setattr(overlay.recovery, "spack_identity", lambda path: {"commit": "pinned"})

    def output(command, **kwargs):
        if "--package-dir" in command:
            return str(builtin / "packages/other") + "\n"
        if "--repo" in command:
            return str(builtin) + "\n"
        assert command[:3] == ["git", "-C", str(builtin)]
        if command[3:] == ["rev-parse", "HEAD"]:
            return "reviewed-head\n"
        if command[3:] == ["rev-parse", "v-test^{commit}"]:
            return ("different-head" if changed_tag else "reviewed-head") + "\n"
        if command[3:] == ["remote", "get-url", "origin"]:
            return "https://example.invalid/packages.git\n"
        if command[3:] == ["status", "--porcelain", "--untracked-files=no"]:
            return ""
        raise AssertionError(command)

    monkeypatch.setattr(subprocess, "check_output", output)
    editor = tmp_path / "editor.py"
    editor.write_text("from pathlib import Path\nimport sys\np=Path(sys.argv[1]); p.write_text(p.read_text()+'# site fix\\n')\n")
    command = '"' + sys.executable + '" "' + str(editor) + '"'
    if changed_tag:
        with pytest.raises(overlay.Error, match="tag"):
            overlay.edit_overlay(root, "other", "gcc/core", "/pinned/spack", editor=command)
        assert not (root / ".cse-overlay").exists()
    else:
        record = overlay.edit_overlay(root, "other", "gcc/core", "/pinned/spack", editor=command)
        assert record["status"] == "applied"
        assert record["spack_identity"]["builtin"]["commit"] == "reviewed-head"
        assert (root / record["target"] / "upstream.patch").read_text() == "keep support\n"
        overlay.restore_overlay(root, record["id"])
        assert not (root / record["target"]).exists()
    assert fingerprints(builtin) == before


def test_missing_inventory_cannot_be_re_admitted_around_pending_build_gate(workspace):
    root, source = workspace
    overlay.apply_overlay(root, source)
    (root / overlay.INVENTORY).unlink()
    with pytest.raises(overlay.Error, match="disappeared"):
        overlay.mark_resolved(root, "cce/common")


def test_parallel_maintenance_operation_blocks_apply_without_recipe_changes(workspace):
    root, source = workspace
    before = fingerprints(root)
    with overlay.maintenance(root):
        environment = os.environ.copy()
        environment.pop("CSE_MAINTENANCE_LOCK_FD", None)
        result = subprocess.run([sys.executable, str(SCRIPT), "apply", "--workspace", str(root),
                                 "--from", str(source)], env=environment, capture_output=True, text=True)
    assert result.returncode != 0 and "another finite workspace operation" in result.stderr
    assert fingerprints(root) == before


def test_after_solve_previous_complete_package_can_be_applied_as_new_correction(workspace):
    root, source = workspace
    first = overlay.apply_overlay(root, source)
    lock = root / "environments/cce/common/spack.lock"
    lock.write_text(lock.read_text() + "\n")
    with pytest.raises(overlay.Error, match="new correction"):
        overlay.restore_overlay(root, first["id"])
    previous = root / ".cse-overlay" / first["id"] / "original/package"
    second = overlay.apply_overlay(root, previous, package="tiny", environment="cce/common")
    assert second["id"] != first["id"]
    assert (root / second["target"] / "package.py").read_text() == "class Tiny:\n    old = True\n"
    with pytest.raises(overlay.Error, match="selected reconcretization"):
        overlay.check_workspace(root, ["cce/common"])


@pytest.mark.parametrize("state", ["concretizing", "resuming", "concretize_failed", "resume_failed"])
def test_build_recovery_state_blocks_active_transition_but_allows_settled_correction(workspace, state):
    root, source = workspace
    record_path = root / ".cse-build-recovery/retained/recovery.json"
    manifest = root / "environments/cce/common/spack.yaml"
    lock = manifest.with_name("spack.lock")
    write(record_path.with_name("spack.yaml.before"), manifest.read_text())
    write(record_path.with_name("spack.lock.before"), lock.read_text())
    write(record_path, json.dumps({"tool": "workspace-build", "status": state,
                                  "action": "resume" if state.startswith("resume") else "concretize",
                                  "environment": "cce/common", "workspace": str(root),
                                  "selected_manifest": str(manifest.relative_to(root)),
                                  "selected_lock": str(lock.relative_to(root)), "lock_existed": True,
                                  "manifest_before_sha256": overlay.fingerprint(manifest),
                                  "lock_before_sha256": overlay.fingerprint(lock),
                                  "rollback_completed": 1.0,
                                  "rollback_manifest_sha256": overlay.fingerprint(manifest),
                                  "rollback_lock_sha256": overlay.fingerprint(lock), "commands": []}))
    before = fingerprints(root)
    if state in ("concretizing", "resuming"):
        with pytest.raises(ValueError, match="unfinished workspace build"):
            overlay.apply_overlay(root, source)
        assert fingerprints(root) == before
    else:
        assert overlay.apply_overlay(root, source)["status"] == "applied"
