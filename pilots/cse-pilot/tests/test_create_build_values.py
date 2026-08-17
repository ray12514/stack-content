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


if __name__ == "__main__":
    unittest.main()
