#!/usr/bin/env python3
"""Preview Tcl module presentation from existing CSE locks and installations.

The operator process uses only the standard library. A child of the recorded
Spack executable supplies its own YAML, configuration and module writer APIs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


class PreviewError(ValueError):
    pass


def inside(path, root):
    return path == root or root in path.parents


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(workspace):
    files = list(workspace.glob("environments/*/*/spack.yaml"))
    files += list(workspace.glob("environments/*/*/spack.lock"))
    for name in ("configs", "catalog", "package-repos", "modulefiles", "presentation"):
        files += [p for p in (workspace / name).rglob("*") if p.is_file()]
    return {str(p): digest(p) for p in sorted(files)}


def selected_environments(workspace, requested):
    available = {str(p.parent.relative_to(workspace / "environments"))
                 for p in workspace.glob("environments/*/*/spack.yaml")}
    selected = sorted(set(requested) if requested else available)
    if not selected:
        raise PreviewError("No recorded environments found")
    for name in selected:
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+/[A-Za-z0-9_.+-]+", name) or name not in available:
            raise PreviewError("Unknown environment: " + name)
        lock = workspace / "environments" / name / "spack.lock"
        if not lock.is_file():
            raise PreviewError("Missing existing lock: " + str(lock) + "; finish the build first")
    return selected


def isolated_environment(output):
    environment = os.environ.copy()
    for key in ("SPACK_ENV", "SPACK_ENV_VIEW", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(key, None)
    environment.update({
        "SPACK_DISABLE_LOCAL_CONFIG": "true",
        "SPACK_USER_CONFIG_PATH": str(output / "state/user-config"),
        "SPACK_SYSTEM_CONFIG_PATH": str(output / "state/system-config"),
        "SPACK_USER_CACHE_PATH": str(output / "state/user-cache"),
        "SPACK_MISC_CACHE_PATH": str(output / "state/misc-cache"),
    })
    return environment


def run_worker(spack, env_dir, request, output, phase):
    token = request["environment"].replace("/", "--")
    request_path = output / "state" / (token + "-" + phase + "-request.json")
    response_path = output / "state" / (token + "-" + phase + "-response.json")
    request = dict(request, phase=phase, response=str(response_path))
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request, indent=2) + "\n")
    command = [str(spack), "-e", str(env_dir), "python", str(Path(__file__).resolve()),
               "--worker", str(request_path)]
    result = subprocess.run(command, env=isolated_environment(output), universal_newlines=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log = output / "state" / (token + "-" + phase + ".log")
    log.write_text(result.stdout)
    if result.returncode:
        raise PreviewError("Spack " + phase + " failed for " + request["environment"]
                           + "; see " + str(log) + "\n" + result.stdout.strip())
    if not response_path.is_file():
        raise PreviewError("Spack did not produce its preview report; see " + str(log))
    return json.loads(response_path.read_text())


def presentation_files(source, modules_root, destination):
    if not source.is_dir():
        raise PreviewError("Missing entrance/lane tree: " + str(source)
                           + "; review a presentation candidate or refresh --scope presentation")
    result = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise PreviewError("Presentation symlinks are unsupported: " + str(path))
        if path.is_file():
            relative = str(path.relative_to(source))
            body = path.read_text()
            # CSE templates contain an absolute module root, followed by / or a
            # Tcl delimiter. Never replace a prefix of a different directory.
            pattern = re.escape(str(modules_root)) + r'(?=/|[\s"};]|$)'
            result[relative] = re.sub(pattern, lambda _: str(destination), body)
    if not result:
        raise PreviewError("Empty entrance/lane tree; review --scope presentation first")
    return result


def preview(*, workspace, output, modules_root, spack, environments=None,
            policy_tree=None, presentation_tree=None, check_only=False):
    workspace, output = workspace.resolve(), output.absolute()
    if not modules_root.is_absolute() or str(modules_root) == "/":
        raise PreviewError("Use the recorded absolute package-module root")
    if re.search(r'[\s\[\]{}$;"\\]', str(output) + str(modules_root)):
        raise PreviewError("Tcl presentation roots must avoid whitespace and Tcl metacharacters")
    if output.exists() or output.is_symlink():
        raise PreviewError("Preview output must be new; retain prior iterations: " + str(output))
    output = output.resolve()
    for protected in (workspace, modules_root.resolve()):
        if inside(output, protected) or inside(protected, output):
            raise PreviewError("Preview output overlaps the workspace or current module root")
    selected = selected_environments(workspace, environments)
    source = (presentation_tree or workspace / "modulefiles").resolve()
    presentation = presentation_files(source, modules_root, output / "modulefiles")
    protected = snapshot(workspace)
    staging = Path(tempfile.mkdtemp(prefix="cse-module-preview-"))
    report = {"schema_version": 1, "status": "checking", "workspace": str(workspace),
              "modules_root": str(modules_root), "preview": str(output),
              "spack": str(spack.resolve()), "check_only": check_only,
              "environments": {}, "source_sha256": protected,
              "capabilities": {"composer_required": False, "controls_refresh_required": False,
                               "existing_views_only": True, "module_type": "tcl"}}
    status = staging / "preview.json"
    try:
        plans = {}
        filenames = {str(output / "modulefiles" / name): "presentation" for name in presentation}
        for name in selected:
            policy = None
            if policy_tree:
                policy = (policy_tree / name / "modules.yaml").resolve()
                if not policy.is_file():
                    raise PreviewError("Missing reviewed policy: " + str(policy))
            request = {"environment": name, "workspace": str(workspace),
                       "output": str(output), "record_directory": str(staging),
                       "modules_root": str(modules_root), "policy": str(policy) if policy else None}
            info = run_worker(spack, workspace / "environments" / name, request, staging, "check")
            for item in info["modules"]:
                filename = item["filename"]
                if filename in filenames:
                    raise PreviewError("Module filename collision: " + filename
                                       + " (" + filenames[filename] + ", " + name + ")")
                if not inside(Path(filename).resolve(), output / "modulefiles"):
                    raise PreviewError("Module projection escapes preview: " + filename)
                filenames[filename] = name
            plans[name] = dict(request, expected_modules=info["modules"],
                               expected_policy_sha256=info["policy_sha256"],
                               policy=str(output / "policies" / name / "modules.yaml"))
            report["environments"][name] = info
        if snapshot(workspace) != protected:
            raise PreviewError("Workspace inputs changed during preflight; start a new preview")
        report["capabilities"]["legacy_entrance_variables"] = [
            name for name, text in presentation.items()
            if name.startswith("cse/") and "setenv CSE_COMPILER " not in text]
        available = selected_environments(workspace, None) if not environments else sorted(
            str(path.parent.relative_to(workspace / "environments"))
            for path in workspace.glob("environments/*/*/spack.yaml"))
        report["capabilities"]["omitted_environments"] = sorted(set(available) - set(selected))
        output.mkdir(parents=True, mode=0o700)
        status = output / "preview.json"
        shutil.copytree(staging / "state", output / "state")
        shutil.copytree(staging / "policies", output / "policies")
        if not check_only:
            for name, body in presentation.items():
                target = output / "modulefiles" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body)
            # Keep editable entrance/lane inputs separate from package output.
            shutil.copytree(source, output / "presentation")
            for name in selected:
                plans[name]["record_directory"] = str(output)
                info = run_worker(spack, workspace / "environments" / name,
                                  plans[name], output, "generate")
                if info["modules"] != plans[name]["expected_modules"]:
                    raise PreviewError("Module plan changed during generation: " + name)
        if snapshot(workspace) != protected:
            raise PreviewError("Workspace inputs changed during preview; discard this candidate")
        report["status"] = "checked" if check_only else "generated"
        shutil.rmtree(staging)
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        print("Preview failure record: " + str(status), file=sys.stderr)
        raise
    finally:
        status.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def worker(request_path):
    """Run only through the pinned Spack Python command; never modify its env."""
    import spack
    import spack.config
    import spack.environment
    import spack.modules.common
    import spack.modules.tcl
    import spack.paths
    import spack.repo
    import spack.store
    import spack.util.spack_yaml as syaml

    request = json.loads(request_path.read_text())
    if str(spack.spack_version) != "1.2.2":
        raise PreviewError("This preview helper is qualified for Spack 1.2.2; got "
                           + str(spack.spack_version) + ". Keep the recorded runtime; "
                           "qualify the helper before using another version.")
    environment = spack.environment.active_environment()
    if environment is None:
        raise PreviewError("No active recorded Spack environment")
    scope_records, workspace_include = [], False
    workspace = Path(request["workspace"])
    defaults = Path(spack.paths.etc_path).resolve() / "defaults"
    for scope in spack.config.CONFIG.active_scopes:
        if re.match(r"^(user|system|site)(/|$)", scope.name):
            raise PreviewError("Unexpected active ambient Spack scope: " + scope.name
                               + "; use the recorded isolated workspace includes")
        path = Path(scope.path).resolve() if hasattr(scope, "path") else None
        if scope.included and path:
            if inside(path, workspace):
                workspace_include = True
            elif not inside(path, defaults):
                raise PreviewError("Unexpected active include outside workspace: " + str(path))
        scope_records.append({"name": scope.name, "path": str(path) if path else None})
    if not workspace_include:
        raise PreviewError("No active workspace include scope; review the retained environment's include::")
    output = Path(request["output"])
    for root in (spack.store.STORE.root, spack.store.STORE.unpadded_root):
        root = Path(root).resolve()
        if inside(output, root) or inside(root, output):
            raise PreviewError("Preview output overlaps the installation store")
    specs = list(environment.all_specs())
    missing = [str(spec) for spec in specs
               if not spec.external and (not spec.installed or not Path(str(spec.prefix)).is_dir())]
    if missing:
        raise PreviewError("Missing installed locked prefixes; finish this environment first: "
                           + ", ".join(missing))
    if not specs:
        raise PreviewError("The existing lock contains no concrete specs")
    if request["policy"]:
        with open(request["policy"]) as handle:
            document = syaml.load_config(handle)
        if not isinstance(document, dict) or set(document) != {"modules"}:
            raise PreviewError("Reviewed policy must contain only a modules mapping")
        policy = document["modules"]
    else:
        policy = spack.config.get("modules")
    if not isinstance(policy, dict):
        raise PreviewError("Missing module policy; review refresh --scope module-policy")
    # Round-trip with Spack's YAML implementation retains its override semantics.
    original = syaml.dump_config({"modules": policy})
    policy_hash = hashlib.sha256(original.encode()).hexdigest()
    if request.get("expected_policy_sha256", policy_hash) != policy_hash:
        raise PreviewError("Module policy changed after preflight; start a new preview")
    policy = syaml.load_config(original)["modules"]
    output, recorded_root = Path(request["output"]), Path(request["modules_root"])
    sets, views = [], {}
    for name, descriptor in environment.views.items():
        root = Path(descriptor.root).resolve()
        if inside(output, root) or inside(root, output):
            raise PreviewError("Preview output overlaps an existing view")
    for name, config in policy.items():
        if name == "prefix_inspections":
            continue
        if not isinstance(config, dict):
            raise PreviewError("Invalid module set: " + str(name))
        if not config.get("enable"):
            continue
        if config["enable"] != ["tcl"]:
            raise PreviewError("Preview currently supports Tcl module sets only: " + str(name))
        raw_root = config.get("roots", {}).get("tcl")
        if not isinstance(raw_root, str) or not Path(raw_root).is_absolute() or "$" in raw_root:
            raise PreviewError("Missing explicit Tcl root in " + str(name)
                               + "; review refresh --scope module-policy")
        try:
            relative = Path(raw_root).relative_to(recorded_root)
        except ValueError as error:
            raise PreviewError("Module root is outside the recorded package-module root: "
                               + raw_root) from error
        if ".." in relative.parts:
            raise PreviewError("Module root contains traversal: " + raw_root)
        config["roots"] = {"tcl": str(output / "modulefiles" / relative)}
        use_view = config.get("use_view", False)
        if use_view:
            view_name = "default" if use_view is True else use_view
            if not isinstance(view_name, str) or not environment.has_view(view_name):
                raise PreviewError("Missing named view " + str(view_name)
                                   + "; review refresh --scope module-policy")
            root = Path(environment.views[view_name].root)
            if not root.is_dir():
                raise PreviewError("Required existing view is absent: " + str(root)
                                   + "; generate it deliberately before preview")
            if inside(output, root.resolve()) or inside(root.resolve(), output):
                raise PreviewError("Preview output overlaps an existing view")
            views[view_name] = str(root)
        sets.append(name)
    if not sets:
        raise PreviewError("No enabled Tcl module sets; review refresh --scope module-policy")
    for spec in specs:
        prefix = Path(str(spec.prefix)).resolve()
        if inside(output, prefix) or inside(prefix, output):
            raise PreviewError("Preview output overlaps an installed prefix")
    writers, modules, seen = [], [], set()
    scope = spack.config.InternalConfigScope("cse-module-preview", {"modules:": policy})
    with spack.config.override(scope):
        for name in sorted(sets):
            for spec in specs:
                if spec.external:
                    continue
                if not spack.repo.PATH.exists(spec.name):
                    raise PreviewError("Recipe unavailable for locked package: " + spec.name)
                writer = spack.modules.tcl.TclModulefileWriter(spec, name)
                if writer.conf.excluded:
                    continue
                filename = Path(writer.layout.filename).resolve()
                if not inside(filename, output / "modulefiles"):
                    raise PreviewError("Module projection escapes preview: " + str(filename))
                if filename.name in ("module-index.yaml", ".modulerc", ".version"):
                    raise PreviewError("Module projection uses a reserved filename: " + str(filename))
                if str(filename) in seen:
                    raise PreviewError("Module filename collision: " + str(filename))
                seen.add(str(filename))
                writers.append(writer)
                modules.append({"set": name, "spec": str(spec), "hash": spec.dag_hash(),
                                "prefix": str(spec.prefix), "filename": str(filename)})
        if not modules:
            raise PreviewError("Policy selected no installed package modules; review its include filters")
        if request["phase"] == "generate":
            if modules != request["expected_modules"]:
                raise PreviewError("Inputs changed after preflight; start a new preview")
            for writer in writers:
                if Path(writer.layout.filename).exists():
                    raise PreviewError("Refusing to overwrite preview module: " + writer.layout.filename)
                writer.write(overwrite=False)
                if not Path(writer.layout.filename).is_file():
                    raise PreviewError("Spack did not write module: " + writer.layout.filename)
            roots = {writer.layout.dirname() for writer in writers}
            for root in roots:
                spack.modules.common.generate_module_index(
                    root, [writer for writer in writers if writer.layout.dirname() == root],
                    overwrite=False)
    editable = Path(request["record_directory"]) / "policies" / request["environment"] / "modules.yaml"
    editable.parent.mkdir(parents=True, exist_ok=True)
    editable.write_text(original)
    report = {"modules": modules, "sets": sorted(sets), "views": views, "scopes": scope_records,
              "spack_version": str(spack.spack_version),
              "policy_sha256": policy_hash}
    Path(request["response"]).write_text(json.dumps(report, indent=2) + "\n")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=os.environ.get("CSE_BUILD_WORKSPACE"))
    parser.add_argument("--output", type=Path, help="new private iteration directory")
    parser.add_argument("--modules-root", type=Path, default=os.environ.get("CSE_MODULES_ROOT"))
    default_spack = str(Path(os.environ["SPACK_ROOT"]) / "bin/spack") if os.environ.get("SPACK_ROOT") else shutil.which("spack")
    parser.add_argument("--spack", type=Path, default=default_spack)
    parser.add_argument("--environment", action="append", dest="environments")
    parser.add_argument("--policy-tree", type=Path, help="reviewed <compiler>/<kind>/modules.yaml files")
    parser.add_argument("--presentation-tree", type=Path, help="reviewed compiler entrances and lane files")
    parser.add_argument("--check-only", action="store_true", help="check prerequisites without generating modules")
    args = parser.parse_args()
    if not args.workspace or not args.modules_root or not args.spack:
        parser.error("use the existing prepared CSE shell, or supply --workspace, --modules-root and --spack")
    if not args.output and not args.check_only:
        parser.error("--output must name a new preview directory")
    temporary = None
    if not args.output:
        temporary = tempfile.TemporaryDirectory(prefix="cse-module-check-")
        args.output = Path(temporary.name) / "check"
    try:
        support_path = Path(__file__).with_name("workspace-build.py")
        support_spec = importlib.util.spec_from_file_location("cse_preview_maintenance", str(support_path))
        support = importlib.util.module_from_spec(support_spec)
        support_spec.loader.exec_module(support)
        with support.maintenance_lock(args.workspace):
            report = preview(**vars(args))
        count = sum(len(info["modules"]) for info in report["environments"].values())
        print(report["status"] + ": " + str(count) + " package modules across "
              + str(len(report["environments"])) + " environments")
        print("Existing controls suffice for this preview; no Composer refresh is required.")
        if report["capabilities"]["legacy_entrance_variables"]:
            print("Older entrances omit CSE_COMPILER; use the explicit compiler lane path.")
        if report["capabilities"]["omitted_environments"]:
            print("Partial preview: omitted " + ", ".join(report["capabilities"]["omitted_environments"])
                  + ". Test package naming directly; full lane tests need its Core/Common/provider modules.")
        if not temporary:
            print("Review record: " + str(args.output / "preview.json"))
            if not args.check_only:
                print("Clean consumer shell: module use " + str(args.output / "modulefiles"))
        return 0
    except (PreviewError, OSError, ValueError) as error:
        print("module-preview: " + str(error), file=sys.stderr)
        return 2
    finally:
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
