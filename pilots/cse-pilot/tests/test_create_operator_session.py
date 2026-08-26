from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
