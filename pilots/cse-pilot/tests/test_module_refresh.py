from __future__ import annotations

import grp
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

PILOT = Path(__file__).resolve().parents[1]


def launcher_fixture(
    tmp_path: Path, shared_mpi_source: str, platform_mpi_source: str,
) -> tuple[Path, dict[str, str], Path]:
    """Run the generated launcher against a command-recording Spack boundary."""
    workspace = tmp_path / "workspace"
    builder_home = tmp_path / "builder"
    spack_root = builder_home / "STACK_TESTING/spack/1.2.2"
    spack_root.mkdir(parents=True)
    log = tmp_path / "spack-commands.jsonl"
    executable = spack_root / "bin/spack"
    executable.parent.mkdir()
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, types\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['TEST_SPACK_LOG'], 'a') as handle:\n"
        "    handle.write(json.dumps(args) + '\\n')\n"
        "if args == ['--version']:\n"
        "    print('1.2.2')\n"
        "elif args[:1] == ['-e'] and args[2:5] == ['config', 'scopes', '-vp']:\n"
        "    print('workspace include active ' + os.environ['CSE_BUILD_WORKSPACE'] + '/configs/common')\n"
        "elif args[:1] == ['-e'] and args[2:4] == ['python', '-c']:\n"
        "    specs = []\n"
        "    if args[1].endswith('/gcc/mpi-openmpi') and os.environ.get('TEST_MISSING_KIND'):\n"
        "        specs = [types.SimpleNamespace(external=False,\n"
        "            installed=os.environ['TEST_MISSING_KIND'] == 'missing-prefix',\n"
        "            prefix=os.environ['CSE_BUILD_WORKSPACE'] + '/absent-prefix')]\n"
        "    api = types.ModuleType('spack.environment')\n"
        "    api.active_environment = lambda: types.SimpleNamespace(all_specs=lambda: specs)\n"
        "    sys.modules['spack'] = types.ModuleType('spack')\n"
        "    sys.modules['spack.environment'] = api\n"
        "    exec(args[4])\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    setup = spack_root / "share/spack/setup-env.sh"
    setup.parent.mkdir(parents=True)
    setup.write_text('export PATH="$SPACK_ROOT/bin:$PATH"\n', encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["config", "user.name", "Test Builder"],
        ["config", "user.email", "test@example.invalid"],
        ["add", "."],
        ["commit", "-qm", "fixture"],
        ["tag", "v1.2.2"],
        ["remote", "add", "origin", "https://example.invalid/spack.git"],
    ):
        subprocess.run(["git", "-C", str(spack_root), *args], check=True, capture_output=True)
    commit = subprocess.check_output(
        ["git", "-C", str(spack_root), "rev-parse", "HEAD"], text=True
    ).strip()

    values = yaml.safe_load((PILOT / "site-values.example.yaml").read_text())
    values["permissions"] = {
        "group": grp.getgrgid(os.getgid()).gr_name, "read": "group", "write": "user"
    }
    for name in values["paths"]:
        values["paths"][name] = str(tmp_path / name)
    for context in ("login", "compute"):
        values["build"]["contexts"][context]["stages"] = [str(tmp_path / "stage" / context)]
    for surface, mpi_source in (("shared", shared_mpi_source), ("platform", platform_mpi_source)):
        values[surface]["compiler"]["modules"] = []
        values[surface]["mpi"]["source"] = mpi_source
        values[surface]["mpi"]["modules"] = []
    values["buildcache"]["url"] = (tmp_path / "buildcache").as_uri()
    values["spack"] = {
        "source": "https://example.invalid/spack.git", "version": "1.2.2",
        "tag": "v1.2.2", "commit": commit, "default_mode": "local",
        "initial_root": str(spack_root), "shared_root": str(tmp_path / "unused-spack"),
    }
    environment = Environment(
        loader=FileSystemLoader(PILOT / "templates"), undefined=StrictUndefined,
        autoescape=False, keep_trailing_newline=True,
    )
    environment.filters["yaml_scalar"] = json.dumps
    environment.filters["yaml_flow"] = json.dumps
    for template in (
        "cse-build", "env/setup-build-env.sh", "env/prepare-module-state.sh",
        "env/select-build-context.sh", "configs/common/config.yaml",
    ):
        output = workspace / template
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(environment.get_template(template + ".j2").render(values=values))
    (workspace / "workspace-manifest.yaml").write_text("schema_version: 1\n")
    (workspace / "scripts").mkdir()
    shutil.copyfile(
        PILOT / "templates/scripts/verify-overlay-inputs.py",
        workspace / "scripts/verify-overlay-inputs.py",
    )
    shutil.copytree(PILOT / "templates/package-repos", workspace / "package-repos")
    for surface in ("gcc", "aocc"):
        for lane in ("core", "common", "serial", "mpi-openmpi"):
            lane_path = workspace / "environments" / surface / lane
            lane_path.mkdir(parents=True)
            (lane_path / "spack.lock").write_bytes(b"existing reviewed lock\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    child_environment = {
        "HOME": str(builder_home), "USER": pwd.getpwuid(os.getuid()).pw_name,
        "WORKDIR": str(workdir), "PATH": os.environ["PATH"], "TEST_SPACK_LOG": str(log),
    }
    return workspace, child_environment, log


