from __future__ import annotations

import ast
import grp
import json
import os
import pwd
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"
ROSTER_PATH = Path(__file__).resolve().parents[1] / "roster.yaml"
BLUEPRINT_PATH = Path(__file__).resolve().parents[1] / "blueprint.yaml"
SITE_VALUES_PATH = Path(__file__).resolve().parents[1] / "site-values.example.yaml"


def render(template: str, **context: object) -> dict:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    environment.filters["yaml_scalar"] = json.dumps
    environment.filters["yaml_flow"] = json.dumps
    return yaml.safe_load(environment.get_template(template).render(**context))


def render_text(template: str, **context: object) -> str:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    environment.filters["yaml_scalar"] = json.dumps
    environment.filters["yaml_flow"] = json.dumps
    return environment.get_template(template).render(**context)


def values() -> dict:
    return {
        "architecture": {"target": "x86_64_v3", "binary_target": "x86_64"},
        "build": {
            "contexts": {
                "login": {
                    "node_type": "login",
                    "stages": [
                        "/unusable/login-stage",
                        "${WORKDIR}/cse-spack-stage/raider/trial-001/login",
                    ],
                },
                "compute": {
                    "node_type": "cpu_compute",
                    "stages": [
                        "/unusable/compute-stage",
                        "${WORKDIR}/cse-spack-stage/raider/trial-001/compute",
                    ],
                },
            }
        },
        "catalog_scopes": {"common": "scopes/common", "platform": None},
        "paths": {"views_root": "/views"},
        "shared": {
            "compiler": {
                "name": "gcc",
                "version": "12.5.0",
                "source": "build",
                "modules": [],
                "build_with": {
                    "name": "gcc",
                    "version": "12.2.1",
                    "modules": ["PrgEnv-gnu/8.7.0", "gcc-native/12.3"],
                },
            },
            "mpi": {
                "name": "openmpi",
                "version": "4.1.8",
                "source": "build",
                "modules": [],
                "spec": (
                    "openmpi@4.1.8 fabrics=ucx schedulers=slurm +pmi "
                    "^ucx@1.18.0+thread_multiple ^slurm@23.02.7"
                ),
                "provider_constraint": (
                    "openmpi@4.1.8 fabrics=ucx schedulers=slurm +pmi"
                ),
            },
            "catalog_scopes": {"compiler": "scopes/compilers/gcc/12.2.1"},
        },
        "platform": {
            "compiler": {
                "name": "aocc",
                "version": "4.1.0",
                "source": "external",
                "modules": ["amd/aocc/4.1.0"],
            },
            "mpi": {
                "name": "openmpi",
                "version": "4.1.8",
                "source": "build",
                "modules": [],
                "spec": (
                    "openmpi@4.1.8 fabrics=ucx schedulers=slurm +pmi "
                    "^ucx@1.18.0+thread_multiple ^slurm@23.02.7"
                ),
                "provider_constraint": (
                    "openmpi@4.1.8 fabrics=ucx schedulers=slurm +pmi"
                ),
            },
            "catalog_scopes": {
                "compiler": "scopes/compilers/aocc/4.1.0",
                "runtime_compiler": None,
            },
        },
    }


