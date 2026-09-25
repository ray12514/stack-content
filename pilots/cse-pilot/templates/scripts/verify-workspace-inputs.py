#!/usr/bin/env python3
"""Check workspace inputs without running the recorded full lock policy."""

import runpy
import sys
from pathlib import Path


def main():
    workspace = Path(__file__).resolve().parents[1]
    try:
        overlay = runpy.run_path(str(workspace / "scripts/verify-overlay-inputs.py"))
        errors = overlay["check"](workspace / "package-repos")
        # Keep the exact policy already recorded for this workspace. Older
        # verifiers only expose a full-lock main(), which must not run merely
        # to enter status or begin an as-yet-unconcretized environment.
        policy = runpy.run_path(str(workspace / "scripts/verify-lockfiles.py"))
        check_inputs = policy.get("workspace_input_errors")
        if not errors and callable(check_inputs):
            errors.extend(check_inputs())
    except (OSError, ValueError, SyntaxError) as error:
        errors = ["workspace input verification failed: {}".format(error)]
    for error in errors:
        print("ERROR: " + error, file=sys.stderr)
    if errors:
        return 1
    print("Workspace overlay inventory passed; recorded input checks applied where available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
