from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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


class BuildContextTests(unittest.TestCase):
    def test_login_and_compute_contexts_have_independent_stage_fallbacks(self) -> None:
        manifest = {
            "profile_facts": {
                "node_types": {
                    "login": {
                        "role": "build_host",
                        "build_stage": [
                            {
                                "path": "/tmp/tester",
                                "visibility": "node-local",
                                "writable": True,
                                "mount_opts": ["rw"],
                            }
                        ],
                    },
                    "cpu_compute": {
                        "role": "runtime",
                        "build_stage": [
                            {
                                "path": "/scratch/tester",
                                "visibility": "compute-only",
                                "writable": True,
                                "mount_opts": ["rw"],
                            }
                        ],
                    },
                }
            }
        }

        with tempfile.TemporaryDirectory() as workdir:
            with mock.patch.dict(
                os.environ,
                {
                    "WORKDIR": workdir,
                    "USER": "tester",
                    "CSE_LOGIN_NODE_TYPE": "login",
                    "CSE_COMPUTE_NODE_TYPE": "cpu_compute",
                },
                clear=False,
            ):
                contexts = CREATE_BUILD_VALUES.build_contexts(
                    manifest,
                    system_name="fran",
                    release="fran-trial-001",
                )

        self.assertEqual(contexts["login"]["node_type"], "login")
        self.assertEqual(contexts["compute"]["node_type"], "cpu_compute")
        self.assertEqual(
            contexts["login"]["stages"][-1],
            "${WORKDIR}/cse-spack-stage/fran/fran-trial-001/login",
        )
        self.assertEqual(
            contexts["compute"]["stages"][-1],
            "${WORKDIR}/cse-spack-stage/fran/fran-trial-001/compute",
        )
        self.assertNotEqual(
            contexts["login"]["stages"],
            contexts["compute"]["stages"],
        )

    def test_known_noexec_stage_is_not_rendered(self) -> None:
        manifest = {
            "profile_facts": {
                "node_types": {
                    "login": {
                        "build_stage": [
                            {
                                "path": "/tmp/tester",
                                "writable": True,
                                "mount_opts": ["rw", "noexec"],
                            }
                        ]
                    },
                    "cpu_compute": {"build_stage": []},
                }
            }
        }

        with tempfile.TemporaryDirectory() as workdir:
            with mock.patch.dict(
                os.environ,
                {
                    "WORKDIR": workdir,
                    "USER": "tester",
                    "CSE_LOGIN_NODE_TYPE": "login",
                    "CSE_COMPUTE_NODE_TYPE": "cpu_compute",
                },
                clear=False,
            ):
                contexts = CREATE_BUILD_VALUES.build_contexts(
                    manifest,
                    system_name="fran",
                    release="fran-trial-001",
                )

        self.assertEqual(
            contexts["login"]["stages"],
            ["${WORKDIR}/cse-spack-stage/fran/fran-trial-001/login"],
        )

    def test_context_node_type_selections_are_required(self) -> None:
        manifest = {
            "profile_facts": {
                "node_types": {
                    "login": {"build_stage": []},
                    "cpu_compute": {"build_stage": []},
                }
            }
        }

        with tempfile.TemporaryDirectory() as workdir:
            with mock.patch.dict(
                os.environ,
                {
                    "WORKDIR": workdir,
                    "USER": "tester",
                    "CSE_LOGIN_NODE_TYPE": "",
                    "CSE_COMPUTE_NODE_TYPE": "",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(
                    CREATE_BUILD_VALUES.InputError,
                    "CSE_LOGIN_NODE_TYPE",
                ):
                    CREATE_BUILD_VALUES.build_contexts(
                        manifest,
                        system_name="fran",
                        release="fran-trial-001",
                    )


class PlatformCompilerRuntimeTests(unittest.TestCase):
    def test_compiler_activation_commands_follow_the_selected_module_chain(self) -> None:
        self.assertEqual(
            CREATE_BUILD_VALUES.compiler_activation_commands("gcc", []),
            {"c": "gcc", "cxx": "g++", "fortran": "gfortran"},
        )
        self.assertEqual(
            CREATE_BUILD_VALUES.compiler_activation_commands(
                "cce", ["PrgEnv-cray", "cce/17.0.1"]
            ),
            {"c": "cc", "cxx": "CC", "fortran": "ftn"},
        )

    def test_mpi_activation_commands_follow_the_selected_provider(self) -> None:
        self.assertEqual(
            CREATE_BUILD_VALUES.mpi_activation_commands("openmpi"),
            {"c": "mpicc", "cxx": "mpicxx", "fortran": "mpifort"},
        )
        self.assertEqual(
            CREATE_BUILD_VALUES.mpi_activation_commands("cray-mpich"),
            {"c": "cc", "cxx": "CC", "fortran": "ftn"},
        )

    def test_only_oneapi_reuses_the_gcc_seed_scope(self) -> None:
        seed_scope = "scopes/compilers/gcc/12.2.1"

        self.assertEqual(
            CREATE_BUILD_VALUES.platform_runtime_compiler_scope(
                "oneapi", seed_scope
            ),
            seed_scope,
        )
        for provider in ("aocc", "cce", "intel"):
            with self.subTest(provider=provider):
                self.assertIsNone(
                    CREATE_BUILD_VALUES.platform_runtime_compiler_scope(
                        provider, seed_scope
                    )
                )


class OpenMpiSpecTests(unittest.TestCase):
    def test_source_built_non_openmpi_provider_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            CREATE_BUILD_VALUES.InputError,
            "source-built MPI is supported only for openmpi",
        ):
            CREATE_BUILD_VALUES.openmpi_build_specs(
                "cray-mpich",
                "9.1.0",
                {},
                {"profile_facts": {"system_externals": []}},
            )

    def test_no_scheduler_external_uses_standard_mpi_launchers(self) -> None:
        root_spec, provider_constraint = CREATE_BUILD_VALUES.openmpi_build_specs(
            "openmpi",
            "4.1.8",
            {"ucx": ["ucx@1.18.0 +thread_multiple"]},
            {"profile_facts": {"system_externals": []}},
        )

        self.assertIn("schedulers=none", provider_constraint)
        self.assertIn("+rsh", provider_constraint)
        self.assertIn("+fortran", provider_constraint)
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
        self.assertIn("+fortran", provider_constraint)
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
        self.assertIn("+fortran", provider_constraint)
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


class ExternalMpiConsumerTests(unittest.TestCase):
    def write_cray_scope(
        self,
        catalog: Path,
        *,
        externals: list[dict] | None = None,
        variants: str = "+wrappers",
    ) -> str:
        relative = "scopes/mpi/cray-mpich/9.1.0/gcc-12.3"
        scope = catalog / relative
        scope.mkdir(parents=True)
        packages = {
            "packages": {
                "cray-mpich": {
                    "buildable": False,
                    "variants": variants,
                    "externals": externals
                    or [
                        {
                            "spec": "cray-mpich@9.1.0",
                            "prefix": "/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3",
                            "modules": ["cray-mpich/9.1.0"],
                            "extra_attributes": {
                                "environment": {
                                    "prepend_path": {
                                        "LD_LIBRARY_PATH": (
                                            "/opt/cray/libfabric/2.3.1/lib64"
                                        )
                                    }
                                }
                            },
                        }
                    ],
                }
            }
        }
        (scope / "packages.yaml").write_text(
            CREATE_BUILD_VALUES.yaml.safe_dump(packages, sort_keys=False),
            encoding="utf-8",
        )
        return relative

    def test_external_cray_mpi_exposes_normalized_candidate_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary)
            relative = self.write_cray_scope(catalog)

            consumer = CREATE_BUILD_VALUES.external_mpi_consumer(
                catalog=catalog,
                scope_path=relative,
                package_name="cray-mpich",
                version="9.1.0",
            )

        prefix = "/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3"
        self.assertEqual(
            consumer["status"], "multi-node-validation-required"
        )
        self.assertEqual(consumer["interface"], "vendor-wrapper")
        self.assertEqual(
            consumer["wrapper_provider"], "cray-mpich-simple-wrapper"
        )
        self.assertEqual(consumer["prefix"], prefix)
        self.assertEqual(
            consumer["wrappers"],
            {
                "c": f"{prefix}/bin/mpicc",
                "cxx": f"{prefix}/bin/mpicxx",
                "fortran": f"{prefix}/bin/mpifort",
                "fortran90": f"{prefix}/bin/mpif90",
                "fortran77": f"{prefix}/bin/mpif77",
            },
        )
        self.assertEqual(
            consumer["runtime_environment"],
            {
                "prepend_path": {
                    "LD_LIBRARY_PATH": ["/opt/cray/libfabric/2.3.1/lib64"]
                }
            },
        )

    def test_mpi_values_adds_consumer_data_without_changing_the_provider_spec(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary)
            relative = self.write_cray_scope(catalog)
            mpi, selected_scope = CREATE_BUILD_VALUES.mpi_values(
                surface="cse",
                source="external",
                provider_ref="cray-mpich@9.1.0",
                compiler_ref="gcc@12.5.0",
                scopes=[
                    {
                        "kind": "mpi",
                        "name": "cray-mpich",
                        "package": "cray-mpich",
                        "version": "9.1.0",
                        "compiler_ref": "gcc@12.3",
                        "path": relative,
                    }
                ],
                module_map={relative: ["cray-mpich/9.1.0"]},
                catalog=catalog,
                common_externals={},
                manifest={},
            )

        self.assertEqual(selected_scope, relative)
        self.assertEqual(mpi["spec"], "cray-mpich@9.1.0")
        self.assertEqual(mpi["provider_constraint"], "cray-mpich@9.1.0")
        self.assertEqual(mpi["modules"], ["cray-mpich/9.1.0"])
        self.assertEqual(
            mpi["consumer"]["prefix"],
            "/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3",
        )

    def test_external_cray_mpi_rejects_ambiguous_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary)
            relative = self.write_cray_scope(
                catalog,
                externals=[
                    {
                        "spec": "cray-mpich@9.1.0",
                        "prefix": "/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3",
                    },
                    {
                        "spec": "cray-mpich@9.1.0",
                        "prefix": "/another/prefix",
                    },
                ],
            )

            with self.assertRaisesRegex(
                CREATE_BUILD_VALUES.InputError,
                "exactly one cray-mpich@9.1.0 external",
            ):
                CREATE_BUILD_VALUES.external_mpi_consumer(
                    catalog=catalog,
                    scope_path=relative,
                    package_name="cray-mpich",
                    version="9.1.0",
                )

    def test_external_cray_mpi_requires_wrapper_enabled_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary)
            relative = self.write_cray_scope(catalog, variants="")

            with self.assertRaisesRegex(
                CREATE_BUILD_VALUES.InputError,
                r"must enable \+wrappers",
            ):
                CREATE_BUILD_VALUES.external_mpi_consumer(
                    catalog=catalog,
                    scope_path=relative,
                    package_name="cray-mpich",
                    version="9.1.0",
                )

    def test_module_front_door_name_must_be_one_path_segment(self) -> None:
        with self.assertRaisesRegex(
            CREATE_BUILD_VALUES.InputError,
            "CSE_SHARED_COMPILER_PUBLIC_NAME",
        ):
            CREATE_BUILD_VALUES.safe_path_segment(
                "init/GCC", "CSE_SHARED_COMPILER_PUBLIC_NAME"
            )

    def test_compiler_front_door_names_must_be_distinct(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CSE_SHARED_COMPILER_PUBLIC_NAME": "init-CSE",
                "CSE_PLATFORM_COMPILER_PUBLIC_NAME": "init-CSE",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                CREATE_BUILD_VALUES.InputError,
                "must be distinct",
            ):
                CREATE_BUILD_VALUES.public_compiler_module_names()


if __name__ == "__main__":
    unittest.main()
