#!/usr/bin/env python3
"""Measure the real helper on a disposable package-shaped fixture, never a workspace."""
import argparse
import grp
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile
import time


def reset(root):
    for directory, children, files in os.walk(str(root), followlinks=False):
        os.chown(directory, -1, os.getgid(), follow_symlinks=False)
        os.chmod(directory, 0o700, follow_symlinks=False)
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            os.chown(str(path), -1, os.getgid(), follow_symlinks=False)
            os.chmod(str(path), 0o700 if path.parent.name == "bin" else 0o600,
                     follow_symlinks=False)


def verify(root, sentinel):
    for directory, children, files in os.walk(str(root), followlinks=False):
        info = os.lstat(directory)
        assert stat.S_IMODE(info.st_mode) in (0o770, 0o2770), directory
        assert info.st_gid == os.getgid(), directory
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            info = path.stat()
            assert stat.S_IMODE(info.st_mode) == (0o770 if path.parent.name == "bin" else 0o660), str(path)
            assert info.st_gid == os.getgid(), str(path)
    assert stat.S_IMODE(sentinel.stat().st_mode) == 0o600
    assert sentinel.read_text() == "outside"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, default=Path(__file__).resolve().parents[1] / "templates/scripts/workspace-permissions.py")
    parser.add_argument("--temporary-parent", type=Path)
    parser.add_argument("--packages", type=int, default=500)
    parser.add_argument("--files-per-package", type=int, default=100)
    parser.add_argument("--jobs", nargs="+", type=int, default=[1, 4, 16, 32])
    args = parser.parse_args()
    if args.packages < 1 or args.files_per_package < 1 or any(j < 1 or j > 32 for j in args.jobs):
        parser.error("positive fixture sizes and jobs 1..32 are required")
    records = []
    with tempfile.TemporaryDirectory(prefix="cse-permission-bench-", dir=str(args.temporary_parent) if args.temporary_parent else None) as temporary:
        base = Path(temporary).resolve()
        root = base / "generated"
        root.mkdir()
        sentinel = base / "outside"
        sentinel.write_text("outside")
        sentinel.chmod(0o600)
        for number in range(args.packages):
            package = root / ("package-%04d" % number)
            for part in ("bin", "lib", "include", "share"):
                (package / part).mkdir(parents=True)
            for index in range(args.files_per_package):
                part = ("bin", "lib", "include", "share")[index % 4]
                (package / part / ("file-%04d" % index)).write_text("fixture")
        (root / "external-link").symlink_to(sentinel)
        expected_count = 1 + args.packages * (5 + args.files_per_package)
        for jobs in args.jobs:
            reset(root)
            for phase, mode in (("root-check", "roots"), ("repair", "handoff"), ("already-correct", "handoff")):
                started = time.monotonic()
                completed = subprocess.run([sys.executable, str(args.helper), "--mode", mode,
                    "--group", grp.getgrgid(os.getgid()).gr_name, "--jobs", str(jobs),
                    "--tree", str(root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, check=True)
                elapsed = time.monotonic() - started
                result = json.loads(completed.stdout)
                assert result["failures"] == 0, result
                if mode == "roots":
                    assert result["visited"] == 1, result
                else:
                    assert result["visited"] == expected_count, result
                    verify(root, sentinel)
                if phase == "already-correct":
                    assert result["changed"] == 0, result
                result.update(phase=phase, wall_seconds=round(elapsed, 3))
                records.append(result)
                print("{} jobs={}: {:.3f}s, visited={}, changed={}".format(
                    phase, jobs, elapsed, result["visited"], result["changed"]), file=sys.stderr)
    print(json.dumps({"platform": platform.platform(), "python": sys.version,
                      "packages": args.packages, "files_per_package": args.files_per_package,
                      "records": records}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
