from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "templates/scripts/module-preview.py"
loader = importlib.util.spec_from_file_location("module_preview", SCRIPT)
assert loader and loader.loader
preview = importlib.util.module_from_spec(loader)
loader.loader.exec_module(preview)


@pytest.fixture
def installed_workspace(tmp_path, monkeypatch):
    """Exercise the public preview with an injectable Spack writer boundary."""
    workspace = tmp_path / "workspace"
    existing = tmp_path / "published-modules"
    existing.mkdir()
    (existing / "untouched").write_text("accepted module output\n")
    views = tmp_path / "views"
    views.mkdir()
    (views / "sentinel").write_text("existing view\n")
    prefix = tmp_path / "store/demo"
    prefix.mkdir(parents=True)
    state = {"installed": True, "prefix": prefix, "views": views, "fail_write": False,
             "spec_name": "demo", "commands": []}
    for name in ("gcc/core", "gcc/serial"):
        env = workspace / "environments" / name
        env.mkdir(parents=True)
        (env / "spack.yaml").write_text("spack:\n  specs: [demo]\n  view: false\n")
        (env / "spack.lock").write_bytes(b"unchanged concrete lock\n")
        config = workspace / "configs/environments" / name / "modules.yaml"
        config.parent.mkdir(parents=True)
        config.write_text(yaml.safe_dump({"modules": {"default": {
            "enable": ["tcl"], "use_view": "cse_modules", "arch_folder": False,
            "roots": {"tcl": str(existing / name)},
            "tcl": {"projections": {"all": "{name}/{version}"}, "all": {"autoload": "none"}}
        }}}))
    entrance = workspace / "modulefiles/cse/init-GCC"
    entrance.parent.mkdir(parents=True)
    entrance.write_text("#%Module1.0\nsetenv CSE_COMPILER gcc\n"
                        + "".join("prepend-path MODULEPATH " + str(existing / "gcc" / kind) + "\n"
                                  for kind in ("core", "common", "lanes")))
    lane = workspace / "modulefiles/gcc/lanes/Serial"
    lane.parent.mkdir(parents=True)
    lane.write_text("#%Module1.0\nprepend-path MODULEPATH " + str(existing) + "/gcc/serial\n")

    modules = {}
    for name in ("spack", "spack.config", "spack.environment", "spack.modules",
                 "spack.modules.common", "spack.modules.tcl", "spack.paths", "spack.repo",
                 "spack.store", "spack.util",
                 "spack.util.spack_yaml"):
        modules[name] = types.ModuleType(name)
        monkeypatch.setitem(sys.modules, name, modules[name])
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(modules[parent], child, modules[name])
    modules["spack"].spack_version = "1.2.2"
    modules["spack.paths"].etc_path = str(tmp_path / "spack/etc/spack")
    modules["spack.store"].STORE = types.SimpleNamespace(
        root=str(tmp_path / "store"), unpadded_root=str(tmp_path / "store"))
    state["scopes"] = [types.SimpleNamespace(name="workspace-include", included=True,
                                            path=str(workspace / "configs"))]
    modules["spack.config"].CONFIG = types.SimpleNamespace(active_scopes=state["scopes"])

    class Spec:
        external = False
        name = "demo"
        version = "1.0"

        @property
        def installed(self):
            return state["installed"]

        @property
        def prefix(self):
            return state["prefix"]

        def dag_hash(self):
            return "abc123"

        def __str__(self):
            return "demo@1.0/abc123"

    def active():
        return types.SimpleNamespace(
            all_specs=lambda: [Spec()], has_view=lambda name: name == "cse_modules",
            views={"cse_modules": types.SimpleNamespace(root=str(state["views"]))})

    modules["spack.environment"].active_environment = active
    modules["spack.repo"].PATH = types.SimpleNamespace(exists=lambda name: True)
    modules["spack.util.spack_yaml"].load_config = yaml.safe_load
    modules["spack.util.spack_yaml"].dump_config = yaml.safe_dump
    modules["spack.config"].get = lambda key: state["policy"]

    class InternalConfigScope:
        def __init__(self, name, data):
            assert name == "cse-module-preview"
            assert set(data) == {"modules:"}
            self.data = data

    modules["spack.config"].InternalConfigScope = InternalConfigScope

    @contextmanager
    def override(scope):
        assert isinstance(scope, InternalConfigScope)
        old = state["policy"]
        state["policy"] = scope.data["modules:"]
        try:
            yield
        finally:
            state["policy"] = old

    modules["spack.config"].override = override

    class Writer:
        def __init__(self, spec, name):
            self.spec = spec
            self.config = state["policy"][name]
            self.conf = types.SimpleNamespace(excluded=self.config.get("exclude_all", False))
            root = self.config["roots"]["tcl"]
            projection = self.config["tcl"]["projections"]["all"]
            self.layout = types.SimpleNamespace(
                filename=str(Path(root) / projection.format(name=spec.name, version=spec.version)),
                dirname=lambda: root)

        def write(self, overwrite):
            assert overwrite is False
            if state["fail_write"]:
                raise OSError("injected module write failure")
            file = Path(self.layout.filename)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("#%Module1.0\n# " + json.dumps(self.config["tcl"]) + "\n")

    modules["spack.modules.tcl"].TclModulefileWriter = Writer
    modules["spack.modules.common"].generate_module_index = lambda *args, **kwargs: None

    def run(spack, env_dir, request, output, phase):
        state["commands"].append((request["environment"], phase))
        state["policy"] = yaml.safe_load(
            (workspace / "configs/environments" / request["environment"] / "modules.yaml").read_text()
        )["modules"]
        output.joinpath("state").mkdir(parents=True, exist_ok=True)
        response = output / "state" / (request["environment"].replace("/", "-") + phase + ".json")
        payload = output / "state/request.json"
        payload.write_text(json.dumps(dict(request, phase=phase, response=str(response))))
        preview.worker(payload)
        return json.loads(response.read_text())

    monkeypatch.setattr(preview, "run_worker", run)
    options = {"workspace": workspace, "output": tmp_path / "iteration-1",
               "modules_root": existing, "spack": tmp_path / "spack/bin/spack"}
    return options, state


