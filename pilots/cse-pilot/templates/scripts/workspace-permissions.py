#!/usr/bin/env python3
"""Bounded permission maintenance for quiescent CSE generated trees (Python 3.6+)."""

import argparse
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import grp
import json
import os
import stat
import sys
import time


class PermissionErrorReport(ValueError):
    pass


def counters():
    return {"visited": 0, "changed": 0, "symlinks": 0, "mounts": 0, "failures": 0, "errors": []}


def combine(total, part):
    for key in ("visited", "changed", "symlinks", "mounts", "failures"):
        total[key] += part[key]
    total["errors"].extend(part["errors"][:max(0, 20 - len(total["errors"]))])


def problem(result, path, message):
    result["failures"] += 1
    if len(result["errors"]) < 20:
        result["errors"].append("{}: {}".format(path, message))


def inside(path, parent):
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def safe_root(path):
    if not os.path.isabs(path):
        raise PermissionErrorReport("root must be absolute: " + path)
    if ".." in path.split(os.sep):
        raise PermissionErrorReport("root must not contain '..': " + path)
    path = os.path.normpath(path)
    if path == os.sep:
        raise PermissionErrorReport("filesystem root is not a generated tree")
    current = os.sep
    for part in path.split(os.sep)[1:]:
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode):
            raise PermissionErrorReport("root resolves through a symlink: " + current)
        if not stat.S_ISDIR(info.st_mode):
            raise PermissionErrorReport("root is not a directory: " + current)
    return path


def inspect_entry(path, info, options, result):
    """Repair owned entries and verify in the same visit; never follow links."""
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        return
    result["visited"] += 1
    mode = stat.S_IMODE(info.st_mode)
    directory = stat.S_ISDIR(info.st_mode)
    expected = 0o2770 if directory else (0o770 if mode & 0o100 else 0o660)
    accepted = (0o770, 0o2770) if directory else (expected,)
    owned = info.st_uid == options["uid"]
    verify = owned or options["mode"] != "repair"
    bad = info.st_gid != options["gid"] or mode not in accepted
    if bad and owned and options["mode"] != "verify":
        try:
            # lchown/chmod(no-follow) cannot change a substituted symlink target.
            # Operators must still quiesce writers, including ancestor renames.
            if info.st_gid != options["gid"]:
                os.chown(path, -1, options["gid"], follow_symlinks=False)
            if mode not in accepted or info.st_gid != options["gid"]:
                try:
                    os.chmod(path, expected, follow_symlinks=False)
                except OSError:
                    if not directory:
                        raise
                    os.chmod(path, 0o770, follow_symlinks=False)
            info = os.lstat(path)
            result["changed"] += 1
            if stat.S_ISLNK(info.st_mode):
                raise PermissionErrorReport("entry changed to a symlink during repair")
            bad = info.st_gid != options["gid"] or stat.S_IMODE(info.st_mode) not in accepted
        except (OSError, NotImplementedError, PermissionErrorReport) as error:
            problem(result, path, str(error))
            return
    if verify and bad:
        problem(result, path, "does not satisfy the restricted group contract (owner uid {}); "
                "the owner must run permissions after stopping writers".format(info.st_uid))
    if options["mode"] == "roots" and not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        problem(result, path, "root is not readable/writable/searchable by this builder")


def scan_directory(task, options):
    path, device = task
    result = counters()
    children = []
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            result["symlinks"] += 1
            return result, children
        if info.st_dev != device:
            result["mounts"] += 1
            return result, children
        if not stat.S_ISDIR(info.st_mode):
            raise PermissionErrorReport("directory changed during traversal")
        inspect_entry(path, info, options, result)
        with os.scandir(path) as entries:
            for entry in entries:
                if any(inside(entry.path, excluded) for excluded in options["exclude"]):
                    continue
                entry_info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_info.st_mode):
                    result["symlinks"] += 1
                elif entry_info.st_dev != device:
                    result["mounts"] += 1
                elif stat.S_ISDIR(entry_info.st_mode):
                    children.append((entry.path, device))
                else:
                    inspect_entry(entry.path, entry_info, options, result)
    except (OSError, PermissionErrorReport) as error:
        problem(result, path, str(error))
    return result, children