@pytest.mark.parametrize(
    ("shared_mpi_source", "platform_mpi_source"), [("build", "external"), ("external", "build")]
)
def test_install_refreshes_all_enabled_module_sets_without_erasing_core_modules(
    tmp_path: Path, shared_mpi_source: str, platform_mpi_source: str,
) -> None:
    workspace, environment, log = launcher_fixture(tmp_path, shared_mpi_source, platform_mpi_source)
    locks = {path: path.read_bytes() for path in workspace.glob("environments/*/*/spack.lock")}
    result = subprocess.run(
        ["bash", str(workspace / "cse-build"), "compute", "install", "--spack-mode", "local"],
        capture_output=True, text=True, env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    module_commands = [
        (str(Path(command[1]).relative_to(workspace / "environments")), command[2:])
        for command in commands if command[:1] == ["-e"] and command[2:3] == ["module"]
    ]
    clear_default = ["module", "tcl", "refresh", "--delete-tree", "-y"]
    expected = [
        ("gcc/core", clear_default),
        ("gcc/core", ["module", "tcl", "--name", "core_independent", "refresh", "-y"]),
        ("gcc/core", ["module", "tcl", "--name", "compiler_producer", "refresh", "--delete-tree", "-y"]),
        ("gcc/common", clear_default),
        ("gcc/serial", clear_default),
        ("gcc/mpi-openmpi", clear_default),
    ]
    if shared_mpi_source == "build":
        expected.append(("gcc/mpi-openmpi", ["module", "tcl", "--name", "mpi_producer", "refresh", "--delete-tree", "-y"]))
    expected.extend([
        ("aocc/core", clear_default),
        ("aocc/core", ["module", "tcl", "--name", "core_independent", "refresh", "-y"]),
        ("aocc/common", clear_default),
        ("aocc/serial", clear_default),
        ("aocc/mpi-openmpi", clear_default),
    ])
    if platform_mpi_source == "build":
        expected.append(("aocc/mpi-openmpi", ["module", "tcl", "--name", "mpi_producer", "refresh", "--delete-tree", "-y"]))
    assert module_commands == expected
    assert not any("concretize" in command for command in commands)
    assert {path: path.read_bytes() for path in locks} == locks


@pytest.mark.parametrize("missing_kind", ["uninstalled", "missing-prefix"])
def test_modules_action_checks_every_selected_install_before_any_refresh(
    tmp_path: Path, missing_kind: str,
) -> None:
    workspace, environment, log = launcher_fixture(tmp_path, "build", "external")
    environment["TEST_MISSING_KIND"] = missing_kind
    result = subprocess.run(
        ["bash", str(workspace / "cse-build"), "compute", "modules", "--surface", "shared",
         "--spack-mode", "local"],
        capture_output=True, text=True, env=environment,
    )
    assert result.returncode != 0
    assert "finish installing gcc/mpi-openmpi" in result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any(argument in ("fetch", "install", "concretize", "module", "regenerate")
                   for command in commands for argument in command)


def test_modules_action_refreshes_selected_surface_without_build_or_solve(tmp_path: Path) -> None:
    workspace, environment, log = launcher_fixture(tmp_path, "build", "external")
    locks = {path: path.read_bytes() for path in workspace.glob("environments/*/*/spack.lock")}
    result = subprocess.run(
        ["bash", str(workspace / "cse-build"), "compute", "modules", "--surface", "shared",
         "--spack-mode", "local"],
        capture_output=True, text=True, env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any(argument in ("fetch", "install", "concretize")
                   for command in commands for argument in command)
    module_commands = [
        (str(Path(command[1]).relative_to(workspace / "environments")), command[2:])
        for command in commands if command[:1] == ["-e"] and command[2:3] == ["module"]
    ]
    default = ["module", "tcl", "refresh", "--delete-tree", "-y"]
    assert module_commands == [
        ("gcc/core", default),
        ("gcc/core", ["module", "tcl", "--name", "core_independent", "refresh", "-y"]),
        ("gcc/core", ["module", "tcl", "--name", "compiler_producer", "refresh", "--delete-tree", "-y"]),
        ("gcc/common", default),
        ("gcc/serial", default),
        ("gcc/mpi-openmpi", default),
        ("gcc/mpi-openmpi", ["module", "tcl", "--name", "mpi_producer", "refresh", "--delete-tree", "-y"]),
    ]
    regenerated_views = [
        str(Path(command[1]).relative_to(workspace / "environments"))
        for command in commands if command[:1] == ["-e"] and command[2:] == ["env", "view", "regenerate"]
    ]
    assert regenerated_views == ["gcc/core", "gcc/common", "gcc/serial", "gcc/mpi-openmpi"]
    assert {path: path.read_bytes() for path in locks} == locks