def test_preview_keeps_locks_and_publication_while_redirecting_lane_and_package_output(installed_workspace):
    options, state = installed_workspace
    before = preview.snapshot(options["workspace"])
    result = preview.preview(**options)
    assert result["status"] == "generated"
    assert preview.snapshot(options["workspace"]) == before
    assert (options["modules_root"] / "untouched").read_text() == "accepted module output\n"
    assert list(options["modules_root"].iterdir()) == [options["modules_root"] / "untouched"]
    assert (state["views"] / "sentinel").read_text() == "existing view\n"
    assert state["commands"] == [("gcc/core", "check"), ("gcc/serial", "check"),
                                  ("gcc/core", "generate"), ("gcc/serial", "generate")]
    for environment in ("gcc/core", "gcc/serial"):
        assert (options["output"] / "modulefiles" / environment / "demo/1.0").is_file()
    lane = (options["output"] / "modulefiles/gcc/lanes/Serial").read_text()
    assert str(options["output"] / "modulefiles/gcc/serial") in lane
    assert str(options["modules_root"]) not in lane


def test_check_only_and_selection_require_no_generated_module_output(installed_workspace):
    options, state = installed_workspace
    report = preview.preview(**options, check_only=True, environments=["gcc/core"])
    assert report["status"] == "checked"
    assert state["commands"] == [("gcc/core", "check")]
    assert not (options["output"] / "modulefiles").exists()
    assert not (options["output"] / "entrances").exists()


def test_consumer_root_exposes_only_entrances_and_entrances_expose_preview_lanes(installed_workspace):
    options, _ = installed_workspace
    platform = options["workspace"] / "modulefiles/cse/init-CCE"
    platform.write_text("#%Module1.0\nprepend-path MODULEPATH "
                        + str(options["modules_root"] / "cce/lanes") + "\n")
    report = preview.preview(**options)
    root = options["output"] / "entrances"
    # Lmod walks the initial MODULEPATH recursively. It must not contain the
    # private compiler tree, otherwise lanes/packages appear before activation.
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) == [
        "cse/init-CCE", "cse/init-GCC"]
    assert report["consumer_modulepath"] == str(root)
    assert not (options["output"] / "modulefiles/cse").exists()
    for compiler, entrance in (("gcc", "init-GCC"), ("cce", "init-CCE")):
        body = (root / "cse" / entrance).read_text()
        assert str(options["output"] / "modulefiles" / compiler / "lanes") in body
        assert str(options["modules_root"]) not in body


