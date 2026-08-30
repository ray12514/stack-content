from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "create-operator-session.py"
)
OPERATOR_SESSION = (
    Path(__file__).resolve().parents[1] / "scripts" / "operator-session.sh"
)


class ProviderSelectionTemplateTests(unittest.TestCase):
    def test_operator_session_sets_group_collaborative_umask(self) -> None:
        session = OPERATOR_SESSION.read_text(encoding="utf-8")
        self.assertIn("umask 0007", session)

    def test_node_context_selections_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "session" / "activate.sh"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--system",
                    "test-system",
                    "--trial-root",
                    str(root / "trial"),
                    "--tools-root",
                    str(root / "tools"),
                    "--bootstrap-python",
                    sys.executable,
                    "--group",
                    "test-builders",
                    "--work-root",
                    str(root / "work"),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            selections = (output.parent / "provider-selections.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn('export CSE_LOGIN_NODE_TYPE="login"', selections)
            self.assertIn(
                'export CSE_COMPUTE_NODE_TYPE="cpu_compute"', selections
            )
            self.assertIn(
                '# export CSE_SHARED_MPI_REF="<provider>@<version>"',
                selections,
            )
            self.assertIn(
                '# export CSE_SHARED_MPI_SOURCE="<external-or-build>"',
                selections,
            )
            self.assertNotIn('CSE_SHARED_MPI_REF="openmpi@4.1.8"', selections)

            activation = output.read_text(encoding="utf-8")
            self.assertIn("export CSE_GROUP=test-builders", activation)

    def test_collaboration_group_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--system",
                    "test-system",
                    "--trial-root",
                    str(root / "trial"),
                    "--tools-root",
                    str(root / "tools"),
                    "--bootstrap-python",
                    sys.executable,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--group", result.stderr)

    def test_failed_inspector_build_does_not_advance_commit_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            work_root = root / "work"
            session = work_root / "sessions" / "activate.sh"
            helper = (
                work_root
                / "stack-content"
                / "pilots"
                / "cse-pilot"
                / "scripts"
                / "operator-session.sh"
            )
            helper.parent.mkdir(parents=True)
            shutil.copy2(OPERATOR_SESSION, helper)

            inspector = work_root / "cluster-inspector"
            inspector.mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=inspector, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=inspector,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test Builder"],
                cwd=inspector,
                check=True,
            )
            (inspector / "Makefile").write_text(
                "build:\n\t@echo 'simulated compiler failure' >&2\n\t@exit 1\n",
                encoding="utf-8",
            )
            old_binary = inspector / "cluster-inspector"
            old_binary.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            old_binary.chmod(0o755)
            subprocess.run(["git", "add", "."], cwd=inspector, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixture"],
                cwd=inspector,
                check=True,
            )

            create = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--system",
                    "test-system",
                    "--trial-root",
                    str(root / "initial-conversion-trials"),
                    "--tools-root",
                    str(root / "tools"),
                    "--bootstrap-python",
                    sys.executable,
                    "--group",
                    "test-builders",
                    "--work-root",
                    str(work_root),
                    "--output",
                    str(session),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(create.returncode, 0, create.stderr)

            state = session.parent / "tool-state"
            state.mkdir()
            stamp = state / "cluster-inspector.commit"
            stamp.write_text("previous-successful-commit\n", encoding="utf-8")
            workdir = root / "builder-work"
            workdir.mkdir()

            command = f"""
export WORKDIR={workdir!s}
export USER=test-builder
source {session!s} >/dev/null
before="$(cat "$CSE_TOOL_STATE_ROOT/cluster-inspector.commit")"
set +e
cse_rebuild_cluster_inspector >/dev/null 2>&1
build_status=$?
set -e
after="$(cat "$CSE_TOOL_STATE_ROOT/cluster-inspector.commit")"
printf 'build_status=%s\\nbefore=%s\\nafter=%s\\n' \\
  "$build_status" "$before" "$after"
cse_session_status
"""
            result = subprocess.run(
                ["bash", "-c", command],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            status_match = re.search(r"^build_status=(\d+)$", result.stdout, re.MULTILINE)
            self.assertIsNotNone(status_match)
            build_status = int(status_match.group(1))
            self.assertNotEqual(build_status, 0)
            self.assertNotEqual(build_status, 127)
            self.assertIn("before=previous-successful-commit", result.stdout)
            self.assertIn("after=previous-successful-commit", result.stdout)
            self.assertIn("inspector: build/rebuild required", result.stdout)


if __name__ == "__main__":
    unittest.main()
