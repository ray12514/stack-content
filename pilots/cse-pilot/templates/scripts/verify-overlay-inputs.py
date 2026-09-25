#!/usr/bin/env python3
"""Check reviewed local recipe bytes without importing recipes or running Spack."""

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath


INVENTORY = "overlay-inventory.json"


def relative_path(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or any(part in ("", ".", "..") for part in value.split("/"))
            or PurePosixPath(value).is_absolute()):
        raise ValueError("unsafe inventory path: {!r}".format(value))
    return value


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate inventory field: {}".format(name))
        result[name] = value
    return result


def validate_inventory(inventory):
    if (not isinstance(inventory, dict)
            or set(inventory) != {"schema_version", "repositories"}
            or inventory["schema_version"] != 1):
        raise ValueError("unsupported overlay inventory schema")
    repositories = inventory["repositories"]
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("incomplete overlay inventory: repositories required")
    paths, namespaces = set(), set()
    for repository in repositories:
        if (not isinstance(repository, dict)
                or set(repository) != {"path", "namespace", "api", "files"}):
            raise ValueError("incomplete overlay repository identity")
        path = relative_path(repository["path"])
        namespace = repository["namespace"]
        if (not isinstance(namespace, str)
                or not re.fullmatch(r"[A-Za-z_]\w*", namespace)
                or repository["api"] != "v2.0"):
            raise ValueError("unsupported overlay repository identity")
        if (namespace in namespaces or path in paths
                or any(path.startswith(old + "/") or old.startswith(path + "/")
                       for old in paths)):
            raise ValueError("duplicate or overlapping overlay repository identity")
        paths.add(path)
        namespaces.add(namespace)
        files = repository["files"]
        if not isinstance(files, dict) or "repo.yaml" not in files:
            raise ValueError("incomplete overlay inventory: repo.yaml required")
        if not any(re.fullmatch(r"packages/[^/]+/package.py", name) for name in files):
            raise ValueError("incomplete overlay inventory: package recipes required")
        for name, digest in files.items():
            relative_path(name)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid SHA-256 digest for {}".format(name))
    return inventory


def repository_identity(path):
    # The portable gate supports the small API-v2 repo.yaml declaration shipped
    # here. Richer YAML needs an explicitly extended parser, never a guessed identity.
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line:
            continue
        if line == "repo:" and not fields:
            fields["repo"] = True
            continue
        match = re.fullmatch(r"  (namespace|api): ([A-Za-z_][\w.]*)", line)
        if not match or match.group(1) in fields or not fields.get("repo"):
            raise ValueError("unsupported repository identity declaration: {}".format(path))
        fields[match.group(1)] = match.group(2)
    if set(fields) != {"repo", "namespace", "api"}:
        raise ValueError("incomplete repository identity: {}".format(path))
    return fields["namespace"], fields["api"]


def scan_files(root):
    if root.is_symlink():
        raise ValueError("overlay root is a symlink: {}".format(root))
    if not root.is_dir():
        raise ValueError("overlay input root missing: {}".format(root))
    files = {}
    def walk_error(error):
        raise error
    for directory, directories, names in os.walk(str(root), onerror=walk_error):
        for name in directories + names:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("overlay input symlink is unsupported: {}".format(path))
        for name in names:
            path = Path(directory) / name
            if not path.is_file():
                raise ValueError("overlay input is not a regular file: {}".format(path))
            relative = path.relative_to(root).as_posix()
            if relative != INVENTORY:
                files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def snapshot(root):
    files = scan_files(root)
    repositories = []
    remaining = set(files)
    for name in sorted(files):
        if not name.endswith("/repo.yaml"):
            continue
        path = name.rsplit("/", 1)[0]
        namespace, api = repository_identity(root / name)
        members = {key[len(path) + 1:]: digest for key, digest in files.items()
                   if key.startswith(path + "/")}
        package_names = {key.split("/")[1] for key in members
                         if key.startswith("packages/") and len(key.split("/")) >= 3}
        for package in package_names:
            recipe = "packages/{}/package.py".format(package)
            if recipe not in members:
                raise ValueError("overlay recipe missing: {}/packages/{}/package.py".format(path, package))
            validate_local_support(root / path / recipe, recipe, members)
        repositories.append({"path": path, "namespace": namespace, "api": api, "files": members})
        remaining.difference_update(path + "/" + key for key in members)
    if remaining:
        raise ValueError("unrecorded input outside an identified repository: {}".format(
            ", ".join(sorted(remaining))))
    return validate_inventory({"schema_version": 1, "repositories": repositories})