def test_cli_points_to_entrances_without_a_manual_lane_path_for_legacy_files(
        installed_workspace, monkeypatch, capsys):
    options, _ = installed_workspace
    entrance = options["workspace"] / "modulefiles/cse/init-GCC"
    entrance.write_text(entrance.read_text().replace("setenv CSE_COMPILER gcc\n", ""))
    arguments = [str(SCRIPT)]
    for name in ("workspace", "output", "modules_root", "spack"):
        arguments += ["--" + name.replace("_", "-"), str(options[name])]
    monkeypatch.setattr(sys, "argv", arguments)
    assert preview.main() == 0
    output = capsys.readouterr().out
    assert "module use " + str(options["output"] / "entrances") in output
    assert "use the explicit compiler lane path" not in output


@pytest.mark.parametrize("missing", ["uninstalled", "prefix", "view"])
def test_missing_installations_and_views_fail_before_any_package_or_lane_output(installed_workspace, missing):
    options, state = installed_workspace
    if missing == "uninstalled":
        state["installed"] = False
    else:
        state["prefix" if missing == "prefix" else "views"] /= "missing"
    with pytest.raises(preview.PreviewError, match="Missing installed|Required existing view"):
        preview.preview(**options)
    assert not options["output"].exists()
    assert not any(phase == "generate" for _, phase in state["commands"])


def test_reviewed_projection_and_autoload_can_iterate_without_mutating_source_policy(installed_workspace):
    options, state = installed_workspace
    first = preview.preview(**options)
    policies = options["output"] / "policies"
    file = policies / "gcc/core/modules.yaml"
    policy = yaml.safe_load(file.read_text())
    policy["modules"]["default"]["tcl"]["projections"]["all"] = "{name}/{version}-compiler-tag"
    policy["modules"]["default"]["tcl"]["all"]["autoload"] = "direct"
    file.write_text(yaml.safe_dump(policy))
    second_output = options["output"].with_name("iteration-2")
    report = preview.preview(**dict(options, output=second_output), policy_tree=policies)
    assert report["status"] == "generated"
    assert (second_output / "modulefiles/gcc/core/demo/1.0-compiler-tag").is_file()
    assert (options["output"] / "modulefiles/gcc/core/demo/1.0").is_file()
    assert first["source_sha256"] == report["source_sha256"]


@pytest.mark.parametrize("kind", ["projection_escape", "root_escape", "other_sections", "empty_filter",
                                  "reserved_filename"])
def test_invalid_reviewed_policy_fails_closed_before_preview_output(installed_workspace, kind):
    options, state = installed_workspace
    tree = options["workspace"].parent / "reviewed"
    path = tree / "gcc/core/modules.yaml"
    path.parent.mkdir(parents=True)
    source = options["workspace"] / "configs/environments/gcc/core/modules.yaml"
    policy = yaml.safe_load(source.read_text())
    config = policy["modules"]["default"]
    if kind == "projection_escape":
        config["tcl"]["projections"]["all"] = "../../../../escape"
    elif kind == "root_escape":
        config["roots"]["tcl"] = "/outside"
    elif kind == "other_sections":
        policy["config"] = {"install_tree": "/different-store"}
    elif kind == "reserved_filename":
        config["tcl"]["projections"]["all"] = "module-index.yaml"
    else:
        config["exclude_all"] = True
    path.write_text(yaml.safe_dump(policy))
    with pytest.raises(preview.PreviewError):
        preview.preview(**options, policy_tree=tree, environments=["gcc/core"])
    assert not options["output"].exists()


