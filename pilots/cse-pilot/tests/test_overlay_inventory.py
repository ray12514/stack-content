"""Exercise the shipped verifier and operator commands in disposable workspaces."""

import json
import grp
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


PILOT = Path(__file__).resolve().parents[1]
TEMPLATES = PILOT / "templates"


@pytest.fixture
def workspace(tmp_path):
    destination = tmp_path / "workspace"
    values = yaml.safe_load((PILOT / "site-values.example.yaml").read_text())
    values["permissions"]["group"] = grp.getgrgid(os.getgid()).gr_name
    values["paths"]["misc_cache"] = str(tmp_path / "misc-cache")
    roster = yaml.safe_load((PILOT / "roster.yaml").read_text())
    engine = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                         undefined=StrictUndefined, keep_trailing_newline=True)
    engine.filters["yaml_scalar"] = json.dumps
    engine.filters["yaml_flow"] = json.dumps
    context = {"values": values, "data": {"roster": roster}}
    for source in TEMPLATES.rglob("*"):
        if not source.is_file() or "_partials" in source.parts:
            continue
        relative = source.relative_to(TEMPLATES).as_posix()
        rendered_path = engine.from_string(relative).render(**context)
        target = destination / rendered_path.removesuffix(".j2")
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith(".j2"):
            target.write_text(engine.get_template(relative).render(**context))
        else:
            shutil.copyfile(source, target)
    return destination


def verify(workspace):
    return subprocess.run([sys.executable, str(workspace / "scripts/verify-lockfiles.py"),
                           "--workspace-only"], capture_output=True, text=True)


def inventory_command(workspace, *arguments):
    return subprocess.run([sys.executable, str(workspace / "scripts/verify-overlay-inputs.py"),
                           *map(str, arguments)], capture_output=True, text=True)


@pytest.mark.parametrize("package", ["cce", "cmake", "dakota", "hdf5", "ncurses", "zlib"])
def test_workspace_gate_detects_a_changed_recipe(workspace, package):
    current = verify(workspace)
    assert current.returncode == 0, current.stderr
    recipe = workspace / "package-repos/spack_repo/cse_trials/packages" / package / "package.py"
    recipe.write_text(recipe.read_text() + "\n# an unreviewed edit\n")
    changed = verify(workspace)
    assert changed.returncode == 1
    assert "changed" in changed.stderr and package + "/package.py" in changed.stderr


@pytest.mark.parametrize("change,diagnostic", [
    ("missing", "missing"),
    ("new-package", "unrecorded"),
    ("symlink", "symlink"),
    ("path-escape", "unsafe"),
    ("missing-inventory", "unsupported overlay identity"),
    ("missing-helper", "unsupported overlay identity"),
    ("empty-inventory", "incomplete"),
    ("wrong-namespace", "identity"),
])
def test_workspace_gate_rejects_incomplete_or_unrecorded_identity(workspace, change, diagnostic):
    root = workspace / "package-repos"
    recipe = root / "spack_repo/cse_trials/packages/cce/package.py"
    manifest = root / "overlay-inventory.json"
    if change == "missing":
        recipe.unlink()
    elif change == "new-package":
        added = recipe.parent.parent / "new_package/package.py"
        added.parent.mkdir()
        added.write_text("# an unrecorded package\n")
    elif change == "symlink":
        outside = workspace / "outside.py"
        outside.write_bytes(recipe.read_bytes())
        recipe.unlink()
        recipe.symlink_to(outside)
    elif change == "missing-inventory":
        manifest.unlink()
    elif change == "missing-helper":
        (workspace / "scripts/verify-overlay-inputs.py").unlink()
    else:
        data = json.loads(manifest.read_text())
        if change == "path-escape":
            data["repositories"][0]["files"]["../../../outside.py"] = "0" * 64
        elif change == "empty-inventory":
            data["repositories"] = []
        else:
            data["repositories"][0]["namespace"] = "wrong_namespace"
        manifest.write_text(json.dumps(data))
    result = verify(workspace)
    assert result.returncode == 1
    assert diagnostic in result.stderr