class ToolchainTemplateTests(unittest.TestCase):
    def test_blueprint_declares_shared_workspace_access_contract(self) -> None:
        blueprint = yaml.safe_load(BLUEPRINT_PATH.read_text(encoding="utf-8"))
        self.assertTrue(blueprint["apply_workspace_permissions"])
        self.assertEqual(
            blueprint["allowed_values"]["permissions.read"],
            ["group", "world"],
        )
        self.assertEqual(
            blueprint["allowed_values"]["permissions.write"],
            ["user", "group"],
        )
        handoff = (TEMPLATE_ROOT / "BUILDER-HANDOFF.md.j2").read_text(
            encoding="utf-8"
        )
        self.assertIn("default `tcsh` login", handoff)
        self.assertIn("`catalog/profile.yaml`", handoff)

    @unittest.skipUnless(shutil.which("tcsh"), "tcsh is not installed")
    def test_cse_build_runs_directly_from_tcsh(self) -> None:
        rendered = render_text(
            "cse-build.j2",
            values=yaml.safe_load(SITE_VALUES_PATH.read_text(encoding="utf-8")),
        )
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "cse-build"
            launcher.write_text(rendered, encoding="utf-8")
            launcher.chmod(0o770)
            result = subprocess.run(
                [
                    shutil.which("tcsh") or "tcsh",
                    "-f",
                    "-c",
                    f"{shlex.quote(str(launcher))} login --help",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage: ./cse-build", result.stdout)

    @unittest.skipUnless(shutil.which("tcsh"), "tcsh is not installed")
    def test_cse_build_shared_status_is_a_self_contained_tcsh_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            spack_root = root / "shared-spack"
            builder_home = root / "builder-home"
            workdir = root / "work"
            workspace.mkdir()
            builder_home.mkdir()
            workdir.mkdir()

            (spack_root / "bin").mkdir(parents=True)
            (spack_root / "share" / "spack").mkdir(parents=True)
            fake_spack = spack_root / "bin" / "spack"
            fake_spack.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "if [ \"${1:-}\" = --version ]; then\n"
                "  printf '1.2.2\\n'\n"
                "elif [ \"${1:-}\" = python ]; then\n"
                "  exit 0\n"
                "elif [ \"${1:-}\" = config ]; then\n"
                "  exit 0\n"
                "elif [ \"${1:-}\" = -e ] && [ \"${3:-}\" = config ]; then\n"
                "  printf 'workspace include active %s/configs/common\\n' \"$CSE_BUILD_WORKSPACE\"\n"
                "else\n"
                "  exit 0\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_spack.chmod(0o755)
            (spack_root / "share" / "spack" / "setup-env.sh").write_text(
                'export PATH="$SPACK_ROOT/bin:$PATH"\n',
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "init", "-q", str(spack_root)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(spack_root), "config", "user.name", "Test Builder"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(spack_root),
                    "config",
                    "user.email",
                    "test@example.invalid",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(spack_root), "add", "."],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(spack_root), "commit", "-qm", "fixture"],
                check=True,
            )
            commit = subprocess.run(
                ["git", "-C", str(spack_root), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(spack_root), "tag", "v1.2.2"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(spack_root),
                    "remote",
                    "add",
                    "origin",
                    "https://example.invalid/spack.git",
                ],
                check=True,
            )

            test_values = {
                **values(),
                "build_jobs": 16,
                "system": {"name": "raider"},
                "release": "trial-001",
                "workspace": {"role": "build"},
                "permissions": {
                    "group": grp.getgrgid(os.getgid()).gr_name,
                    "read": "group",
                    "write": "group",
                },
                "spack": {
                    "source": "https://example.invalid/spack.git",
                    "version": "1.2.2",
                    "tag": "v1.2.2",
                    "commit": commit,
                    "default_mode": "shared",
                    "shared_root": str(spack_root),
                    "initial_root": str(spack_root),
                },
            }
            launcher = workspace / "cse-build"
            launcher.write_text(
                render_text("cse-build.j2", values=test_values),
                encoding="utf-8",
            )
            launcher.chmod(0o770)
            (workspace / "workspace-manifest.yaml").write_text(
                "schema_version: 1\n",
                encoding="utf-8",
            )
            (workspace / "configs" / "common").mkdir(parents=True)
            (workspace / "scripts").mkdir()
            (workspace / "scripts" / "verify-lockfiles.py").write_text(
                "# fake verifier\n",
                encoding="utf-8",
            )
            env_dir = workspace / "env"
            env_dir.mkdir()
            (env_dir / "select-build-context.sh").write_text(
                render_text("env/select-build-context.sh.j2", values=test_values),
                encoding="utf-8",
            )
            (env_dir / "prepare-module-state.sh").write_text(
                "cse_prepare_module_state() { :; }\n",
                encoding="utf-8",
            )
            (env_dir / "setup-build-env.sh").write_text(
                render_text("env/setup-build-env.sh.j2", values=test_values),
                encoding="utf-8",
            )

            for path in sorted(spack_root.rglob("*"), reverse=True):
                path.chmod(0o550 if path.is_dir() or os.access(path, os.X_OK) else 0o440)
            spack_root.chmod(0o550)

            result = subprocess.run(
                [
                    shutil.which("tcsh") or "tcsh",
                    "-f",
                    "-c",
                    f"cd {shlex.quote(str(workspace))} && "
                    "./cse-build login status --spack-mode shared",
                ],
                check=False,
                text=True,
                capture_output=True,
                env={
                    "HOME": str(builder_home),
                    "USER": pwd.getpwuid(os.getuid()).pw_name,
                    "WORKDIR": str(workdir),
                    "PATH": os.environ["PATH"],
                },
            )
            home_entries = list(builder_home.iterdir())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Node context: login (login)", result.stdout)
        self.assertIn("Concrete locks: 0/8", result.stdout)
        self.assertEqual(home_entries, [])

    def test_gcc_groups_inherit_the_managed_producer_without_a_second_constraint(
        self,
    ) -> None:
        test_values = values()
        roster = {
            "specs": {
                "foundation": ["zlib@1.3.1"],
                "core": ["cmake@3.31.12"],
                "core_independent": ["miniforge3@26.1.1-3"],
                "build_tools": ["cmake@3.31.12"],
            }
        }

        core = render(
            "environments/{{ values.shared.compiler.name }}/core/spack.yaml.j2",
            values=test_values,
            data={"roster": roster},
        )
        payload = render(
            "_partials/payload-spack.yaml.j2",
            values=test_values,
            data={"roster": roster},
            surface_key="shared",
            surface=test_values["shared"],
            environment_kind="serial",
            environment_name="serial",
            payload_specs=["hdf5@2.1.0~mpi"],
            payload_constraint="target=x86_64_v3 %gcc@12.5.0",
        )

        for rendered in (core, payload):
            groups = {
                entry["group"]: entry for entry in rendered["spack"]["specs"]
            }
            compiler_spec = groups["compiler"]["specs"][0]
            self.assertIn("+binutils", compiler_spec)

        core_groups = {
            entry["group"]: entry for entry in core["spack"]["specs"]
        }
        for group in ("foundation", "core"):
            compiler_constraint = core_groups[group]["specs"][0]["matrix"][1][0]
            self.assertEqual(compiler_constraint, "target=x86_64_v3")
            self.assertIn("compiler", core_groups[group]["needs"])

        payload_groups = {
            entry["group"]: entry for entry in payload["spack"]["specs"]
        }
        for group in ("foundation", "build-tools"):
            compiler_constraint = payload_groups[group]["specs"][0]["matrix"][1][0]
            self.assertEqual(compiler_constraint, "target=x86_64_v3")
            self.assertIn("compiler", payload_groups[group]["needs"])
        self.assertIn("compiler", payload_groups["payload"]["needs"])

    def test_common_package_policy_uses_system_glibc_for_iconv(self) -> None:
        rendered = render(
            "configs/common/packages.yaml.j2",
            values={
                "architecture": {
                    "target": "x86_64_v3",
                    "binary_target": "x86_64",
                },
                "permissions": {
                    "read": "group",
                    "write": "group",
                    "group": "cse",
                },
            },
            data={"roster": {"cmake": {"build_default": "3.31.12"}}},
        )

        self.assertEqual(rendered["packages"]["iconv"]["require"], ["glibc"])

    def test_common_package_policy_enables_standard_boost_libraries(self) -> None:
        rendered = render(
            "configs/common/packages.yaml.j2",
            values={
                "architecture": {
                    "target": "x86_64_v3",
                    "binary_target": "x86_64",
                },
                "permissions": {
                    "read": "group",
                    "write": "group",
                    "group": "cse",
                },
            },
            data={"roster": {"cmake": {"build_default": "3.31.12"}}},
        )

        requirement = rendered["packages"]["boost"]["require"]
        self.assertEqual(len(requirement), 2)
        for library in ("filesystem", "iostreams", "program_options", "system"):
            self.assertIn(f"+{library}", requirement[0])
        self.assertEqual(
            requirement[1],
            {"spec": "^python@3.12.13", "when": "+mpi"},
        )
        self.assertEqual(
            rendered["packages"]["xcb-proto"]["require"],
            ["^python@3.12.13"],
        )
        self.assertEqual(rendered["packages"]["python"]["require"], ["+ssl"])
        for virtual in ("blas", "lapack"):
            self.assertEqual(
                rendered["packages"][virtual]["require"],
                ["netlib-lapack@3.12.1"],
            )

    def test_roster_binds_implicit_python_and_dakota_producers(self) -> None:
        roster = yaml.safe_load(ROSTER_PATH.read_text(encoding="utf-8"))

        self.assertIn("ninja ^python@3.12.13", roster["specs"]["core"])
        for spec in roster["specs"]["mpi"]:
            if spec.startswith("boost@"):
                self.assertIn("+mpi", spec)
        for spec in roster["specs"]["mpi"]:
            if not spec.startswith("dakota@"):
                continue
            self.assertIn("+python", spec)
            self.assertIn("^python@3.12.13", spec)
            self.assertIn("^netlib-lapack@3.12.1", spec)
            self.assertIn("^boost@1.90.0+mpi", spec)

        self.assertEqual(
            len([spec for spec in roster["specs"]["mpi"] if spec.startswith("dakota@")]),
            2,
        )

    def test_module_sets_select_only_their_intended_roots(self) -> None:
        test_values = values()
        test_values["paths"]["modules_root"] = "/modules"
        roster = {
            "specs": {
                "core": ["pkgconf", "python@3.12.13"],
                "core_independent": ["miniforge3@26.1.1-3"],
            }
        }

        shared = render(
            "configs/environments/{{ values.shared.compiler.name }}/core/modules.yaml.j2",
            values=test_values,
            data={"roster": roster},
        )["modules"]

        self.assertEqual(shared["compiler_producer"]["tcl"]["exclude"], ["@:"])
        self.assertEqual(
            shared["compiler_producer"]["tcl"]["include"],
            ["gcc@12.5.0+binutils"],
        )
        self.assertEqual(shared["default"]["tcl"]["exclude"], ["@:"])
        self.assertIn(
            "pkgconf %gcc@12.5.0+binutils",
            shared["default"]["tcl"]["include"],
        )
        self.assertIn(
            "python@3.12.13 %gcc@12.5.0+binutils",
            shared["default"]["tcl"]["include"],
        )

        test_values["platform"]["compiler"].update(
            {
                "name": "intel-oneapi-compilers",
                "version": "2024.2.1",
                "modules": ["oneapi/2024.2.1"],
            }
        )
        platform = render(
            "configs/environments/{{ values.platform.compiler.name }}/core/modules.yaml.j2",
            values=test_values,
            data={"roster": roster},
        )["modules"]

        self.assertIn(
            "pkgconf %oneapi@2024.2.1", platform["default"]["tcl"]["include"]
        )

    def test_lock_verifier_keeps_python_36_compatible_annotations(self) -> None:
        script = render_text(
            "scripts/verify-lockfiles.py.j2",
            values=values(),
            data={
                "roster": {
                    "cmake": {
                        "build_default": "3.31.12",
                        "current": "4.4.2",
                    }
                }
            },
        )
        tree = ast.parse(script)

        future_annotations = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
        ]
        builtin_generics = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"dict", "list", "set", "tuple"}
        ]

        self.assertEqual(future_annotations, [])
        self.assertEqual(builtin_generics, [])
        compile(script, "verify-lockfiles.py", "exec")

    def test_lock_verifier_rejects_downstream_use_of_a_different_gcc_hash(self) -> None:
        script = render_text(
            "scripts/verify-lockfiles.py.j2",
            values=values(),
            data={
                "roster": {
                    "cmake": {
                        "build_default": "3.31.12",
                        "current": "4.4.2",
                    }
                }
            },
        )
        namespace = {
            "__file__": "/workspace/scripts/verify-lockfiles.py",
            "__name__": "verifier_test",
        }
        exec(compile(script, "verify-lockfiles.py", "exec"), namespace)
        errors = []

        namespace["verify_shared_gcc_provider_hashes"](
            {"gcc-plus-binutils-hash"},
            {("gcc", "gcc", "12.5.0"): {"gcc-without-binutils-hash"}},
            errors,
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("do not match the +binutils producer hash", errors[0])

    def test_workspace_gate_rejects_an_incomplete_dakota_overlay(self) -> None:
        script = render_text(
            "scripts/verify-lockfiles.py.j2",
            values=values(),
            data={
                "roster": {
                    "cmake": {
                        "build_default": "3.31.12",
                        "current": "4.4.2",
                    }
                }
            },
        )
        dakota_source = (
            TEMPLATE_ROOT
            / "package-repos"
            / "spack_repo"
            / "cse_trials"
            / "packages"
            / "dakota"
        )
        current_patch = (dakota_source / "boost-system-header-only.patch").read_text(
            encoding="utf-8"
        )
        incomplete_patch = current_patch.split(
            "diff --git a/src/surrogates/unit/CMakeLists.txt", 1
        )[0]

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            script_path = workspace / "scripts" / "verify-lockfiles.py"
            overlay = (
                workspace
                / "package-repos"
                / "spack_repo"
                / "cse_trials"
                / "packages"
                / "dakota"
            )
            shared_config = (
                workspace / "configs" / "surfaces" / "shared" / "compiler.yaml"
            )
            script_path.parent.mkdir(parents=True)
            overlay.mkdir(parents=True)
            shared_config.parent.mkdir(parents=True)
            script_path.write_text(script, encoding="utf-8")
            shutil.copyfile(dakota_source / "package.py", overlay / "package.py")
            (overlay / "boost-system-header-only.patch").write_text(
                current_patch, encoding="utf-8"
            )
            shared_config.write_text(
                "packages:\n"
                "  c:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  cxx:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  fortran:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  gcc:\n    buildable: true\n",
                encoding="utf-8",
            )
            producer = "gcc@12.5.0+binutils languages='c,c++,fortran'"
            downstream_constraint = "target=x86_64_v3"
            for lane in ("core", "common", "serial", "mpi-openmpi"):
                environment = workspace / "environments" / "gcc" / lane
                environment.mkdir(parents=True)
                (environment / "spack.yaml").write_text(
                    "spack:\n  specs:\n    - group: compiler\n"
                    f"      specs:\n        - {producer}\n"
                    "    - group: foundation\n      needs: [compiler]\n"
                    "      specs:\n        - matrix:\n"
                    "            - [$foundation]\n"
                    f"            - [{downstream_constraint}]\n",
                    encoding="utf-8",
                )

            current = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )
            (overlay / "boost-system-header-only.patch").write_text(
                incomplete_patch, encoding="utf-8"
            )
            stale = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertIn("Workspace input verification passed", current.stdout)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("Dakota overlay is incomplete", stale.stderr)

    def test_workspace_gate_rejects_a_stale_gcc_producer_spec(self) -> None:
        script = render_text(
            "scripts/verify-lockfiles.py.j2",
            values=values(),
            data={
                "roster": {
                    "cmake": {
                        "build_default": "3.31.12",
                        "current": "4.4.2",
                    }
                }
            },
        )
        dakota_source = (
            TEMPLATE_ROOT
            / "package-repos"
            / "spack_repo"
            / "cse_trials"
            / "packages"
            / "dakota"
        )

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            script_path = workspace / "scripts" / "verify-lockfiles.py"
            overlay = (
                workspace
                / "package-repos"
                / "spack_repo"
                / "cse_trials"
                / "packages"
                / "dakota"
            )
            shared_config = (
                workspace / "configs" / "surfaces" / "shared" / "compiler.yaml"
            )
            script_path.parent.mkdir(parents=True)
            overlay.mkdir(parents=True)
            shared_config.parent.mkdir(parents=True)
            script_path.write_text(script, encoding="utf-8")
            shutil.copyfile(dakota_source / "package.py", overlay / "package.py")
            shutil.copyfile(
                dakota_source / "boost-system-header-only.patch",
                overlay / "boost-system-header-only.patch",
            )
            shared_config.write_text(
                "packages:\n"
                "  c:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  cxx:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  fortran:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  gcc:\n    buildable: true\n",
                encoding="utf-8",
            )

            producer = "gcc@12.5.0+binutils languages='c,c++,fortran'"
            downstream_constraint = "target=x86_64_v3"
            for lane in ("core", "common", "serial", "mpi-openmpi"):
                environment = workspace / "environments" / "gcc" / lane
                environment.mkdir(parents=True)
                (environment / "spack.yaml").write_text(
                    "spack:\n  specs:\n    - group: compiler\n"
                    f"      specs:\n        - {producer}\n"
                    "    - group: foundation\n      needs: [compiler]\n"
                    "      specs:\n        - matrix:\n"
                    "            - [$foundation]\n"
                    f"            - [{downstream_constraint}]\n",
                    encoding="utf-8",
                )

            current = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )
            stale_path = workspace / "environments" / "gcc" / "common" / "spack.yaml"
            stale_path.write_text(
                stale_path.read_text(encoding="utf-8").replace(
                    producer, producer.replace("+binutils", "")
                ),
                encoding="utf-8",
            )
            stale = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("does not enable +binutils", stale.stderr)

    def test_workspace_gate_rejects_a_second_gcc_downstream_constraint(self) -> None:
        script = render_text(
            "scripts/verify-lockfiles.py.j2",
            values=values(),
            data={
                "roster": {
                    "cmake": {
                        "build_default": "3.31.12",
                        "current": "4.4.2",
                    }
                }
            },
        )
        dakota_source = (
            TEMPLATE_ROOT
            / "package-repos"
            / "spack_repo"
            / "cse_trials"
            / "packages"
            / "dakota"
        )

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            script_path = workspace / "scripts" / "verify-lockfiles.py"
            overlay = (
                workspace
                / "package-repos"
                / "spack_repo"
                / "cse_trials"
                / "packages"
                / "dakota"
            )
            shared_config = (
                workspace / "configs" / "surfaces" / "shared" / "compiler.yaml"
            )
            script_path.parent.mkdir(parents=True)
            overlay.mkdir(parents=True)
            shared_config.parent.mkdir(parents=True)
            script_path.write_text(script, encoding="utf-8")
            shutil.copyfile(dakota_source / "package.py", overlay / "package.py")
            shutil.copyfile(
                dakota_source / "boost-system-header-only.patch",
                overlay / "boost-system-header-only.patch",
            )
            shared_config.write_text(
                "packages:\n"
                "  c:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  cxx:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  fortran:\n    prefer: [gcc@12.5.0+binutils]\n"
                "  gcc:\n    buildable: true\n",
                encoding="utf-8",
            )

            producer = "gcc@12.5.0+binutils languages='c,c++,fortran'"
            downstream_constraint = "target=x86_64_v3"
            for lane in ("core", "common", "serial", "mpi-openmpi"):
                environment = workspace / "environments" / "gcc" / lane
                environment.mkdir(parents=True)
                (environment / "spack.yaml").write_text(
                    "spack:\n  specs:\n    - group: compiler\n"
                    f"      specs:\n        - {producer}\n"
                    "    - group: foundation\n      needs: [compiler]\n"
                    "      specs:\n        - matrix:\n"
                    "            - [$foundation]\n"
                    f"            - [{downstream_constraint}]\n",
                    encoding="utf-8",
                )

            current = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )

            stale_path = workspace / "environments" / "gcc" / "common" / "spack.yaml"
            stale_path.write_text(
                stale_path.read_text(encoding="utf-8").replace(
                    downstream_constraint,
                    "target=x86_64_v3 %gcc@12.5.0+binutils",
                ),
                encoding="utf-8",
            )
            stale_constraint = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )

            stale_path.write_text(
                stale_path.read_text(encoding="utf-8").replace(
                    "target=x86_64_v3 %gcc@12.5.0+binutils",
                    downstream_constraint,
                ),
                encoding="utf-8",
            )
            stale_path.write_text(
                stale_path.read_text(encoding="utf-8").replace(
                    "      needs: [compiler]\n", ""
                ),
                encoding="utf-8",
            )
            missing_needs = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )
            stale_path.write_text(
                stale_path.read_text(encoding="utf-8").replace(
                    "    - group: foundation\n      specs:\n",
                    "    - group: foundation\n      needs: [compiler]\n"
                    "      specs:\n",
                ),
                encoding="utf-8",
            )
            shared_config.write_text(
                shared_config.read_text(encoding="utf-8").replace(
                    "gcc@12.5.0+binutils", "gcc@12.5.0"
                ),
                encoding="utf-8",
            )
            stale_preferences = subprocess.run(
                [sys.executable, str(script_path), "--workspace-only"],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertNotEqual(stale_constraint.returncode, 0)
        self.assertIn("repeats the managed GCC producer", stale_constraint.stderr)
        self.assertNotEqual(missing_needs.returncode, 0)
        self.assertIn("does not inherit the managed GCC producer", missing_needs.stderr)
        self.assertNotEqual(stale_preferences.returncode, 0)
        self.assertIn("language-provider policy", stale_preferences.stderr)

    def test_cse_build_checks_workspace_inputs_before_actions(self) -> None:
        template = (TEMPLATE_ROOT / "cse-build.j2").read_text(encoding="utf-8")

        self.assertIn("verify_workspace_inputs()", template)
        self.assertLess(
            template.index("\nverify_workspace_inputs\n"),
            template.index("\nverify_scopes\n"),
        )

    def test_cse_build_prepares_modules_before_activating_spack(self) -> None:
        template = (TEMPLATE_ROOT / "cse-build.j2").read_text(encoding="utf-8")
        prepare = template.index("cse_prepare_module_state")
        activate = template.index('source "$SPACK_ROOT/share/spack/setup-env.sh"')

        self.assertLess(prepare, activate)

    def test_cse_build_can_select_one_compiler_surface_for_install(self) -> None:
        script = render_text(
            "cse-build.j2",
            values={
                **values(),
                "system": {"name": "raider"},
                "release": "trial-001",
                "workspace": {"role": "build"},
                "permissions": {"group": "cse"},
                "spack": {
                    "source": "https://github.com/spack/spack.git",
                    "version": "1.2.2",
                    "tag": "v1.2.2",
                    "commit": "a" * 40,
                    "default_mode": "shared",
                    "shared_root": "/tools/spack/1.2.2",
                    "initial_root": "/tools/spack/1.2.2",
                },
            },
        )

        self.assertIn("--surface all|shared|platform", script)
        self.assertIn(
            'shared) CSE_ACTION_ENVIRONMENTS=("${CSE_SHARED_ENVIRONMENTS[@]}")',
            script,
        )
        self.assertIn(
            'platform) CSE_ACTION_ENVIRONMENTS=("${CSE_PLATFORM_ENVIRONMENTS[@]}")',
            script,
        )
        self.assertIn(
            'for environment in "${CSE_ACTION_ENVIRONMENTS[@]}"; do',
            script,
        )
        self.assertIn(
            'SPACK_USER_CACHE_PATH="$SPACK_USER_STATE_ROOT/cache/'
            '$CSE_NODE_CONTEXT/$REQUESTED_SURFACE"',
            script,
        )
        self.assertIn(
            'SPACK_BOOTSTRAP_ROOT="$SPACK_USER_STATE_ROOT/bootstrap"',
            script,
        )

    def test_bootstrap_root_is_shared_across_node_contexts(self) -> None:
        rendered = render(
            "configs/common/bootstrap.yaml.j2",
            values=values(),
        )

        self.assertEqual(
            rendered,
            {"bootstrap": {"root": "${SPACK_BOOTSTRAP_ROOT}"}},
        )

    def test_cse_build_selects_login_or_compute_context(self) -> None:
        script = render_text(
            "cse-build.j2",
            values={
                **values(),
                "system": {"name": "raider"},
                "release": "trial-001",
                "workspace": {"role": "build"},
                "permissions": {"group": "cse"},
                "spack": {
                    "source": "https://github.com/spack/spack.git",
                    "version": "1.2.2",
                    "tag": "v1.2.2",
                    "commit": "a" * 40,
                    "default_mode": "shared",
                    "shared_root": "/tools/spack/1.2.2",
                    "initial_root": "/tools/spack/1.2.2",
                },
            },
        )

        self.assertIn("[login|compute]", script)
        self.assertIn('source "$CSE_WORKSPACE_ROOT/env/select-build-context.sh"', script)
        self.assertIn('cse_select_build_context "$CSE_NODE_CONTEXT"', script)
        self.assertIn(
            'CSE_TMUX_SESSION="cse-$CSE_RECORDED_SYSTEM-'
            '$CSE_RECORDED_RELEASE-$CSE_NODE_CONTEXT"',
            script,
        )

    def test_context_selector_uses_distinct_workdir_fallbacks(self) -> None:
        selector = render_text(
            "env/select-build-context.sh.j2",
            values=values(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            selector_path = Path(temp_dir) / "select-build-context.sh"
            selector_path.write_text(selector, encoding="utf-8")
            harness = r"""
set -euo pipefail
export USER=tester
export WORKDIR="$1/work"
mkdir -p "$WORKDIR"
source "$2"
cse_select_build_context login
printf 'login=%s|%s\n' "$CSE_BUILD_NODE_TYPE" "$CSE_BUILD_STAGE"
cse_select_build_context compute
printf 'compute=%s|%s\n' "$CSE_BUILD_NODE_TYPE" "$CSE_BUILD_STAGE"
"""
            result = subprocess.run(
                ["bash", "-c", harness, "bash", temp_dir, str(selector_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("login=login|", lines[0])
        self.assertTrue(lines[0].endswith("/raider/trial-001/login"))
        self.assertIn("compute=cpu_compute|", lines[1])
        self.assertTrue(lines[1].endswith("/raider/trial-001/compute"))

    def test_preloaded_external_module_is_removed_before_spack_runs(self) -> None:
        script = render_text(
            "env/prepare-module-state.sh.j2",
            values=values(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "prepare-module-state.sh"
            script_path.write_text(script, encoding="utf-8")
            harness = r"""
set -euo pipefail
export LOADEDMODULES='amd/aocc/4.1.0:site/base'
module() {
  [ "$1" = unload ] || return 2
  [ "$2" = amd/aocc/4.1.0 ] || return 3
  LOADEDMODULES="${LOADEDMODULES#amd/aocc/4.1.0:}"
  export LOADEDMODULES
}
source "$1"
cse_prepare_module_state
printf '%s\n' "$LOADEDMODULES"
"""
            result = subprocess.run(
                ["bash", "-c", harness, "bash", str(script_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "site/base")

    def test_conflicting_cray_programming_environment_is_removed(self) -> None:
        test_values = values()
        test_values["platform"]["compiler"]["modules"] = [
            "PrgEnv-aocc/8.7.0",
            "aocc/4.1.0",
        ]
        script = render_text(
            "env/prepare-module-state.sh.j2",
            values=test_values,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "prepare-module-state.sh"
            script_path.write_text(script, encoding="utf-8")
            harness = r"""
set -euo pipefail
export LOADEDMODULES='PrgEnv-cray/8.7.0:cce/21.0.0:site/base'
export PE_ENV=CRAY
module() {
  [ "$1" = unload ] || return 2
  [ "$2" = PrgEnv-cray/8.7.0 ] || return 3
  LOADEDMODULES="${LOADEDMODULES#PrgEnv-cray/8.7.0:}"
  export LOADEDMODULES
}
source "$1"
cse_prepare_module_state
printf 'modules=%s\n' "$LOADEDMODULES"
printf 'pe=%s\n' "${PE_ENV-<unset>}"
"""
            result = subprocess.run(
                ["bash", "-c", harness, "bash", str(script_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("modules=cce/21.0.0:site/base", result.stdout)
        self.assertIn("pe=<unset>", result.stdout)

    def test_language_provider_policy_is_surface_specific(self) -> None:
        test_values = values()
        cases = {
            "configs/surfaces/shared/compiler.yaml.j2": (
                "prefer",
                ["gcc@12.5.0+binutils"],
            ),
            "configs/surfaces/platform/compiler.yaml.j2": (
                "prefer",
                ["aocc@4.1.0"],
            ),
        }

        for template, (policy_key, expected) in cases.items():
            with self.subTest(template=template):
                rendered = render(template, values=test_values)
                packages = rendered["packages"]
                for language in ("c", "cxx", "fortran"):
                    self.assertEqual(packages[language][policy_key], expected)

        shared = render(
            "configs/surfaces/shared/compiler.yaml.j2", values=test_values
        )["packages"]["gcc"]
        self.assertTrue(shared["buildable"])
        self.assertNotIn("require", shared)

    def test_oneapi_core_includes_registered_gcc_runtime_provider(self) -> None:
        test_values = values()
        test_values["platform"]["compiler"].update(
            {
                "name": "oneapi",
                "version": "2024.1",
                "modules": ["intel/2024.2.1/compiler/latest"],
            }
        )
        test_values["platform"]["catalog_scopes"].update(
            {
                "compiler": "scopes/compilers/oneapi/2024.1",
                "runtime_compiler": "scopes/compilers/gcc/12.2.1",
            }
        )
        rendered = render(
            "environments/{{ values.platform.compiler.name }}/core/spack.yaml.j2",
            values=test_values,
            data={
                "roster": {
                    "specs": {
                        "foundation": ["zlib@1.3.1"],
                        "core": ["cmake@3.31.12"],
                        "core_independent": [],
                    }
                }
            },
        )

        self.assertIn(
            "../../../catalog/scopes/compilers/gcc/12.2.1",
            rendered["spack"]["include:"],
        )

        payload = render(
            "_partials/payload-spack.yaml.j2",
            values=test_values,
            data={
                "roster": {
                    "specs": {
                        "foundation": ["zlib@1.3.1"],
                        "build_tools": ["cmake@3.31.12"],
                    }
                }
            },
            surface_key="platform",
            surface=test_values["platform"],
            environment_kind="serial",
            environment_name="serial",
            payload_specs=["hdf5@2.1.0~mpi"],
            payload_constraint="target=x86_64_v3 %oneapi@2024.1",
        )
        self.assertIn(
            "../../../catalog/scopes/compilers/gcc/12.2.1",
            payload["spack"]["include:"],
        )
        groups = {entry["group"]: entry for entry in payload["spack"]["specs"]}
        for group in ("foundation", "build-tools"):
            compiler_constraint = groups[group]["specs"][0]["matrix"][1][0]
            self.assertEqual(
                compiler_constraint, "target=x86_64_v3 %oneapi@2024.1"
            )

    def test_mpi_boundary_does_not_propagate_lane_constraints_to_externals(self) -> None:
        test_values = values()
        rendered = render(
            "_partials/payload-spack.yaml.j2",
            values=test_values,
            data={
                "roster": {
                    "specs": {
                        "foundation": ["zlib@1.3.1"],
                        "build_tools": ["cmake@3.31.12"],
                    }
                }
            },
            surface_key="shared",
            surface=test_values["shared"],
            environment_kind="mpi",
            environment_name="mpi-openmpi",
            payload_specs=["hdf5@2.1.0+mpi"],
            payload_constraint=(
                "target=x86_64_v3 %gcc@12.5.0 ^openmpi@4.1.8"
            ),
        )

        groups = {entry["group"]: entry for entry in rendered["spack"]["specs"]}
        for group in ("foundation", "build-tools"):
            matrix = groups[group]["specs"][0]["matrix"]
            self.assertEqual(len(matrix), 2, f"{group} lost its compiler binding")

        payload_matrix = groups["payload"]["specs"][0]["matrix"]
        self.assertEqual(len(payload_matrix), 1, "payload constrains MPI externals")

        mpi_spec = groups["mpi"]["specs"][0]
        self.assertNotIn("target=", mpi_spec)
        self.assertNotIn("%", mpi_spec)

    def test_mpi_provider_requirement_does_not_constrain_external_architecture(self) -> None:
        test_values = values()
        for surface in ("shared", "platform"):
            with self.subTest(surface=surface):
                rendered = render(
                    f"configs/surfaces/{surface}/packages.yaml.j2",
                    values=test_values,
                )
                requirement = rendered["packages"]["mpi"]["require"]
                self.assertEqual(
                    requirement,
                    [test_values[surface]["mpi"]["provider_constraint"]],
                )
                self.assertNotIn("target=", requirement[0])
                self.assertNotIn("%", requirement[0])


if __name__ == "__main__":
    unittest.main()