def test_all_environments_preflight_before_any_generation_and_detect_cross_env_collisions(installed_workspace):
    options, state = installed_workspace
    path = options["workspace"] / "configs/environments/gcc/serial/modules.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["modules"]["default"]["roots"]["tcl"] = str(options["modules_root"] / "gcc/core")
    path.write_text(yaml.safe_dump(policy))
    with pytest.raises(preview.PreviewError, match="collision"):
        preview.preview(**options)
    assert not options["output"].exists()


def test_generation_error_is_failed_retained_preview_not_success(installed_workspace):
    options, state = installed_workspace
    state["fail_write"] = True
    with pytest.raises(OSError, match="injected"):
        preview.preview(**options)
    report = json.loads((options["output"] / "preview.json").read_text())
    assert report["status"] == "failed"
    assert "injected" in report["error"]
    assert (options["modules_root"] / "untouched").is_file()


@pytest.mark.parametrize("location", ["workspace", "modules_root", "prefix", "views"])
def test_output_cannot_touch_protected_trees(installed_workspace, location):
    options, state = installed_workspace
    root = options[location] if location in options else state[location]
    output = root / "new-preview"
    with pytest.raises(preview.PreviewError, match="overlap"):
        preview.preview(**dict(options, output=output))
    assert not output.exists()


def test_missing_lock_and_existing_output_are_not_overwritten(installed_workspace):
    options, state = installed_workspace
    options["output"].mkdir()
    with pytest.raises(preview.PreviewError, match="must be new"):
        preview.preview(**options)
    options["output"].rmdir()
    (options["workspace"] / "environments/gcc/core/spack.lock").unlink()
    with pytest.raises(preview.PreviewError, match="Missing existing lock"):
        preview.preview(**options)


def test_subprocess_config_isolated_but_recorded_python_is_retained(tmp_path, monkeypatch):
    monkeypatch.setenv("SPACK_ENV", "/ambient/environment")
    monkeypatch.setenv("SPACK_USER_CONFIG_PATH", "/ambient/config")
    monkeypatch.setenv("SPACK_PYTHON", "/recorded/python")
    monkeypatch.setenv("PYTHONPATH", "/ambient/import")
    result = preview.isolated_environment(tmp_path)
    assert "SPACK_ENV" not in result and "PYTHONPATH" not in result
    assert result["SPACK_PYTHON"] == "/recorded/python"
    assert result["SPACK_DISABLE_LOCAL_CONFIG"] == "true"
    assert result["SPACK_USER_CONFIG_PATH"] == str(tmp_path / "state/user-config")


def test_generated_helper_retains_python36_syntax_and_subprocess_api():
    import ast

    source = SCRIPT.read_text()
    ast.parse(source, feature_version=(3, 6))
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "__future__"
                   for node in ast.walk(tree))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "run"]
    assert calls and all("text" not in {key.arg for key in node.keywords} for node in calls)


@pytest.mark.parametrize("scope", ["site", "user", "system", "outside-include"])
def test_ambient_or_outside_configuration_prevents_generation(installed_workspace, scope):
    options, state = installed_workspace
    state["scopes"].append(types.SimpleNamespace(name=scope, included=True, path="/ambient"))
    with pytest.raises(preview.PreviewError, match="Unexpected active"):
        preview.preview(**options)
    assert not options["output"].exists()


def test_preview_refuses_unused_directory_inside_installation_store(installed_workspace):
    options, state = installed_workspace
    output = state["prefix"].parent / "not-an-installed-prefix"
    with pytest.raises(preview.PreviewError, match="installation store"):
        preview.preview(**dict(options, output=output))
    assert not output.exists()


def test_standalone_cli_obeys_shared_workspace_maintenance_lock(installed_workspace):
    import fcntl
    import subprocess

    options, _ = installed_workspace
    with (options["workspace"] / ".cse-maintenance.lock").open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(options["workspace"]),
                                 "--output", str(options["output"]), "--modules-root", str(options["modules_root"]),
                                 "--spack", str(options["spack"])], capture_output=True, text=True)
    assert result.returncode != 0 and "another finite workspace operation" in result.stderr
    assert not options["output"].exists()
