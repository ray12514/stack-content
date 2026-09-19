"""Operator CLI rejection behavior; actual signed pushes run in hpc-lab."""
import json
from pathlib import Path
import subprocess
import sys
import time


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/accept-and-push-buildcache.py"
ROOT_HASH = "a" * 32


def locked_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "spack.yaml").write_text("spack:\n  specs: [fixture]\n")
    (workspace / "spack.lock").write_text(json.dumps({
        "_meta": {"file-type": "spack-lockfile", "lockfile-version": 6},
        "roots": [{"hash": ROOT_HASH, "spec": "fixture"}],
        "concrete_specs": {ROOT_HASH: {"name": "fixture"}},
    }))
    return workspace


def invoke(tmp_path, workspace, command, *options):
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--spack", str(tmp_path / "absent-spack"),
        "--environment", str(workspace), "--destination", str(tmp_path / "cache"),
        "--evidence", str(tmp_path / "evidence"), *options, "--", *command,
    ], text=True, capture_output=True)
    report_path = tmp_path / "evidence/report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    return result, report


def test_failed_consumer_retains_evidence_without_attempting_push(tmp_path):
    workspace = locked_workspace(tmp_path)
    result, report = invoke(tmp_path, workspace, [sys.executable, "-c",
        "print('wrong numerical answer'); raise SystemExit(7)"])
    assert result.returncode != 0
    assert report["status"] == "acceptance_failed"
    assert report["acceptance"]["returncode"] == 7
    assert "push" not in report
    assert "wrong numerical answer" in (tmp_path / "evidence/acceptance.log").read_text()
    assert not (tmp_path / "cache").exists()


def test_accepted_command_cannot_change_lock_before_push(tmp_path):
    workspace = locked_workspace(tmp_path)
    result, report = invoke(tmp_path, workspace, [sys.executable, "-c",
        "from pathlib import Path; Path('spack.lock').write_text('{}')"])
    assert result.returncode != 0
    assert report["status"] == "inputs_changed"
    assert "push" not in report
    assert not (tmp_path / "cache").exists()


def test_consumer_timeout_is_failed_acceptance(tmp_path):
    workspace = locked_workspace(tmp_path)
    result, report = invoke(tmp_path, workspace, [sys.executable, "-c",
        "import time; time.sleep(10)"], "--timeout", "1")
    assert result.returncode != 0
    assert report["status"] == "acceptance_failed"
    assert report["acceptance"]["timed_out"] is True
    assert "push" not in report


def test_timeout_stops_consumer_child_processes(tmp_path):
    workspace = locked_workspace(tmp_path)
    marker = workspace / "late-consumer-output"
    child = "import time; from pathlib import Path; time.sleep(1.3); Path('late-consumer-output').touch()"
    command = "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', %r]); time.sleep(10)" % child
    result, report = invoke(tmp_path, workspace, [sys.executable, "-c", command], "--timeout", "1")
    time.sleep(0.6)
    assert result.returncode != 0 and report["status"] == "acceptance_failed"
    assert not marker.exists()


def test_signed_gate_rejects_oci_before_acceptance(tmp_path):
    workspace = locked_workspace(tmp_path)
    result, report = invoke(tmp_path, workspace, [sys.executable, "-c", "raise SystemExit(0)"],
                            "--destination", "oci://example.invalid/unsigned")
    assert result.returncode != 0
    assert "non-OCI" in result.stderr
    assert report == {}
