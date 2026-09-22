import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


PILOT = Path(__file__).resolve().parents[1]
HELPER = PILOT / "templates" / "scripts" / "workspace-build.py"
SPEC = importlib.util.spec_from_file_location("workspace_build", HELPER)
WORKSPACE_BUILD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(WORKSPACE_BUILD)
OLD = "a" * 32
NEW = "b" * 32
OTHER = "c" * 32


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def lock(package, hash_value):
    return {
        "_meta": {
            "file-type": "spack-lockfile",
            "lockfile-version": 6,
            "specfile-version": 5,
        },
        "roots": [{"hash": hash_value, "spec": package}],
        "concrete_specs": {
            hash_value: {
                "name": package,
                "version": "1.0",
                "parameters": {},
                "arch": {"platform": "linux", "target": "x86_64_v3"},
            }
        },
    }


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    write(root / "configs/common/config.yaml", "config:\n  misc_cache: /shared/literal-cache\n")
    write(
        root / "configs/common/repos.yaml",
        "repos:\n  cse_trials: ../../package-repos/spack_repo/cse_trials\n",
    )
    write(
        root / "package-repos/spack_repo/cse_trials/repo.yaml",
        "repo:\n  namespace: cse_trials\n  api: v2.0\n",
    )
    write(
        root / "package-repos/spack_repo/cse_trials/packages/tiny/package.py",
        "class Tiny:\n    pass\n",
    )
    for environment, package, hash_value in (
        ("cce/common", "tiny", OLD),
        ("gcc/common", "other", OTHER),
    ):
        env = root / "environments" / environment
        manifest = {
            "spack": {
                "include:": ["../../../configs/common"],
                "specs": [package],
                "view": {"default": {"root": "/live/views/" + environment}},
                "modules:": {"default": {"enable": ["tcl"]}},
            }
        }
        write(env / "spack.yaml", yaml.safe_dump(manifest, sort_keys=False))
        write(env / "spack.lock", json.dumps(lock(package, hash_value)))

    spack = tmp_path / "spack" / "bin" / "spack"
    write(
        spack,
        "#!" + sys.executable + "\n" + r'''
import json, os, pathlib, sys, yaml
args = sys.argv[1:]
if args == ['--version']:
    print('1.2.2'); raise SystemExit(0)
record_dir = pathlib.Path.cwd()
record = json.loads((record_dir / 'recovery.json').read_text())
env = pathlib.Path(args[1])
action = args[2]
manifest = yaml.safe_load((env / 'spack.yaml').read_text())['spack']
module_key = next((key for key in manifest if key.rstrip(':') == 'modules'), None)
if manifest.get('view') is not False or module_key is None or manifest[module_key]['default']['enable'] != []:
    raise SystemExit('environment was not isolated from views/modules')
config_key = next((key for key in manifest if key.rstrip(':') == 'config'), None)
if config_key is None or manifest[config_key].get('misc_cache') != str(record_dir / 'state' / 'misc'):
    raise SystemExit('environment misc cache was not isolated')
with (record_dir / 'fake-actions.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\n')
if action == 'python':
    current = manifest['specs']
    locked = [item['spec'] for item in json.loads((env / 'spack.lock').read_text())['roots']]
    missing = [spec for spec in current if spec not in locked]
    stale = [spec for spec in locked if spec not in current]
    print('CSE_ROOT_CHECK=' + json.dumps({
        'current_not_locked': missing, 'locked_not_current': stale}))
elif action == 'concretize':
    path = env / 'spack.lock'
    data = json.loads(path.read_text())
    if os.environ.get('FAIL_CONCRETIZE'):
        path.write_text('partial lock')
        raise SystemExit(1)
    if 'a' * 32 in data['concrete_specs']:
        data['concrete_specs']['b' * 32] = data['concrete_specs'].pop('a' * 32)
        data['roots'][0]['hash'] = 'b' * 32
    data['roots'][0]['spec'] = manifest['specs'][0]
    path.write_text(json.dumps(data))
elif action == 'install':
    if os.environ.get('FAIL_RESUME'):
        raise SystemExit(1)
    (record_dir / 'installed').write_text(str(env))
else:
    raise SystemExit('unexpected action: ' + repr(args))
''',
    )
    spack.chmod(0o755)
    fake_bin = tmp_path / "test-bin"
    write(fake_bin / "ps", "#!/bin/sh\nexit 0\n")
    (fake_bin / "ps").chmod(0o755)
    repository = spack.parent.parent
    for arguments in (
        ("init", "-q"),
        ("remote", "add", "origin", "https://example.invalid/spack.git"),
        ("add", "."),
        ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"),
    ):
        subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
    return root, spack


