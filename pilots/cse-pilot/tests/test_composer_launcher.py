from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("native", [False, True])
def test_composer_launcher_keeps_python_off_native_command(tmp_path: Path, native: bool) -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = tmp_path / "candidate binary"
    launcher.write_text("#!/bin/sh\nprintf '%s\\n' native \"$@\"\n")
    launcher.chmod(0o755)
    pyz = tmp_path / "fake.pyz"
    pyz.write_text("import sys\nprint('pyz')\nprint(*sys.argv[1:], sep='\\n')\n")
    session = tmp_path / "session/activate.sh"
    result = subprocess.run([
        sys.executable, str(root / "scripts/create-operator-session.py"),
        "--system", "test-system", "--trial-root", str(tmp_path / "initial-conversion-trials"),
        "--tools-root", str(tmp_path / "tools"), "--bootstrap-python", sys.executable,
        "--group", "test-builders", "--work-root", str(tmp_path / "work"),
        "--output", str(session),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # Point the generated entry at the actual source helper, not a copied fake.
    helper = tmp_path / "work/stack-content/pilots/cse-pilot/scripts/operator-session.sh"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.symlink_to(root / "scripts/operator-session.sh")
    env = dict(os.environ, WORKDIR=str(tmp_path / "scratch"), USER="test-builder")
    env.update(
        TEST_SESSION=str(session), TEST_PYTHON=sys.executable, TEST_PYZ=str(pyz),
        TEST_NATIVE=str(launcher) if native else "",
    )
    env.pop("SPACK_ENV", None)
    result = subprocess.run(["bash", "-c", '''
set -e
source "$TEST_SESSION" >/dev/null
export CSE_PYTHON="$TEST_PYTHON" STACK_COMPOSER="$TEST_PYZ"
export CSE_STACK_COMPOSER_NATIVE="$TEST_NATIVE"
cse_stack_composer --help "argument with spaces"
'''], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["native" if native else "pyz", "--help", "argument with spaces"]
