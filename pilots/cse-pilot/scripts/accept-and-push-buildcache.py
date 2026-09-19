#!/usr/bin/env python3
"""Run explicit consumer acceptance, then sign/push the unchanged locked roots.

Use a quiescent workspace and a candidate mirror. A failed push may leave partial
cache artifacts; this command never activates a release or changes public modules.
Requires Spack 1.2.2 CLI semantics; Python uses only the standard library.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse


def snapshot(workspace):
    result = {}
    for name in ("spack.yaml", "spack.lock"):
        path = workspace / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("required workspace input is missing or a symlink: " + str(path))
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def execute(command, logfile, timeout, cwd):
    started = time.monotonic()
    record = {"argv": command}
    with logfile.open("w") as output:
        try:
            process = subprocess.Popen(command, cwd=str(cwd), stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            record["returncode"] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            record.update(returncode=124, timed_out=True)
        except OSError as error:
            record.update(returncode=127, error=str(error))
    record.update(seconds=round(time.monotonic() - started, 3), log=logfile.name)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spack", required=True, help="Path to the pinned Spack executable")
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--destination", required=True, help="Explicit candidate mirror path or URL")
    parser.add_argument("--evidence", required=True, type=Path, help="New evidence directory")
    parser.add_argument("--timeout", type=int, default=600, help="Per-command seconds")
    parser.add_argument("acceptance", nargs=argparse.REMAINDER,
                        help="Consumer command argv after --; exit zero means acceptance")
    args = parser.parse_args()
    command = args.acceptance[1:] if args.acceptance[:1] == ["--"] else args.acceptance
    if not command or args.timeout <= 0:
        parser.error("provide an acceptance command after -- and a positive timeout")
    # Spack 1.2.2 silently disables --signed for OCI. Mirror aliases could resolve
    # to OCI too, so accept only explicit supported paths/URLs here.
    if not (Path(args.destination).is_absolute() or
            urlparse(args.destination).scheme in ("file", "http", "https", "s3", "gs")):
        parser.error("signed publication requires an explicit non-OCI mirror path or URL")
    args.environment = args.environment.resolve()
    args.evidence = args.evidence.resolve()
    args.evidence.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "status": "preflight_failed",
              "environment": str(args.environment), "destination": args.destination,
              "started_at_unix": time.time()}
    try:
        before = snapshot(args.environment)
        lock = json.loads((args.environment / "spack.lock").read_text())
        roots = sorted({root["hash"] for root in lock["roots"]})
        if not roots or any(not re.fullmatch("[a-z2-7]{32}", root) or
                            root not in lock["concrete_specs"] for root in roots):
            raise ValueError("lock must contain concrete root hashes")
        report.update(input_sha256=before, approved_root_hashes=roots,
                      dependency_policy="all non-external dependencies of exact roots")
        for name in before:
            (args.evidence / name).write_bytes((args.environment / name).read_bytes())
        report["acceptance"] = execute(command, args.evidence / "acceptance.log",
                                       args.timeout, args.environment)
        if report["acceptance"]["returncode"]:
            report["status"] = "acceptance_failed"
            return 1
        report["inputs_after_acceptance"] = snapshot(args.environment)
        if before != report["inputs_after_acceptance"]:
            report["status"] = "inputs_changed"
            return 1
        push = [str(Path(args.spack).resolve()), "-e", str(args.environment),
                "buildcache", "push", "--signed", "--fail-fast", "--update-index",
                "--with-build-dependencies", args.destination]
        push.extend("/" + root for root in roots)
        report["push"] = execute(push, args.evidence / "push.log", args.timeout,
                                 args.environment)
        report["status"] = "push_failed" if report["push"]["returncode"] else "pushed"
        report["inputs_after_push"] = snapshot(args.environment)
        if before != report["inputs_after_push"]:
            report["status"] = "inputs_changed_during_push"
        return 0 if report["status"] == "pushed" else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["error"] = str(error)
        return 1
    finally:
        (args.evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print("{}: {}".format(report["status"], args.evidence / "report.json"))


if __name__ == "__main__":
    sys.exit(main())
