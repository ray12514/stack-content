"""Exercise startup refresh through the real Composer CLI and pilot templates."""
from __future__ import annotations

import json
import grp
import os
from pathlib import Path
import pwd
import subprocess
import sys

import pytest
import yaml

pytest.importorskip("stack_composer")

PILOT = Path(__file__).resolve().parents[1]
REFRESH = PILOT / "scripts/refresh-workspace-controls.py"
STARTUP_FILES = {
    "cse-build", "env/share-generated-permissions.sh", "env/workspace-shell.rc",
    "env/setup-build-env.sh", "scripts/verify-overlay-inputs.py",
    "scripts/verify-workspace-inputs.py", "scripts/workspace-build.py",
    "scripts/workspace-overlay.py", "scripts/overlay-recovery.py", "scripts/module-preview.py",
    "scripts/workspace-permissions.py", "BUILDER-HANDOFF.md",
}


def yaml_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def make_workspace(tmp_path, values=None):
    values = values or yaml.safe_load((PILOT / "site-values.example.yaml").read_text())
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


def test_startup_refresh_prepares_missing_helpers_together(tmp_path):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    tag_only_values(recorded, values)
    required = [
        "scripts/verify-overlay-inputs.py", "package-repos/overlay-inventory.json",
        "scripts/overlay-recovery.py", "scripts/workspace-overlay.py",
        "scripts/workspace-build.py", "scripts/module-preview.py",
    ]
    for name in required:
        (workspace / name).unlink()
    # The update must inventory these exact existing bytes, not the latest
    # authored overlay or its precomputed inventory.
    recipe = workspace / "package-repos/spack_repo/cse_trials/packages/cce/package.py"
    recipe.write_text(recipe.read_text() + "\n# Existing site recipe adjustment\n")
    before = snapshot([path for path in workspace.rglob("*") if path.is_file()])
    preview = refresh(workspace, recorded, composer, "--dry-run")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert snapshot(before) == before
    assert all(not (workspace / name).exists() for name in required)
    result = refresh(workspace, recorded, composer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all((workspace / name).is_file() for name in required)
    protected = {path: state for path, state in before.items()
                 if str(path.relative_to(workspace)) not in STARTUP_FILES}
    assert snapshot(protected) == protected
    result = subprocess.run([sys.executable, str(workspace / "scripts/verify-overlay-inputs.py")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_startup_refresh_does_not_rebaseline_an_existing_inventory(tmp_path):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    tag_only_values(recorded, values)
    recipe = workspace / "package-repos/spack_repo/cse_trials/packages/cce/package.py"
    recipe.write_text(recipe.read_text() + "\n# Unrecorded edit\n")
    before = snapshot([path for path in workspace.rglob("*") if path.is_file()])
    result = refresh(workspace, recorded, composer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "overlay input changed" in result.stderr
    assert "keeping the existing overlay inventory unchanged" in result.stderr
    protected = {path: state for path, state in before.items()
                 if str(path.relative_to(workspace)) not in STARTUP_FILES}
    assert snapshot(protected) == protected


def runtime_fixture(tmp_path, request):
    """Use a real pinned Git checkout and real shell/helpers; stub Spack only."""
    values = yaml.safe_load((PILOT / "site-values.example.yaml").read_text())
    spack = tmp_path / "spack"
    (spack / "bin").mkdir(parents=True)
    (spack / "share/spack").mkdir(parents=True)
    executable = spack / "bin/spack"
    executable.write_text('''#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$CSE_TEST_TRACE"
if [ "$1" = --version ]; then
  printf '1.2.2\\n'
elif [ "$1" = python ]; then
  shift
  exec python3 "$@"
elif [ "$1" = -e ] && [ "$3" = config ]; then
  printf 'workspace include active %s/configs/common\\n' "$CSE_BUILD_WORKSPACE"
fi
''')
    executable.chmod(0o750)
    (spack / "share/spack/setup-env.sh").write_text('export PATH="$SPACK_ROOT/bin:$PATH"\n')
    def git(*args):
        return subprocess.run(["git", "-C", str(spack), *args], text=True, capture_output=True, check=True).stdout.strip()
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Ravon Venters", "-c", "user.email=ray12514@gmail.com", "commit", "-qm", "fixture")
    git("tag", "v1.2.2")
    git("remote", "add", "origin", "https://example.invalid/spack.git")
    values["spack"].update(source="https://example.invalid/spack.git", commit=git("rev-parse", "HEAD"),
                           shared_root=str(spack), initial_root=str(spack), default_mode="shared")
    def unlock_fixture():
        for path in [spack, *spack.rglob("*")]:
            if path.is_dir():
                path.chmod(0o700)
    request.addfinalizer(unlock_fixture)
    for path in [*spack.rglob("*"), spack]:
        path.chmod(0o550 if path.is_dir() or os.access(path, os.X_OK) else 0o440)
    values["permissions"]["group"] = grp.getgrgid(os.getgid()).gr_name
    for name in values["paths"]:
        values["paths"][name] = str(tmp_path / name)
    values["buildcache"]["url"] = (tmp_path / "buildcache").as_uri()
    for context in values["build"]["contexts"].values():
        context["stages"] = [str(tmp_path / "stage")]
    for directory in (tmp_path / "home", tmp_path / "work", tmp_path / "stage"):
        directory.mkdir()
    environment = dict(os.environ, HOME=str(tmp_path / "home"), WORKDIR=str(tmp_path / "work"),
                       USER=pwd.getpwuid(os.getuid()).pw_name, PYTHONDONTWRITEBYTECODE="1",
                       PATH=str(Path(sys.executable).parent) + ":/usr/bin:/bin:/usr/sbin:/sbin",
                       CSE_TEST_TRACE=str(tmp_path / "spack-trace"), CSE_PERMISSION_JOBS="1")
    environment.pop("SPACK_ENV", None)
    environment.pop("CSE_MAINTENANCE_LOCK_FD", None)
    return values, environment


def test_updated_older_workspace_enters_shell_runs_status_and_restores(tmp_path, request):
    values, environment = runtime_fixture(tmp_path, request)
    workspace, recorded, composer, values = make_workspace(tmp_path, values)
    tag_only_values(recorded, values)
    missing = [name for name in STARTUP_FILES if name.startswith("scripts/")]
    missing.append("package-repos/overlay-inventory.json")
    for name in missing:
        (workspace / name).unlink()
    config = workspace / "configs/common/config.yaml"
    config.write_text(config.read_text().replace("${SPACK_MISC_CACHE_PATH}", values["paths"]["misc_cache"]))
    full_policy = workspace / "scripts/verify-lockfiles.py"
    full_policy.write_text('''from pathlib import Path
def main():
    raise RuntimeError("The full lock verifier must not run during startup/status")
if __name__ == "__main__":
    main()
''')
    # Exercise an older setup helper that overrides the misc cache variable.
    setup = workspace / "env/setup-build-env.sh"
    setup.write_text(setup.read_text() + '\nexport SPACK_MISC_CACHE_PATH="/obsolete-cache"\n')
    for manifest in sorted((workspace / "environments").rglob("spack.yaml"))[:3]:
        lock = manifest.with_suffix(".lock")
        lock.write_text('{"locked": "existing partial build"}\n')
        lock.chmod(0o660)
    installed = Path(values["paths"]["install_tree"]) / "gcc/existing-hash/lib.so"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"existing compiled package")
    installed.chmod(0o600)
    installed_before = snapshot([installed])
    before = snapshot([path for path in workspace.rglob("*") if path.is_file()])
    result = refresh(workspace, recorded, composer, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(before) == before
    result = refresh(workspace, recorded, composer)
    assert result.returncode == 0, result.stdout + result.stderr
    expected_config = before[config][0].decode().replace(values["paths"]["misc_cache"], "${SPACK_MISC_CACHE_PATH}")
    assert config.read_text() == expected_config
    assert full_policy.read_bytes() == before[full_policy][0]
    for action in ("permissions", "status", "shell", None):
        command = ["bash", str(workspace / "cse-build"), "login"] + ([action] if action else [])
        result = subprocess.run(command,
                                env=dict(environment, TMUX="test-session"), input="printf 'CSE_READY:%s\\n' \"$SPACK_MISC_CACHE_PATH\"\nexit\n",
                                capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stdout + result.stderr
        if action in ("shell", None):
            assert "CSE_READY:" + values["paths"]["misc_cache"] + "/" in result.stdout
            assert "/obsolete-cache" not in result.stdout
    assert "verify-workspace-inputs.py" in (tmp_path / "spack-trace").read_text()
    assert snapshot(installed_before) == installed_before
    record = next((workspace / ".cse-control-refresh").glob("*/record.json"))
    result = refresh(workspace, recorded, composer, "--restore-from", str(record))
    assert result.returncode == 0, result.stdout + result.stderr
    assert config.read_bytes() == before[config][0]
    assert all(not (workspace / name).exists() for name in missing)
    assert full_policy.read_bytes() == before[full_policy][0]


def test_input_preflight_honors_recorded_checks_without_running_full_verifier(tmp_path):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    policy = workspace / "scripts/verify-lockfiles.py"
    policy.write_text('''def workspace_input_errors():
    return ["recorded policy rejected an input"]
if __name__ == "__main__":
    raise RuntimeError("full lock verification was invoked")
''')
    result = subprocess.run([sys.executable, str(workspace / "scripts/verify-workspace-inputs.py")],
                            text=True, capture_output=True)
    assert result.returncode == 1
    assert "recorded policy rejected an input" in result.stderr
    assert "full lock verification was invoked" not in result.stderr


@pytest.mark.parametrize("field,value", [
    (("architecture", "target"), "x86_64"),
    (("shared", "compiler", "name"), "different-compiler"),
    (("platform", "mpi", "name"), "different-mpi"),
    (("build_jobs",), 123),
])
def test_startup_refresh_keeps_recorded_setup_identity(tmp_path, field, value):
    workspace, recorded, composer, values = make_workspace(tmp_path)
    mapping = values
    for name in field[:-1]:
        mapping = mapping[name]
    mapping[field[-1]] = value
    yaml_file(recorded, values)
    before = snapshot([path for path in workspace.rglob("*") if path.is_file()])
    result = refresh(workspace, recorded, composer)
    assert result.returncode != 0
    assert "startup refresh would change recorded setup identity" in result.stderr
    assert snapshot(before) == before


@pytest.mark.parametrize("action", ["shell", "permissions", "login"])
def test_overlay_drift_does_not_lock_out_inspection_or_permission_repair(tmp_path, request, action):
    values, environment = runtime_fixture(tmp_path, request)
    workspace, recorded, composer, values = make_workspace(tmp_path, values)
    package = workspace / "package-repos/spack_repo/cse_trials/packages/netlib_lapack"
    package.mkdir()
    recipe = package / "package.py"
    recipe.write_text("class NetlibLapack:\n    pass\n")
    patch = package / "previous.patch"
    patch.write_text("previous support file\n")
    candidate = tmp_path / "recorded-inventory.json"
    result = subprocess.run([sys.executable, str(workspace / "scripts/verify-overlay-inputs.py"),
                             "--candidate", str(candidate)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    inventory = workspace / "package-repos/overlay-inventory.json"
    inventory.write_bytes(candidate.read_bytes())
    recipe.write_text(recipe.read_text() + "\n# Teammate's CCE recipe edit\n")
    patch.unlink()
    before = {path: path.read_bytes() for path in (inventory, recipe)}
    command = ["bash", str(workspace / "cse-build"), "login"] + ([] if action == "login" else [action])
    result = subprocess.run(command, env=dict(environment, TMUX="test-session"),
                            input="printf 'CSE_INSPECTION_READY\\n'\nexit\n",
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "overlay input changed" in result.stderr
    assert "overlay input missing" in result.stderr
    if action != "permissions":
        assert "CSE_INSPECTION_READY" in result.stdout
    assert {path: path.read_bytes() for path in before} == before
    result = subprocess.run(["bash", str(workspace / "cse-build"), "compute", "install"],
                            env=dict(environment, CSE_OVERLAY_ALLOW_UNVERIFIED="1"),
                            capture_output=True, text=True, timeout=45)
    assert result.returncode != 0
    assert "overlay input changed" in result.stderr


@pytest.mark.parametrize("gsl_recorded", [False, True])
def test_refresh_and_launcher_register_intentional_netlib_and_gsl_overlays(tmp_path, request, gsl_recorded):
    values, environment = runtime_fixture(tmp_path, request)
    workspace, recorded, composer, values = make_workspace(tmp_path, values)
    tag_only_values(recorded, values)
    packages = workspace / "package-repos/spack_repo/cse_trials/packages"
    gsl = packages / "gsl/package.py"
    gsl.parent.mkdir()
    gsl.write_text("class Gsl:\n    pass\n")
    inventory = workspace / "package-repos/overlay-inventory.json"
    if gsl_recorded:
        candidate = tmp_path / "with-gsl.json"
        result = subprocess.run([sys.executable, str(workspace / "scripts/verify-overlay-inputs.py"),
                                 "--candidate", str(candidate)], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        inventory.write_bytes(candidate.read_bytes())
    netlib = packages / "netlib_lapack/package.py"
    netlib.parent.mkdir()
    netlib.write_text("class NetlibLapack:\n    patch('cce.patch')\n")
    (netlib.parent / "cce.patch").write_text("intentional CCE patch\n")
    # The control refresh must deliver the repair command through the very drift
    # that prevented entry. It may not silently adopt either recipe.
    before = {path: path.read_bytes() for path in (inventory, gsl, netlib, netlib.parent / "cce.patch")}
    result = refresh(workspace, recorded, composer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert {path: path.read_bytes() for path in before} == before
    base = ["bash", str(workspace / "cse-build"), "login"]
    reconcile = base + ["overlay", "reconcile", "--package", "netlib-lapack", "--package", "gsl"]
    result = subprocess.run(reconcile + ["--dry-run"], env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "netlib-lapack: new" in result.stdout
    assert ("gsl: already-recorded" if gsl_recorded else "gsl: new") in result.stdout
    assert {path: path.read_bytes() for path in before} == before
    assert not (workspace / ".cse-overlay").exists()
    result = subprocess.run(reconcile, env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert inventory.read_bytes() != before[inventory]
    assert {path: path.read_bytes() for path in before if path != inventory} == {
        path: state for path, state in before.items() if path != inventory}
    result = subprocess.run(base + ["status"], env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    record = next((workspace / ".cse-overlay").glob("*/record.json"))
    result = subprocess.run(base + ["overlay", "restore", "--record", record.parent.name],
                            env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert {path: path.read_bytes() for path in before} == before