def test_operator_can_review_a_candidate_before_explicit_adoption(workspace, tmp_path):
    manifest = workspace / "package-repos/overlay-inventory.json"
    original = manifest.read_bytes()
    package = workspace / "package-repos/spack_repo/cse_trials/packages/new_package"
    package.mkdir()
    (package / "package.py").write_text('from spack.package import *\nclass NewPackage(Package):\n    patch("fix.patch")\n')
    (package / "fix.patch").write_text("a local support file\n")
    candidate = tmp_path / "candidate.json"
    result = inventory_command(workspace, "--candidate", candidate)
    assert result.returncode == 0, result.stderr
    assert "review" in result.stdout.lower()
    assert manifest.read_bytes() == original
    assert verify(workspace).returncode == 1
    shutil.copyfile(candidate, manifest)
    assert verify(workspace).returncode == 0
    refused = inventory_command(workspace, "--candidate", manifest)
    assert refused.returncode == 1
    assert "outside" in refused.stderr


@pytest.mark.parametrize("reference,diagnostic", [
    ('"missing.patch"', "local support file missing"),
    ('"../../../../outside.patch"', "unsafe"),
    ('computed_name', "dynamic patch"),
])
def test_candidate_requires_complete_static_local_support(workspace, tmp_path, reference, diagnostic):
    recipe = workspace / "package-repos/spack_repo/cse_trials/packages/cmake/package.py"
    recipe.write_text(recipe.read_text() + "\npatch({})\n".format(reference))
    candidate = tmp_path / "candidate.json"
    result = inventory_command(workspace, "--candidate", candidate)
    assert result.returncode == 1
    assert diagnostic in result.stderr
    assert not candidate.exists()


def test_new_workspace_pins_builtin_to_the_admitted_commit(workspace):
    config = yaml.safe_load((workspace / "configs/common/repos.yaml").read_text())
    assert list(config["repos"]) == ["cse_trials", "builtin"]
    assert config["repos"]["builtin"] == {
        "git": "https://github.com/spack/spack-packages.git",
        "commit": "d4f7c711a6a42f1c4d551c8fd10fce9a11340a81",
    }


def test_prepared_shell_scopes_cache_to_workspace_and_reviewed_overlay_identity(workspace, tmp_path):
    def shell_cache(candidate):
        environment = dict(os.environ, WORKDIR=str(tmp_path), CSE_NODE_CONTEXT="login",
                           CSE_BUILD_NODE_TYPE="login", CSE_BUILD_STAGE=str(tmp_path),
                           CSE_BUILD_WORKSPACE=str(candidate))
        result = subprocess.run(
            ["bash", "-c", 'set -e; source "$CSE_BUILD_WORKSPACE/env/setup-build-env.sh"; '
             'printf "%s\\n" "$SPACK_MISC_CACHE_PATH"'],
            env=environment, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    first = shell_cache(workspace)
    assert first.startswith(str(tmp_path / "misc-cache") + "/")
    assert first == shell_cache(workspace)
    old_cache = Path(first)
    old_cache.mkdir(parents=True)
    sentinel = old_cache / "retain-old-index.json"
    sentinel.write_text("retained old cache\n")
    moved = tmp_path / "moved-workspace"
    shutil.copytree(workspace, moved)
    assert shell_cache(moved) != first
    recipe = workspace / "package-repos/spack_repo/cse_trials/packages/cmake/package.py"
    recipe.write_text(recipe.read_text() + "\n# reviewed next candidate\n")
    candidate = tmp_path / "reviewed-next-inventory.json"
    result = inventory_command(workspace, "--candidate", candidate)
    assert result.returncode == 0, result.stderr
    shutil.copyfile(candidate, workspace / "package-repos/overlay-inventory.json")
    assert shell_cache(workspace) != first
    assert sentinel.read_text() == "retained old cache\n"


def test_lock_reader_accepts_pinned_spack_122_format(workspace, tmp_path):
    import runpy
    reader = runpy.run_path(str(workspace / 'scripts/verify-lockfiles.py'))['load_lock']
    lock = tmp_path / 'spack.lock'
    document = {'_meta': {'file-type': 'spack-lockfile', 'lockfile-version': 6,
                           'specfile-version': 5},
                'roots': [], 'concrete_specs': {}}
    lock.write_text(json.dumps(document))
    assert reader(lock) == (document, {})
    document['_meta']['lockfile-version'] = 999
    lock.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='lockfile version 6'):
        reader(lock)
