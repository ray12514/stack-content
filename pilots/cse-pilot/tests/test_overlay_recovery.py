"""Operator-facing recovery CLI: candidate isolation, explicit review, and retries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import time

import pytest
import yaml

PILOT = Path(__file__).resolve().parents[1]
HELPER = PILOT / 'templates/scripts/overlay-recovery.py'
OLD = 'a' * 32
NEW = 'b' * 32
DEP = 'c' * 32


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)


@pytest.fixture
def recovery(tmp_path):
    workspace = tmp_path / 'baseline'
    candidate = tmp_path / 'candidate'
    source = tmp_path / 'fix' / 'tiny'
    repo = workspace / 'package-repos/spack_repo/cse_trials'
    write(repo / 'repo.yaml', 'repo:\n  namespace: cse_trials\n  api: v2.0\n')
    write(repo / 'packages/tiny/package.py', 'class Tiny:\n    pass\n')
    write(source / 'package.py', 'class Tiny:\n    fixed = True\n')
    write(workspace / 'configs/common/repos.yaml', 'repos:\n  cse_trials: ../../package-repos/spack_repo/cse_trials\n')
    write(workspace / 'configs/common/config.yaml', 'config:\n  install_tree: /retained/store\n  misc_cache: /retained/cache\n')
    write(workspace / 'workspace-manifest.yaml', 'schema_version: 1\n')
    for name, package, h in [('cce/common', 'tiny', OLD), ('cce/serial', 'tiny', OLD), ('gcc/common', 'other', DEP)]:
        env = workspace / 'environments' / name
        write(env / 'spack.yaml', yaml.safe_dump({'spack': {'include:': ['../../../configs/common'], 'specs': [package], 'view': '/live/views', 'modules:': {'default': {'enable': ['tcl']}}}}))
        node = {'name': package, 'version': '1.0', 'compiler': {'name': 'cce', 'version': '17'}, 'parameters': {}}
        write(env / 'spack.lock', json.dumps({'_meta': {'file-type': 'spack-lockfile', 'lockfile-version': 6, 'specfile-version': 5}, 'roots': [{'hash': h, 'spec': package}], 'concrete_specs': {h: node}}))
    write(workspace / 'environments/cce/unlocked/spack.yaml', 'spack:\n  include:: [../../../configs/common]\n  specs: [tiny]\n')
    spack = tmp_path / 'spack/bin/spack'
    write(spack, '#!' + sys.executable + '\n' + '''import json, os, pathlib, sys, subprocess
args = sys.argv[1:]
if args == ['--version']:
    print('1.2.2'); sys.exit(0)
candidate = pathlib.Path.cwd()
record = json.loads((candidate / 'recovery.json').read_text())
env = pathlib.Path(args[1]); action = args[2]
if action == 'location':
    print(str(pathlib.Path(record['spack']).parent.parent) if args[-1] == 'builtin' else str(candidate / 'package-repos/spack_repo' / record['repository']))
elif action == 'concretize':
    if os.environ.get('FAIL_SOLVE'):
        (env / 'spack.lock').write_text('broken partial output')
        sys.exit(1)
    path = env / 'spack.lock'; data = json.loads(path.read_text())
    old = record['old_hash']; new = 'b' * 32
    if old in data['concrete_specs']:
        data['concrete_specs'][new] = data['concrete_specs'].pop(old)
        if os.environ.get('ADD_PATCH_ID'):
            data['concrete_specs'][new].setdefault('parameters', {})['patches'] = ['d' * 64]
        for root in data['roots']:
            if root['hash'] == old: root['hash'] = new
    path.write_text(json.dumps(data))
elif action == 'python':
    if 'inspect.getfile' in args[-1]:
        recipe = str(candidate / record['recipe'])
        if os.environ.get('WRONG_RECIPE'): recipe = '/builtin/package.py'
        print('RECOVERY_JSON=' + json.dumps({'recipe': recipe}))
    elif "'missing'" in args[-1]:
        print('RECOVERY_JSON=' + json.dumps({'missing': []}))
    else:
        prefix = candidate / 'fake-prefix'
        print('RECOVERY_JSON=' + json.dumps({'installed': prefix.exists(), 'prefix': str(prefix)}))
elif action == 'install':
    if os.environ.get('FORK_MARKER'):
        worker = subprocess.Popen([sys.executable, '-c', 'import os,time,json; os.setpgrp(); open(os.environ["FORK_MARKER"],"w").write(json.dumps({"pid":os.getpid(),"pgid":os.getpgrp(),"sid":os.getsid(0)})); time.sleep(60)'])
        worker.wait()
    if os.environ.get('FAIL_BUILD'): sys.exit(1)
    (candidate / 'fake-prefix').mkdir(exist_ok=True)
else:
    sys.exit('unexpected args ' + repr(args))
''')
    spack.chmod(0o755)
    for args in [('init', '-q'), ('remote', 'add', 'origin', 'https://example.invalid/spack.git'), ('add', '.'), ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')]:
        subprocess.run(['git', '-C', str(spack.parent.parent), *args], check=True, capture_output=True)
    return workspace, candidate, source, spack


def cli(recovery, action, *args, extra_env=None):
    workspace, candidate, source, spack = recovery
    command = [sys.executable, str(HELPER), action, '--candidate', str(candidate)]
    if action == 'prepare':
        command += ['--workspace', str(workspace), '--from', str(source), '--package', 'tiny', '--environment', 'cce/common', '--spack', str(spack)]
    environment = os.environ.copy()
    environment['CSE_NODE_CONTEXT'] = 'compute'
    environment.update(extra_env or {})
    return subprocess.run(command + list(args), env=environment, capture_output=True, text=True)


def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr


def record(recovery):
    return json.loads((recovery[1] / 'recovery.json').read_text())


def fingerprint(root):
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


def test_recovery_scans_all_locks_builds_exact_correction_and_exports(recovery, tmp_path):
    baseline = fingerprint(recovery[0])
    ok(cli(recovery, 'prepare'))
    state = record(recovery)
    assert state['affected'] == ['cce/common', 'cce/serial']
    assert state['unchanged'] == ['gcc/common']
    assert state['unlocked'] == ['cce/unlocked']
    for path in (recovery[1] / 'environments').glob('*/*/spack.yaml'):
        data = yaml.safe_load(path.read_text())['spack']
        assert data['view'] is False
        assert data['modules:'] == {'default': {'enable': []}}
    ok(cli(recovery, 'solve'))
    assert (recovery[1] / 'environments/gcc/common/spack.lock').read_bytes() == (recovery[0] / 'environments/gcc/common/spack.lock').read_bytes()
    state = record(recovery)
    assert state['new_hash'] == NEW
    rejected = cli(recovery, 'retry', '--approve-plan', 'wrong')
    assert rejected.returncode != 0
    ok(cli(recovery, 'retry', '--approve-plan', state['plan_sha256']))
    state = record(recovery)
    assert state['retry'] == 'passed'
    install = [c['argv'] for c in state['commands'] if 'install' in c['argv']]
    assert len(install) == 1
    assert install[0][-1] == '/' + NEW
    assert '--no-cache' in install[0] and '--only-concrete' in install[0]
    ok(cli(recovery, 'retry', '--approve-plan', state['plan_sha256']))
    assert len([c for c in record(recovery)['commands'] if 'install' in c['argv']]) == 1
    bundle = tmp_path / 'export'
    ok(cli(recovery, 'export', '--output', str(bundle)))
    assert (bundle / 'tiny/package.py').read_bytes() == (recovery[2] / 'package.py').read_bytes()
    assert not list(bundle.rglob('spack.lock'))
    assert (bundle / 'SHA256SUMS').is_file()
    assert fingerprint(recovery[0]) == baseline


def test_failed_solve_restores_candidate_lock_and_resumes(recovery):
    ok(cli(recovery, 'prepare'))
    lock = recovery[1] / 'environments/cce/common/spack.lock'
    before = lock.read_bytes()
    result = cli(recovery, 'solve', extra_env={'FAIL_SOLVE': '1'})
    assert result.returncode != 0
    assert lock.read_bytes() == before
    assert record(recovery)['status'] == 'solve_failed'
    ok(cli(recovery, 'solve'))
    assert record(recovery)['status'] == 'solved'


def test_failed_build_resumes_without_resolve(recovery):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve'))
    state = record(recovery)
    locks = {p: p.read_bytes() for p in (recovery[1] / 'environments').rglob('spack.lock')}
    result = cli(recovery, 'retry', '--approve-plan', state['plan_sha256'], extra_env={'FAIL_BUILD': '1'})
    assert result.returncode != 0
    assert record(recovery)['status'] == 'retry_failed'
    ok(cli(recovery, 'retry', '--approve-plan', state['plan_sha256']))
    assert all(p.read_bytes() == value for p, value in locks.items())


@pytest.mark.parametrize('which', ['baseline', 'candidate'])
def test_drift_blocks_execution(recovery, which):
    ok(cli(recovery, 'prepare'))
    before_commands = record(recovery)['commands']
    root = recovery[0 if which == 'baseline' else 1]
    path = root / 'environments/cce/common/spack.lock'
    path.write_text(path.read_text() + '\n')
    result = cli(recovery, 'solve')
    assert result.returncode != 0 and 'changed' in result.stderr
    assert record(recovery)['commands'] == before_commands


def test_already_installed_corrected_hash_is_not_counted_as_retry(recovery):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve'))
    (recovery[1] / 'fake-prefix').mkdir()
    result = cli(recovery, 'retry', '--approve-plan', record(recovery)['plan_sha256'])
    assert result.returncode != 0 and 'already installed' in result.stderr
    assert record(recovery)['retry'] is None


def test_wrong_recipe_selection_blocks_solve_and_keeps_lock(recovery):
    ok(cli(recovery, 'prepare'))
    path = recovery[1] / 'environments/cce/common/spack.lock'
    before = path.read_bytes()
    result = cli(recovery, 'solve', extra_env={'WRONG_RECIPE': '1'})
    assert result.returncode != 0 and 'did not select' in result.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize('kind', ['symlink', 'outside-include', 'missing-patch', 'existing-candidate'])
def test_unsafe_preparation_rejected_without_modifying_source(recovery, kind, tmp_path):
    workspace, candidate, source, _ = recovery
    if kind == 'symlink':
        (source / 'escape').symlink_to(workspace / 'workspace-manifest.yaml')
    elif kind == 'outside-include':
        path = workspace / 'environments/cce/common/spack.yaml'
        path.write_text('spack:\n  include:: [/outside/config]\n  specs: [tiny]\n')
    elif kind == 'missing-patch':
        (source / 'package.py').write_text('patch("missing.patch")\n')
    else:
        candidate.mkdir()
        (candidate / 'sentinel').write_text('keep')
    before = fingerprint(workspace)
    result = cli(recovery, 'prepare')
    assert result.returncode != 0
    assert fingerprint(workspace) == before
    if kind == 'existing-candidate':
        assert (candidate / 'sentinel').read_text() == 'keep'


def test_dependency_import_broadens_scope_conservatively(recovery):
    path = recovery[0] / 'package-repos/spack_repo/cse_trials/packages/other/package.py'
    write(path, 'from spack_repo.cse_trials.packages.tiny.package import Tiny\n')
    ok(cli(recovery, 'prepare'))
    assert record(recovery)['affected'] == ['cce/common', 'cce/serial', 'gcc/common']


def test_login_context_cannot_build(recovery):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve'))
    result = cli(recovery, 'retry', '--approve-plan', record(recovery)['plan_sha256'], extra_env={'CSE_NODE_CONTEXT': 'login'})
    assert result.returncode != 0 and 'compute shell' in result.stderr


def test_resume_requires_retry_and_continues_only_recorded_environment(recovery):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve'))
    approval = record(recovery)['plan_sha256']
    result = cli(recovery, 'resume', '--approve-plan', approval)
    assert result.returncode != 0 and 'focused retry' in result.stderr
    ok(cli(recovery, 'retry', '--approve-plan', approval))
    ok(cli(recovery, 'resume', '--approve-plan', approval))
    state = record(recovery)
    assert state['resume'] == 'passed'
    installs = [c['argv'] for c in state['commands'] if 'install' in c['argv']]
    assert len(installs) == 2
    assert all(command[2].endswith('/environments/cce/common') for command in installs)
    assert not any(arg.startswith('/' + NEW) for arg in installs[1])
    assert '--only-concrete' in installs[1]


def test_changed_review_plan_blocks_retry(recovery):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve'))
    plan = recovery[1] / 'plan.json'
    plan.write_text(plan.read_text() + '\n')
    result = cli(recovery, 'retry', '--approve-plan', record(recovery)['plan_sha256'])
    assert result.returncode != 0
    assert not any('install' in c['argv'] for c in record(recovery)['commands'])


def test_unsupported_lock_format_fails_before_candidate_created(recovery):
    lock = recovery[0] / 'environments/cce/common/spack.lock'
    data = json.loads(lock.read_text())
    data['_meta']['lockfile-version'] = 999
    lock.write_text(json.dumps(data))
    result = cli(recovery, 'prepare')
    assert result.returncode != 0 and 'version 6' in result.stderr
    assert not recovery[1].exists()


def test_unknown_recipe_imports_expand_scope(recovery):
    source = recovery[2] / 'package.py'
    source.write_text('import importlib\nimportlib.import_module("local_policy")\nclass Tiny: pass\n')
    ok(cli(recovery, 'prepare'))
    assert record(recovery)['affected'] == ['cce/common', 'cce/serial', 'gcc/common']


def test_patch_metadata_change_is_not_a_changed_user_variant(recovery):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve', extra_env={'ADD_PATCH_ID': '1'}))
    assert record(recovery)['new_hash'] == NEW
    ok(cli(recovery, 'retry', '--approve-plan', record(recovery)['plan_sha256']))


def test_nested_catalog_include_escape_is_rejected(recovery):
    write(recovery[0] / 'catalog/scopes/common/include.yaml', 'include: [/outside/policy]\n')
    result = cli(recovery, 'prepare')
    assert result.returncode != 0 and 'escapes workspace' in result.stderr
    assert not recovery[1].exists()


def test_changed_provider_directive_broadens_scope(recovery):
    (recovery[2] / 'package.py').write_text('class Tiny:\n    provides("virtual-tiny")\n')
    ok(cli(recovery, 'prepare'))
    assert record(recovery)['provider_directives_changed']
    assert record(recovery)['affected'] == ['cce/common', 'cce/serial', 'gcc/common']


def test_tracked_dirty_spack_checkout_is_rejected(recovery):
    spack = recovery[3]
    spack.write_text(spack.read_text() + '\n# unrecorded runtime edit\n')
    result = cli(recovery, 'prepare')
    assert result.returncode != 0 and 'tracked modifications' in result.stderr
    assert not recovery[1].exists()


def test_export_rejects_changed_plan_after_successful_retry(recovery, tmp_path):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve'))
    ok(cli(recovery, 'retry', '--approve-plan', record(recovery)['plan_sha256']))
    path = recovery[1] / 'plan.json'
    path.write_text(path.read_text() + '\n')
    output = tmp_path / 'rejected-export'
    result = cli(recovery, 'export', '--output', str(output))
    assert result.returncode != 0
    assert not output.exists()


def test_sigterm_stops_separate_build_worker_group_before_retry(recovery, tmp_path):
    ok(cli(recovery, 'prepare'))
    ok(cli(recovery, 'solve'))
    approval = record(recovery)['plan_sha256']
    marker = tmp_path / 'worker.json'
    environment = dict(os.environ, CSE_NODE_CONTEXT='compute', FORK_MARKER=str(marker))
    process = subprocess.Popen([sys.executable, str(HELPER), 'retry', '--candidate',
                                str(recovery[1]), '--approve-plan', approval],
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    worker = None
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.communicate())
            time.sleep(0.05)
        assert marker.exists(), 'build worker never started'
        worker = json.loads(marker.read_text())
        assert worker['pgid'] != worker['sid'], 'fixture must reproduce separate Spack worker group'
        process.terminate()
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 143, stdout + stderr
        probe = subprocess.run(['ps', '-p', str(worker['pid']), '-o', 'stat='],
                               capture_output=True, text=True)
        assert not probe.stdout.strip() or probe.stdout.strip().startswith('Z'), 'orphaned build worker is still running'
        assert record(recovery)['status'] == 'retry_failed'
        ok(cli(recovery, 'retry', '--approve-plan', approval))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        if worker:
            try:
                os.killpg(worker['pgid'], signal.SIGKILL)
            except ProcessLookupError:
                pass