def validate_local_support(path, recipe, members):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        raise ValueError("overlay recipe syntax error: {}".format(error))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", None))
        if name != "patch":
            continue
        try:
            reference = ast.literal_eval(node.args[0]) if node.args else None
        except (ValueError, TypeError):
            reference = None
        if not isinstance(reference, str):
            raise ValueError("unsupported dynamic patch reference: {}:{}".format(path, node.lineno))
        if reference.startswith(("https://", "http://")):
            continue
        relative_path(reference)
        support = str(PurePosixPath(recipe).parent / reference)
        if support not in members:
            raise ValueError("local support file missing: {} references {}".format(path, reference))


def check(root):
    inventory_path = root / INVENTORY
    if not inventory_path.is_file():
        return ["unsupported overlay identity: missing {}; explicit candidate "
                "preparation and inventory review required".format(inventory_path)]
    try:
        if inventory_path.is_symlink():
            raise ValueError("overlay inventory is a symlink: {}".format(inventory_path))
        inventory = validate_inventory(json.loads(
            inventory_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object))
        actual = snapshot(root)
        errors = []
        expected_files, actual_files = {}, {}
        expected_identity, actual_identity = {}, {}
        for document, files, identities in ((inventory, expected_files, expected_identity),
                                            (actual, actual_files, actual_identity)):
            for repository in document["repositories"]:
                path = repository["path"]
                identities[path] = (repository["namespace"], repository["api"])
                files.update((path + "/" + name, digest)
                             for name, digest in repository["files"].items())
        if expected_identity != actual_identity:
            errors.append("overlay repository identity differs from reviewed inventory")
        for name in sorted(set(expected_files) | set(actual_files)):
            if name not in expected_files:
                errors.append("overlay input unrecorded: " + name)
            elif name not in actual_files:
                errors.append("overlay input missing: " + name)
            elif expected_files[name] != actual_files[name]:
                errors.append("overlay input changed: " + name)
        return errors
    except (OSError, ValueError, KeyError, TypeError) as error:
        return ["invalid overlay inventory or inputs: {}".format(error)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1] / "package-repos")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="check the reviewed inventory (default)")
    mode.add_argument("--candidate", type=Path,
                      help="write a new inventory outside the input tree for manual review")
    mode.add_argument("--cache-key", action="store_true",
                      help="verify inputs and print a cache key for resolved repo paths and reviewed inventory")
    parser.add_argument("--allow-unverified", action="store_true",
                        help="allow an isolated inspection cache when inventory checks fail")
    args = parser.parse_args()
    if args.allow_unverified and not args.cache_key:
        parser.error("--allow-unverified requires --cache-key")
    if args.candidate is not None:
        try:
            try:
                args.candidate.resolve().relative_to(args.root.resolve())
            except ValueError:
                pass
            else:
                raise ValueError("candidate must be outside the package-repos input tree")
            inventory = snapshot(args.root)
            # Exclusive creation never overwrites an earlier review candidate.
            with args.candidate.open("x", encoding="utf-8") as stream:
                json.dump(inventory, stream, indent=2, sort_keys=True)
                stream.write("\n")
        except (OSError, ValueError) as error:
            print("ERROR: {}".format(error), file=sys.stderr)
            return 1
        print("Candidate written to {}; review the complete file diff and inventory "
              "before explicitly adopting it. No admitted inventory changed.".format(args.candidate))
        return 0
    errors = check(args.root)
    for error in errors:
        print(("WARNING: " if args.allow_unverified else "ERROR: ") + error, file=sys.stderr)
    if errors:
        if args.allow_unverified:
            # This cache never shares the verified inventory namespace. Include
            # current bytes so successive intentional edits cannot reuse metadata.
            try:
                state = {"root": str(args.root.resolve()), "files": scan_files(args.root)}
            except (OSError, ValueError):
                state = {"root": str(args.root.resolve()), "errors": errors}
            key = hashlib.sha256(json.dumps(state, sort_keys=True).encode("utf-8")).hexdigest()
            print("Inspection cache selected; register intentional changes with "
                  "cse-build login overlay reconcile --package NAME. "
                  "cse-build work commands still require a matching inventory.", file=sys.stderr)
            print("inspection-" + key)
            return 0
        return 1
    if args.cache_key:
        try:
            inventory_bytes = (args.root / INVENTORY).read_bytes()
            inventory = json.loads(inventory_bytes.decode("utf-8"))
            identity = {
                "schema_version": 1,
                "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
                "repository_paths": sorted(str((args.root / repo["path"]).resolve())
                                           for repo in inventory["repositories"]),
            }
            print(hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest())
        except (OSError, ValueError, KeyError, TypeError) as error:
            print("ERROR: could not identify overlay cache: {}".format(error), file=sys.stderr)
            return 1
        return 0
    print("Overlay byte inventory passed; Spack selection/import remains a separate check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