def walk_task(payload):
    task, options = payload
    pending = [task]
    result = counters()
    while pending:
        part, children = scan_directory(pending.pop(), options)
        combine(result, part)
        pending.extend(children)
    return result


def maintain(trees, roots, excluded, group, mode, jobs, create=()):
    if not 1 <= jobs <= 32:
        raise PermissionErrorReport("permission jobs must be between 1 and 32")
    gid = grp.getgrnam(group).gr_gid
    trees = sorted(set(safe_root(path) for path in trees), key=len)
    roots = sorted(set(safe_root(path) for path in roots), key=len)
    excluded = sorted(set(safe_root(path) for path in excluded), key=len)
    create = [safe_root(path) for path in create]
    # Do not allow a generated surface to opt itself back into an excluded store.
    for path in trees:
        if any(inside(path, item) for item in excluded):
            raise PermissionErrorReport("generated tree overlaps a protected store/private root: " + path)
    for path in create:
        if mode != "roots" or path not in trees + roots:
            raise PermissionErrorReport("creation is restricted to declared startup roots")
        os.makedirs(path, mode=0o2770, exist_ok=True)
    devices = {}
    for path in set(trees + roots):
        try:
            devices[path] = os.lstat(path).st_dev
        except FileNotFoundError:
            devices[path] = None
    selected = []
    for path in trees:
        # An explicitly declared nested filesystem is its own traversal root.
        if not any(inside(path, parent) and devices[path] == devices[parent] for parent in selected):
            selected.append(path)
    options = {"uid": os.geteuid(), "gid": gid, "mode": mode, "exclude": excluded}
    result = counters()
    if mode == "roots":
        roots = sorted(set(roots + trees))
        selected = []
    else:
        roots = [path for path in roots if not any(inside(path, tree) and devices[path] == devices[tree]
                                                  for tree in selected)
                 or path in excluded]
    for path in roots:
        try:
            inspect_entry(path, os.lstat(path), options, result)
        except FileNotFoundError:
            continue  # A view/module/build-cache root may not exist yet.
        except OSError as error:
            problem(result, path, str(error))
    pending = deque()
    for path in selected:
        try:
            pending.append((path, os.lstat(path).st_dev))
        except FileNotFoundError:
            continue
        except OSError as error:
            problem(result, path, str(error))
    # Split once into disjoint subtrees. Common ancestors and files directly in
    # them are handled by the coordinator, never once per worker.
    while pending and len(pending) < jobs:
        part, children = scan_directory(pending.popleft(), options)
        combine(result, part)
        pending.extend(children)
    if jobs == 1:
        for task in pending:
            combine(result, walk_task((task, options)))
    elif pending:
        kwargs = {"max_workers": jobs}
        if sys.version_info >= (3, 7):
            # This single-threaded Unix CLI can safely fork. Python 3.6 already
            # defaults to fork here; newer versions expose explicit mp_context.
            kwargs["mp_context"] = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(**kwargs) as pool:
            for part in pool.map(walk_task, ((task, options) for task in pending)):
                combine(result, part)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("roots", "repair", "handoff", "verify"), required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--tree", action="append", default=[])
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--exclude-tree", action="append", default=[])
    parser.add_argument("--create-root", action="append", default=[])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        result = maintain(args.tree, args.root, args.exclude_tree, args.group, args.mode, args.jobs, args.create_root)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print("cse-build: permission maintenance failed: {}".format(error), file=sys.stderr)
        return 2
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["jobs"] = args.jobs
    for error in result["errors"]:
        print("cse-build: " + error, file=sys.stderr)
    if not args.quiet:
        print(json.dumps(result, sort_keys=True))
    return 2 if result["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
