from __future__ import annotations

import ast
import json
import shlex
import shutil
import subprocess
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
                "build_with": {"name": "gcc", "version": "12.2.1"},
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

    def test_gcc_producer_explicitly_enables_binutils(self) -> None:
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
            shared["compiler_producer"]["tcl"]["include"], ["gcc@12.5.0"]
        )
        self.assertEqual(shared["default"]["tcl"]["exclude"], ["@:"])
        self.assertIn("pkgconf %gcc@12.5.0", shared["default"]["tcl"]["include"])
        self.assertIn(
            "python@3.12.13 %gcc@12.5.0", shared["default"]["tcl"]["include"]
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

    def test_language_provider_preferences_are_surface_specific(self) -> None:
        test_values = values()
        cases = {
            "configs/surfaces/shared/compiler.yaml.j2": "gcc@12.5.0",
            "configs/surfaces/platform/compiler.yaml.j2": "aocc@4.1.0",
        }

        for template, expected in cases.items():
            with self.subTest(template=template):
                rendered = render(template, values=test_values)
                packages = rendered["packages"]
                for language in ("c", "cxx", "fortran"):
                    self.assertEqual(packages[language]["prefer"], [expected])

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
