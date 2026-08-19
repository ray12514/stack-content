#!/usr/bin/env python3
"""Create the sourceable operator-session entry point for one CSE trial.

The generated file records installer/operator selections only. Path derivation,
validation, and helper functions stay in operator-session.sh so a repository
update fixes the behavior for every saved session.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import stat
import sys
from pathlib import Path


SPACK_SOURCE = "https://github.com/spack/spack.git"
SPACK_VERSION = "1.2.2"
SPACK_COMMIT = "3e19345b6e12f5ff1b874f4059622fc6a1fd804a"
STACK_BRANCH = "codex/simplified-render-plan"
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


class InputError(ValueError):
    pass


def safe_segment(value: str, label: str) -> str:
    if not SAFE_SEGMENT.fullmatch(value) or value in {".", ".."}:
        raise InputError(
            f"{label} must contain only letters, numbers, '.', '_', or '-'; "
            f"got {value!r}"
        )
    return value


def absolute_path(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise InputError(f"{label} must be an absolute path; got {str(path)!r}")
    return path


def shell_export(name: str, value: str) -> str:
    return f"export {name}={shlex.quote(value)}"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Create a resumable CSE trial operator-session script."
    )
    result.add_argument("--system", required=True)
    result.add_argument("--trial-root", required=True)
    result.add_argument("--tools-root", required=True)
    result.add_argument("--bootstrap-python", required=True)
    result.add_argument("--spack-mode", choices=("shared", "local"), default="shared")
    result.add_argument("--work-root", default=str(Path.home() / "STACK_TESTING"))
    result.add_argument("--catalog-release")
    result.add_argument("--trial-release")
    result.add_argument("--branch", default=STACK_BRANCH)
    result.add_argument("--group", default="cse")
    result.add_argument("--spack-source", default=SPACK_SOURCE)
    result.add_argument("--spack-version", default=SPACK_VERSION)
    result.add_argument("--spack-commit", default=SPACK_COMMIT)
    result.add_argument("--output")
    result.add_argument("--overwrite", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        system = safe_segment(args.system, "--system")
        catalog_release = safe_segment(
            args.catalog_release or f"{system}-catalog-001", "--catalog-release"
        )
        trial_release = safe_segment(
            args.trial_release or f"{system}-trial-001", "--trial-release"
        )
        safe_segment(args.group, "--group")
        safe_segment(args.spack_version, "--spack-version")

        work_root = absolute_path(args.work_root, "--work-root")
        trial_root = absolute_path(args.trial_root, "--trial-root")
        tools_root = absolute_path(args.tools_root, "--tools-root")
        bootstrap_python = absolute_path(
            args.bootstrap_python, "--bootstrap-python"
        )
        if not bootstrap_python.is_file() or not os.access(bootstrap_python, os.X_OK):
            raise InputError(
                f"--bootstrap-python must name an executable file; got "
                f"{bootstrap_python}"
            )

        if args.output:
            output = absolute_path(args.output, "--output")
        else:
            output = (
                work_root
                / "operator-sessions"
                / system
                / trial_release
                / "activate.sh"
            )

        if output.exists() and not args.overwrite:
            raise InputError(
                f"operator session already exists: {output}; select a new release or "
                "pass --overwrite before that release has durable artifacts"
            )

        values = {
            "WORK_ROOT": str(work_root),
            "SYSTEM_NAME": system,
            "STACK_BRANCH": args.branch,
            "CATALOG_RELEASE": catalog_release,
            "TRIAL_RELEASE": trial_release,
            "CSE_GROUP": args.group,
            "CSE_TRIAL_ROOT": str(trial_root),
            "SPACK_RUNTIME_MODE": args.spack_mode,
            "CSE_TOOLS_ROOT": str(tools_root),
            "SPACK_SOURCE": args.spack_source,
            "SPACK_VERSION": args.spack_version,
            "SPACK_TAG": f"v{args.spack_version}",
            "SPACK_COMMIT": args.spack_commit,
            "CSE_BOOTSTRAP_PYTHON": str(bootstrap_python),
        }

        lines = [
            "#!/usr/bin/env bash",
            "# Source this file to resume one CSE Initial Conversion Trials operator session.",
            "# It intentionally restores state; it does not pull repositories or rebuild tools.",
            "",
            'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then',
            '  echo "source this file instead of executing it" >&2',
            "  exit 2",
            "fi",
            "",
        ]
        lines.extend(shell_export(name, value) for name, value in values.items())
        lines.extend(
            [
                'export CSE_OPERATOR_SESSION_FILE="${BASH_SOURCE[0]}"',
                'source "$WORK_ROOT/stack-content/pilots/cse-pilot/scripts/operator-session.sh"',
                "",
            ]
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        output.parent.chmod(stat.S_IRWXU)
        output.write_text("\n".join(lines), encoding="utf-8")
        output.chmod(stat.S_IRUSR | stat.S_IWUSR)

        selections = output.parent / "provider-selections.sh"
        if not selections.exists():
            selections.write_text(
                """# Reviewed selections completed after static-catalog review.
# This file is sourced automatically by activate.sh when present.
# Uncomment and fill every required selection before creating build values.
# export CSE_SHARED_COMPILER_REF="gcc@12.5.0"
# export CSE_SHARED_COMPILER_PUBLIC_NAME="<module-front-door-name>"
# export CSE_SHARED_MPI_REF="<provider>@<version>"
# export CSE_SHARED_MPI_SOURCE="<external-or-build>"
# export CSE_PLATFORM_COMPILER_REF="<provider>@<version>"
# export CSE_PLATFORM_COMPILER_PUBLIC_NAME="<front-door-name>"
# export CSE_PLATFORM_MPI_REF="<provider>@<version>"
# export CSE_PLATFORM_MPI_SOURCE="<external-or-build>"
# Verify these exact keys against profile_facts.node_types in catalog/manifest.yaml.
export CSE_LOGIN_NODE_TYPE="login"
export CSE_COMPUTE_NODE_TYPE="cpu_compute"
# export BUILD_JOBS="<approved-job-count>"
# Optional: export CSE_CPU_TARGET="x86_64_v2"
# Optional: export CSE_SHARED_COMPILER_SEED_REF="gcc@<reviewed-version>"
""",
                encoding="utf-8",
            )
            selections.chmod(stat.S_IRUSR | stat.S_IWUSR)

        print(f"Created operator session: {output}")
        print(f"Review provider selections later: {selections}")
        print(f"Resume with: source {shlex.quote(str(output))}")
        return 0
    except InputError as exc:
        print(f"create-operator-session: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