def cli(workspace, action, *arguments, extra_env=None):
    root, spack = workspace
    command = [
        sys.executable,
        str(HELPER),
        action,
        "--workspace",
        str(root),
    ]
    if action in ("concretize", "resume"):
        command += ["--environment", "cce/common", "--spack", str(spack)]
    environment = os.environ.copy()
    environment.pop(WORKSPACE_BUILD.LOCK_FD_ENV, None)
    environment["PATH"] = str(root.parent / "test-bin") + os.pathsep + environment.get("PATH", "")
    environment.update(extra_env or {})
    return subprocess.run(command + list(arguments), env=environment, capture_output=True, text=True)


def fingerprint(root):
    ignored = {WORKSPACE_BUILD.LOCK_NAME, WORKSPACE_BUILD.RECOVERY_DIRECTORY}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not any(part in ignored for part in path.relative_to(root).parts)
    }


def records(root):
    return sorted((root / WORKSPACE_BUILD.RECOVERY_DIRECTORY).glob("*/recovery.json"))


def test_existing_lock_is_kept_without_a_recovery_record(workspace):
    before = fingerprint(workspace[0])
    result = cli(workspace, "concretize")
    assert result.returncode == 0, result.stderr
    assert "Keeping existing lock" in result.stdout
    assert fingerprint(workspace[0]) == before
    assert records(workspace[0]) == []


def test_reconcretize_changes_only_selected_lock_and_restores_manifest(workspace):
    root, _ = workspace
    selected = root / "environments/cce/common"
    other = root / "environments/gcc/common/spack.lock"
    manifest_before = (selected / "spack.yaml").read_bytes()
    other_before = other.read_bytes()
    result = cli(workspace, "concretize", "--reconcretize")
    assert result.returncode == 0, result.stdout + result.stderr
    assert NEW in json.loads((selected / "spack.lock").read_text())["concrete_specs"]
    assert other.read_bytes() == other_before
    assert (selected / "spack.yaml").read_bytes() == manifest_before
    record = json.loads(records(root)[0].read_text())
    assert record["status"] == "concretized"
    assert len(record["graph_delta"]["added"]) == 1
    action = json.loads((records(root)[0].parent / "fake-actions.jsonl").read_text().splitlines()[0])
    assert action[-4:] == ["-f", "--fresh", "-j", "1"]


def test_failed_reconcretize_restores_and_new_correction_can_be_solved(workspace):
    root, _ = workspace
    selected = root / "environments/cce/common"
    lock_before = (selected / "spack.lock").read_bytes()
    yaml_before = (selected / "spack.yaml").read_bytes()
    failed = cli(workspace, "concretize", "--reconcretize", extra_env={"FAIL_CONCRETIZE": "1"})
    assert failed.returncode != 0
    assert (selected / "spack.lock").read_bytes() == lock_before
    assert (selected / "spack.yaml").read_bytes() == yaml_before
    record_path = records(root)[0]
    assert json.loads(record_path.read_text())["status"] == "concretize_failed"
    corrected = yaml.safe_load((selected / "spack.yaml").read_text())
    corrected["spack"]["specs"] = ["tiny+corrected"]
    (selected / "spack.yaml").write_text(yaml.safe_dump(corrected, sort_keys=False))
    corrected_bytes = (selected / "spack.yaml").read_bytes()
    retried = cli(workspace, "concretize", "--reconcretize")
    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert (selected / "spack.yaml").read_bytes() == corrected_bytes
    assert len(records(root)) == 2
    assert records(root)[0] == record_path
    assert json.loads(records(root)[1].read_text())["status"] == "concretized"


def test_resume_installs_selected_environment_and_preserves_workspace_inputs(workspace):
    root, _ = workspace
    before = fingerprint(root)
    result = cli(workspace, "resume")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fingerprint(root) == before
    record_path = records(root)[0]
    record = json.loads(record_path.read_text())
    assert record["status"] == "resumed"
    assert (record_path.parent / "installed").read_text() == str(root / "environments/cce/common")
    action = json.loads((record_path.parent / "fake-actions.jsonl").read_text().splitlines()[-1])
    assert action[2:] == ["install", "--only-concrete", "--no-add", "--fail-fast"]
    assert "--no-cache" not in action


