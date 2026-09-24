from __future__ import annotations

import ast
import grp
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from test_toolchain_templates import TEMPLATE_ROOT, SITE_VALUES_PATH, render_text
import yaml

HELPER = TEMPLATE_ROOT / "scripts/workspace-permissions.py"


def test_prepared_shell_does_not_walk_generated_trees(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "env").mkdir(parents=True)
    (workspace / "scripts").mkdir()
    spack = tmp_path / "spack"
    (spack / "share/spack").mkdir(parents=True)
    (spack / "share/spack/setup-env.sh").write_text("")
    (workspace / "env/setup-build-env.sh").write_text("")
    values = yaml.safe_load(SITE_VALUES_PATH.read_text())
    for name in ("workspace-shell.rc", "share-generated-permissions.sh"):
        (workspace / "env" / name).write_text(render_text("env/" + name + ".j2", values=values))
    if HELPER.exists():
        shutil.copyfile(HELPER, workspace / "scripts/workspace-permissions.py")
    roots = {name: str(tmp_path / name) for name in (
        "CSE_INSTALL_TREE_ROOT", "CSE_SHARED_SOURCE_CACHE_ROOT", "CSE_SHARED_MISC_CACHE_ROOT",
        "CSE_VIEWS_ROOT", "CSE_MODULES_ROOT", "CSE_BUILDCACHE_ROOT",
    )}
    for path in roots.values():
        Path(path).mkdir()
        Path(path).chmod(0o2770)
    private_file = Path(roots["CSE_SHARED_SOURCE_CACHE_ROOT"]) / "generated.json"
    private_file.write_text("{}")
    private_file.chmod(0o600)
    env = dict(os.environ, **roots, CSE_BUILD_WORKSPACE=str(workspace), SPACK_ROOT=str(spack),
               SPACK_MISC_CACHE_PATH=roots["CSE_SHARED_MISC_CACHE_ROOT"] + "/builder",
               CSE_GROUP=grp.getgrgid(os.getgid()).gr_name, CSE_NODE_CONTEXT="login",
               CSE_BUILD_NODE_TYPE="login", CSE_BUILD_STAGE=str(tmp_path / "stage"), CSE_PERMISSION_JOBS="1")
    result = subprocess.run(["bash", "--noprofile", "--rcfile", str(workspace / "env/workspace-shell.rc"),
                             "-i", "-c", "exit"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(private_file.stat().st_mode) == 0o600, "shell startup/exit traversed and repaired descendants"


def run_permissions(root, *args, mode="handoff", jobs=1):
    return subprocess.run([sys.executable, str(HELPER), "--mode", mode,
                           "--group", grp.getgrgid(os.getgid()).gr_name,
                           "--jobs", str(jobs), "--tree", str(root), *map(str, args)],
                          capture_output=True, text=True)


@pytest.mark.parametrize("jobs", [1, 4, 16, 32])
def test_repair_recovers_traversal_preserves_exec_and_skips_links(tmp_path, jobs):
    root = tmp_path / "generated"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private")
    outside.chmod(0o600)
    for i in range(20):
        child = root / str(i)
        child.mkdir()
        (child / "data").write_text("data")
        (child / "data").chmod(0o600)
        (child / "run").write_text("exec")
        (child / "run").chmod(0o700)
        child.chmod(0o660)
    plain = root / "at-root"
    plain.write_text("root file")
    plain.chmod(0o600)
    (root / "link").symlink_to(outside)
    result = run_permissions(root, jobs=jobs)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(plain.stat().st_mode) == 0o660
    for i in range(20):
        child = root / str(i)
        assert stat.S_IMODE(child.stat().st_mode) in (0o770, 0o2770)
        assert stat.S_IMODE((child / "data").stat().st_mode) == 0o660
        assert stat.S_IMODE((child / "run").stat().st_mode) == 0o770
    assert stat.S_IMODE(outside.stat().st_mode) == 0o600
    again = run_permissions(root, jobs=jobs)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["changed"] == 0
    assert json.loads(again.stdout)["visited"] == 62


def test_roots_only_and_install_prefix_exclusion(tmp_path):
    root = tmp_path / "workspace"
    store = root / "store"
    prefix = store / "gcc/hash"
    prefix.mkdir(parents=True)
    artifact = prefix / "library"
    artifact.write_text("installed")
    artifact.chmod(0o600)
    result = run_permissions(root, "--root", store, "--exclude-tree", store, mode="roots")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["visited"] == 2
    result = run_permissions(root, "--root", store, "--exclude-tree", store)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600


def test_overlapping_roots_are_scanned_once(tmp_path):
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "data").write_text("x")
    result = run_permissions(root, "--tree", nested, "--root", root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["visited"] == 3


def test_verify_is_read_only_and_reports_bad_modes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    result = run_permissions(root, mode="verify", jobs=4)
    assert result.returncode != 0
    assert "restricted group contract" in result.stderr
    assert stat.S_IMODE(root.stat().st_mode) == 0o755


def test_refuses_symlink_root_and_bad_job_count(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    link = tmp_path / "link"
    link.symlink_to(root)
    for bad in (link, link / "missing"):
        result = run_permissions(bad)
        assert result.returncode != 0
        assert "symlink" in result.stderr
    for jobs in (0, 33):
        assert run_permissions(root, jobs=jobs).returncode != 0


def test_missing_optional_roots_and_python36_syntax(tmp_path):
    result = run_permissions(tmp_path / "missing")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["visited"] == 0
    ast.parse(HELPER.read_text(), feature_version=(3, 6))


def load_helper():
    spec = importlib.util.spec_from_file_location("cse_workspace_permissions", HELPER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_foreign_owned_entries_are_reported_without_mutation(tmp_path, monkeypatch):
    helper = load_helper()
    path = tmp_path / "private"
    path.write_text("private")
    path.chmod(0o600)
    def no_mutation(*args, **kwargs):
        pytest.fail("attempted to change another builder's entry")
    monkeypatch.setattr(helper.os, "chmod", no_mutation)
    monkeypatch.setattr(helper.os, "chown", no_mutation)
    for mode in ("repair", "handoff"):
        result = helper.counters()
        helper.inspect_entry(str(path), path.stat(),
                             {"uid": os.getuid() + 1, "gid": os.getgid(), "mode": mode}, result)
        assert result["changed"] == 0
        assert result["failures"] == (1 if mode == "handoff" else 0)


def test_filesystem_boundary_is_not_mutated(tmp_path):
    helper = load_helper()
    before = tmp_path.stat().st_mode
    result, children = helper.scan_directory((str(tmp_path), tmp_path.stat().st_dev + 1), {})
    assert result["mounts"] == 1
    assert result["visited"] == 0
    assert children == []
    assert tmp_path.stat().st_mode == before


def test_worker_death_fails_instead_of_reporting_success(tmp_path, monkeypatch):
    from concurrent.futures.process import BrokenProcessPool
    helper = load_helper()
    root = tmp_path / "root"
    root.mkdir()
    for name in ("crash", "other"):
        (root / name).mkdir()
    scan = helper.scan_directory
    def crash(task, options):
        if Path(task[0]).name == "crash":
            os._exit(9)
        return scan(task, options)
    monkeypatch.setattr(helper, "scan_directory", crash)
    with pytest.raises(BrokenProcessPool):
        helper.maintain([str(root)], [], [], grp.getgrgid(os.getgid()).gr_name, "handoff", 2)


def test_cache_creation_refuses_symlink_ancestor_before_writing(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "redirect").symlink_to(outside)
    result = run_permissions(root, "--root", root / "redirect/new",
                             "--create-root", root / "redirect/new", mode="roots")
    assert result.returncode != 0
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("role,write", [("publish", "group"), ("build", "user")])
def test_permissions_action_rejects_nonrestricted_workspaces(tmp_path, role, write):
    values = yaml.safe_load(SITE_VALUES_PATH.read_text())
    values["workspace"]["role"] = role
    values["permissions"]["write"] = write
    launcher = tmp_path / "cse-build"
    launcher.write_text(render_text("cse-build.j2", values=values))
    result = subprocess.run(["bash", str(launcher), "login", "permissions"],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert "permissions" in result.stderr
    assert "workspace" in result.stderr
