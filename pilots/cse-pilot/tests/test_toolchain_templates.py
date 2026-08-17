from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"


def render(template: str, **context: object) -> dict:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    environment.filters["yaml_scalar"] = json.dumps
    return yaml.safe_load(environment.get_template(template).render(**context))


def values() -> dict:
    return {
        "architecture": {"target": "x86_64_v3", "binary_target": "x86_64"},
        "catalog_scopes": {"common": "scopes/common", "platform": None},
        "paths": {"views_root": "/views"},
        "shared": {
            "compiler": {
                "name": "gcc",
                "version": "12.5.0",
                "source": "build",
                "build_with": {"name": "gcc", "version": "12.2.1"},
            },
            "mpi": {
                "name": "openmpi",
                "version": "4.1.8",
                "source": "build",
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
            "compiler": {"name": "aocc", "version": "4.1.0", "source": "external"},
            "mpi": {
                "name": "openmpi",
                "version": "4.1.8",
                "source": "build",
                "spec": (
                    "openmpi@4.1.8 fabrics=ucx schedulers=slurm +pmi "
                    "^ucx@1.18.0+thread_multiple ^slurm@23.02.7"
                ),
                "provider_constraint": (
                    "openmpi@4.1.8 fabrics=ucx schedulers=slurm +pmi"
                ),
            },
            "catalog_scopes": {"compiler": "scopes/compilers/aocc/4.1.0"},
        },
    }


class ToolchainTemplateTests(unittest.TestCase):
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