def test_failed_resume_allows_correction_solve_and_new_resume(workspace):
    root, _ = workspace
    manifest = root / "environments/cce/common/spack.yaml"
    before = manifest.read_bytes()
    failed = cli(workspace, "resume", extra_env={"FAIL_RESUME": "1"})
    assert failed.returncode != 0
    assert manifest.read_bytes() == before
    record_path = records(root)[0]
    assert json.loads(record_path.read_text())["status"] == "resume_failed"
    recipe = root / "package-repos/spack_repo/cse_trials/packages/tiny/package.py"
    recipe.write_text(recipe.read_text() + "# corrected\n")
    solved = cli(workspace, "concretize", "--reconcretize")
    assert solved.returncode == 0, solved.stdout + solved.stderr
    retried = cli(workspace, "resume")
    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert len(records(root)) == 3
    assert records(root)[0] == record_path


def test_guard_passes_a_verified_inherited_lock(workspace):
    root, _ = workspace
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "guard",
            "--workspace",
            str(root),
            "--",
            sys.executable,
            str(HELPER),
            "check-lock",
            "--workspace",
            str(root),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rejected = cli(workspace, "check-lock")
    assert rejected.returncode != 0


def test_unfinished_overlay_transaction_blocks_workspace_build(workspace):
    root, _ = workspace
    write(root / ".cse-overlay/active/record.json", json.dumps({"status": "applying"}))
    result = cli(workspace, "concretize", "--reconcretize")
    assert result.returncode != 0
    assert "overlay journal" in result.stderr.lower()
    assert records(root) == []


def test_failed_solve_blocks_check_and_resume_until_a_new_solve(workspace):
    root, _ = workspace
    failed = cli(workspace, "concretize", "--reconcretize", extra_env={"FAIL_CONCRETIZE": "1"})
    assert failed.returncode != 0
    checked = cli(workspace, "check", "--environment", "cce/common")
    assert checked.returncode != 0
    assert "latest forced solve" in checked.stderr
    resumed = cli(workspace, "resume")
    assert resumed.returncode != 0
    assert "latest forced solve" in resumed.stderr
    solved = cli(workspace, "concretize", "--reconcretize")
    assert solved.returncode == 0, solved.stdout + solved.stderr
    assert cli(workspace, "check", "--environment", "cce/common").returncode == 0


def test_resume_rejects_changed_root_intent_but_allows_presentation_change(workspace):
    root, _ = workspace
    manifest = root / "environments/cce/common/spack.yaml"
    value = yaml.safe_load(manifest.read_text())
    value["spack"]["specs"] = ["tiny+changed"]
    manifest.write_text(yaml.safe_dump(value, sort_keys=False))
    rejected = cli(workspace, "resume")
    assert rejected.returncode != 0
    assert "root intent" in rejected.stderr

    value["spack"]["specs"] = ["tiny"]
    value["spack"]["view"] = {"default": {"root": "/new/module-policy-view"}}
    manifest.write_text(yaml.safe_dump(value, sort_keys=False))
    before = manifest.read_bytes()
    resumed = cli(workspace, "resume")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert manifest.read_bytes() == before


@pytest.mark.parametrize('action,status', [
    ('concretize', 'concretize_preparing'), ('concretize', 'concretizing'),
    ('resume', 'resume_preparing'), ('resume', 'resuming'),
])
def test_interrupted_retry_preserves_later_manual_variant_edit(workspace, action, status):
    root, _ = workspace
    environment = root / 'environments/cce/common'
    manifest = environment / 'spack.yaml'
    before = manifest.read_bytes()
    lock_before = (environment / 'spack.lock').read_bytes()
    directory = root / '.cse-build-recovery/interrupted'
    directory.mkdir(parents=True)
    (directory / 'spack.yaml.before').write_bytes(before)
    (directory / 'spack.lock.before').write_bytes(lock_before)
    record = {'action': action, 'status': status, 'commands': [],
              'baseline': {'retained': True}, 'lock_existed': True,
              'manifest_before_sha256': hashlib.sha256(before).hexdigest(),
              'lock_before_sha256': hashlib.sha256(lock_before).hexdigest()}
    changed = yaml.safe_load(before)
    changed['spack']['specs'] = ['tiny+manually-corrected']
    manifest.write_text(yaml.safe_dump(changed))
    intended = manifest.read_bytes()
    with pytest.raises(ValueError, match='selected manifest changed after interruption'):
        WORKSPACE_BUILD._resume_interrupted(directory, record, environment,
                                            WORKSPACE_BUILD._recovery())
    assert manifest.read_bytes() == intended
    assert (environment / 'spack.lock').read_bytes() == lock_before
    assert (directory / 'spack.yaml.before').read_bytes() == before
