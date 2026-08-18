from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "create-build-values.py"
)
SPEC = importlib.util.spec_from_file_location("create_build_values", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT_PATH}")
CREATE_BUILD_VALUES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CREATE_BUILD_VALUES)


class PortableCpuTargetTests(unittest.TestCase):
    def test_gpu_node_contributes_its_cpu_architecture_facts(self) -> None:
        manifest = {
            "profile_facts": {
                "node_types": {
                    "compute": {
                        "role": "both",
                        "cpu": {
                            "detected": "zen3",
                            "preferred": "zen3",
                            "alternates": [
                                "zen2",
                                "x86_64_v3",
                                "x86_64_v2",
                                "x86_64",
                            ],
                        },
                        "gpu": {
                            "vendor": "nvidia",
                            "driver_version": "575.57.08",
                            "arch_target": "sm_86",
                        },
                    }
                }
            }
        }

        self.assertEqual(
            CREATE_BUILD_VALUES.portable_cpu_target(manifest),
            ("x86_64_v3", ["compute"]),
        )

    def test_target_is_common_to_cpu_and_gpu_bearing_nodes(self) -> None:
        manifest = {
            "profile_facts": {
                "node_types": {
                    "login": {
                        "role": "build_host",
                        "cpu": {
                            "detected": "zen3",
                            "preferred": "x86_64_v3",
                            "alternates": ["x86_64_v2", "x86_64"],
                        },
                    },
                    "compute": {
                        "role": "runtime",
                        "cpu": {
                            "detected": "zen2",
                            "preferred": "x86_64_v2",
                            "alternates": ["x86_64"],
                        },
                        "gpu": {"vendor": "nvidia", "arch_target": "sm_86"},
                    },
                }
            }
        }

        self.assertEqual(
            CREATE_BUILD_VALUES.portable_cpu_target(manifest),
            ("x86_64_v2", ["compute", "login"]),
        )


class OpenMpiSpecTests(unittest.TestCase):
    def test_no_scheduler_external_uses_standard_mpi_launchers(self) -> None:
        root_spec, provider_constraint = CREATE_BUILD_VALUES.openmpi_build_specs(
            "openmpi",
            "4.1.8",
            {"ucx": ["ucx@1.18.0 +thread_multiple"]},
            {"profile_facts": {"system_externals": []}},
        )

        self.assertIn("schedulers=none", provider_constraint)
        self.assertIn("+rsh", provider_constraint)
        self.assertNotIn("pmi", provider_constraint)
        self.assertNotIn("legacylaunchers", provider_constraint)
        self.assertEqual(
            root_spec,
            provider_constraint + " ^ucx@1.18.0+thread_multiple",
        )

    def test_provider_constraint_excludes_machine_external_dependencies(self) -> None:
        manifest = {
            "profile_facts": {
                "system_externals": [
                    {
                        "name": "slurm",
                        "version": "23.02.7",
                        "capabilities": {
                            "mpi_launch": {
                                "command": "srun",
                                "plugins": ["pmi2"],
                                "development_interfaces": ["pmi2"],
                            }
                        },
                    }
                ]
            }
        }

        root_spec, provider_constraint = CREATE_BUILD_VALUES.openmpi_build_specs(
            "openmpi",
            "4.1.8",
            {
                "ucx": ["ucx@1.18.0 +thread_multiple"],
                "slurm": ["slurm@23.02.7"],
            },
            manifest,
        )

        self.assertIn("fabrics=ucx", provider_constraint)
        self.assertIn("schedulers=slurm", provider_constraint)
        self.assertIn("+pmi", provider_constraint)
        self.assertIn("+legacylaunchers", provider_constraint)
        self.assertNotIn("^", provider_constraint)
        self.assertEqual(
            root_spec,
            provider_constraint
            + " ^ucx@1.18.0+thread_multiple ^slurm@23.02.7",
        )

    def test_pbs_external_uses_tm_without_slurm_only_variants(self) -> None:
        root_spec, provider_constraint = CREATE_BUILD_VALUES.openmpi_build_specs(
            "openmpi",
            "4.1.8",
            {
                "ucx": ["ucx@1.18.0 +thread_multiple"],
                "pbs": ["pbs@23.06.06"],
            },
            {"profile_facts": {"system_externals": []}},
        )

        self.assertIn("schedulers=tm", provider_constraint)
        self.assertIn("~rsh", provider_constraint)
        self.assertNotIn("pmi", provider_constraint)
        self.assertNotIn("legacylaunchers", provider_constraint)
        self.assertEqual(
            root_spec,
            provider_constraint + " ^ucx@1.18.0+thread_multiple ^pbs@23.06.06",
        )

    def test_multiple_scheduler_externals_are_ambiguous(self) -> None:
        with self.assertRaisesRegex(
            CREATE_BUILD_VALUES.InputError,
            "found both verified slurm and pbs externals",
        ):
            CREATE_BUILD_VALUES.openmpi_build_specs(
                "openmpi",
                "4.1.8",
                {
                    "ucx": ["ucx@1.18.0 +thread_multiple"],
                    "slurm": ["slurm@23.02.7"],
                    "pbs": ["pbs@23.06.06"],
                },
                {"profile_facts": {"system_externals": []}},
            )


if __name__ == "__main__":
    unittest.main()
