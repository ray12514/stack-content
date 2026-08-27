from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "package-repos"
    / "spack_repo"
    / "cse_trials"
    / "packages"
)
RAIDER_NOTES = Path(__file__).resolve().parents[3] / "systems" / "raider" / "runbook-notes.md"


class PackageRepoOverlayTests(unittest.TestCase):
    def test_raider_recovery_uses_rendered_dakota_overlay_paths(self) -> None:
        notes = RAIDER_NOTES.read_text(encoding="utf-8")

        self.assertIn(
            'RAIDER_DAKOTA_SOURCE="$CONTENT/pilots/cse-pilot/templates/'
            'package-repos/spack_repo/cse_trials/packages/dakota"',
            notes,
        )

    def test_raider_recovery_uses_rendered_hdf5_overlay_paths(self) -> None:
        notes = RAIDER_NOTES.read_text(encoding="utf-8")

        self.assertIn(
            'RAIDER_HDF5_SOURCE="$CONTENT/pilots/cse-pilot/templates/'
            'package-repos/spack_repo/cse_trials/packages/hdf5"',
            notes,
        )
        self.assertIn(
            'RAIDER_HDF5_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/'
            'spack_repo/cse_trials/packages/hdf5"',
            notes,
        )
        self.assertIn(
            '"$PLATFORM_COMPILER_NAME/mpi-$PLATFORM_MPI_NAME"',
            notes,
        )
        self.assertIn("concretize -f --reuse-deps -j 1", notes)
        self.assertIn("--fail-fast hdf5@2.1.0", notes)
        self.assertIn(
            'RAIDER_DAKOTA_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/'
            'spack_repo/cse_trials/packages/dakota"',
            notes,
        )
        self.assertIn("-name 'spack-stage-dakota-6.2[34].0-*'", notes)
        self.assertIn(
            '"$SHARED_COMPILER_NAME/mpi-$SHARED_MPI_NAME"',
            notes,
        )
        self.assertIn(
            '"$PLATFORM_COMPILER_NAME/mpi-$PLATFORM_MPI_NAME"',
            notes,
        )

    def test_dakota_overlay_limits_boost_system_fix_to_trial_versions(self) -> None:
        recipe = (PACKAGE_ROOT / "dakota" / "package.py").read_text(encoding="utf-8")

        ast.parse(recipe)
        self.assertIn(
            'patch("boost-system-header-only.patch", when="@6.23.0:6.24.0")',
            recipe,
        )

    def test_hdf5_overlay_limits_module_fix_to_2_1_0_parallel_fortran_hl(self) -> None:
        recipe = (PACKAGE_ROOT / "hdf5" / "package.py").read_text(encoding="utf-8")

        ast.parse(recipe)
        self.assertIn(
            'patch("parallel-fortran-module-dir.patch", '
            'when="@2.1.0+mpi+fortran+hl")',
            recipe,
        )

    @unittest.skipUnless(shutil.which("patch"), "patch is not installed")
    def test_hdf5_patch_adds_module_dir_to_both_high_level_targets(self) -> None:
        cmake_source = """\
if (BUILD_STATIC_LIBS)
  add_library (${HDF5_HL_F90_LIB_TARGET} STATIC ${HDF5_HL_F90_F_SOURCES})
  target_include_directories (${HDF5_HL_F90_LIB_TARGET}
      PRIVATE "${HDF5_F90_BINARY_DIR};${CMAKE_Fortran_MODULE_DIRECTORY}/static;$<$<BOOL:${HDF5_ENABLE_PARALLEL}>:${MPI_Fortran_INCLUDE_DIRS}>"
      INTERFACE "$<INSTALL_INTERFACE:$<INSTALL_PREFIX>/${HDF5_INSTALL_MODULE_DIR}/static>"
  )
  target_compile_options(${HDF5_HL_F90_LIB_TARGET} PRIVATE "${HDF5_CMAKE_Fortran_FLAGS}")
endif ()
if (BUILD_SHARED_LIBS)
  add_library (${HDF5_HL_F90_LIBSH_TARGET} SHARED ${DLLDEF} ${HDF5_HL_F90_F_SOURCES_SHARED})
  target_include_directories (${HDF5_HL_F90_LIBSH_TARGET}
      PRIVATE "${HDF5_F90_BINARY_DIR};${CMAKE_Fortran_MODULE_DIRECTORY}/shared;$<$<BOOL:${HDF5_ENABLE_PARALLEL}>:${MPI_Fortran_INCLUDE_DIRS}>"
      INTERFACE "$<INSTALL_INTERFACE:$<INSTALL_PREFIX>/${HDF5_INSTALL_MODULE_DIR}/shared>"
  )
  target_compile_options(${HDF5_HL_F90_LIBSH_TARGET} PRIVATE "${HDF5_CMAKE_Fortran_FLAGS}")
endif ()
"""
        patch_path = PACKAGE_ROOT / "hdf5" / "parallel-fortran-module-dir.patch"

        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "hl" / "fortran" / "src" / "CMakeLists.txt"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(cmake_source, encoding="utf-8")
            result = subprocess.run(
                ["patch", "-p1", "--input", str(patch_path)],
                cwd=temporary,
                check=False,
                text=True,
                capture_output=True,
            )
            patched = source_path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(patched.count("${MPI_Fortran_MODULE_DIR}"), 2)

    @unittest.skipUnless(shutil.which("patch"), "patch is not installed")
    def test_dakota_patch_removes_all_removed_boost_system_references(self) -> None:
        find_system_tpls_source = """\
macro(dakota_find_boost)

  if(WIN32)
    # BMA TODO: Relax this and document
    set(Boost_USE_STATIC_LIBS TRUE)
  endif()

  # Dakota requires the specified compiled Boost library components
  # Dakota requires Boost 1.70 or newer ; enforce for all libs in the build
  set(dakota_boost_libs program_options regex serialization system)

  if(DAKOTA_APPLE_FIX_BOOSTLIBS)
    # This approach requires separate include and lib dirs
    # Macro publishes _dakota_boost_includedir
    dakota_fix_boost_dylibs("${dakota_boost_libs}"
      "${CMAKE_CURRENT_BINARY_DIR}/boost_libs")
    set(BOOST_ROOT)
    set(BOOST_INCLUDEDIR "${_dakota_boost_includedir}")
    set(BOOST_LIBRARYDIR "${CMAKE_CURRENT_BINARY_DIR}/boost_libs")
  endif()

  # std::unary_function and std::binary_function were removed from the C++17 standard library
  # but are used by default in Boost until version 1.80.0
  if(CMAKE_CXX_STANDARD GREATER_EQUAL 17)
    # Removes use of std::unary_function in boost/container_hash/hash.hpp
    add_compile_definitions(BOOST_NO_CXX98_FUNCTION_BASE)

    # Removes use of std::unary_function and std::binary_function in boost/functional.hpp
    add_compile_definitions(_HAS_AUTO_PTR_ETC=0)
  endif()


  find_package(Boost 1.70 REQUIRED COMPONENTS ${dakota_boost_libs})
  #message(STATUS "Found Boost version ${Boost_VERSION}")

  set(DAKOTA_BOOST_TARGETS Boost::boost Boost::program_options
    Boost::regex Boost::serialization Boost::system)

  set(dakota_boost_libs "${dakota_boost_libs}" CACHE STRING "")
  set(dakota_boost_version "${Boost_VERSION_MAJOR}.${Boost_VERSION_MINOR}.${Boost_VERSION_PATCH}" CACHE STRING "")
endmacro()
"""
        plugins_source = """\
set_target_properties(generic_python_plugin PROPERTIES CXX_STANDARD 17)
set_target_properties(generic_python_plugin PROPERTIES CXX_VISIBILITY_PRESET hidden)

find_package(Boost 1.70 REQUIRED COMPONENTS system)
# handle special case for gcc filesystem support
if((CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 9.0) OR DAKOTA_LINK_STDCPPFS)
  target_link_libraries(generic_python_plugin
    PUBLIC Boost::system stdc++fs
    PRIVATE pybind11::embed Python::Python
  )
else()
    target_link_libraries(generic_python_plugin
      PUBLIC Boost::system
      PRIVATE pybind11::embed Python::Python
    )
endif()
"""
        surrogates_unit_source = """\
endif()

dakota_add_unit_test(NAME surrogates_polynomial_regression
  SOURCES PolynomialRegressionTest.cpp
  LINK_LIBS dakota_surrogates Boost::system )

dakota_add_unit_test(NAME surrogates_tools
  SOURCES SurrogatesToolsTest.cpp

if(DAKOTA_PYTHON_SURROGATES)

  dakota_add_unit_test(NAME surrogates_python_pybind11
    SOURCES PythonSurrogatesTest.cpp
    LINK_LIBS dakota_surrogates Boost::system )
  # Rationale: This includes Teuchos headers and needs to link to the
  # ParameterList components. It also includes SurrogatesPython.hpp, which
  # depends on pybind11 headers that are build-only details of dakota_surrogates.
"""
        patch_path = PACKAGE_ROOT / "dakota" / "boost-system-header-only.patch"

        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            sources = {
                Path("cmake/DakotaFindSystemTPLs.cmake"): find_system_tpls_source,
                Path("src/plugins/CMakeLists.txt"): plugins_source,
                Path("src/surrogates/unit/CMakeLists.txt"): surrogates_unit_source,
            }
            for relative_path, contents in sources.items():
                source_path = source_root / relative_path
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(contents, encoding="utf-8")
            result = subprocess.run(
                ["patch", "-p1", "--input", str(patch_path)],
                cwd=temporary,
                check=False,
                text=True,
                capture_output=True,
            )
            patched_sources = {
                relative_path: (source_root / relative_path).read_text(encoding="utf-8")
                for relative_path in sources
            }

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "set(dakota_boost_libs program_options regex serialization)",
            patched_sources[Path("cmake/DakotaFindSystemTPLs.cmake")],
        )
        self.assertIn(
            "Boost::serialization)",
            patched_sources[Path("cmake/DakotaFindSystemTPLs.cmake")],
        )
        self.assertIn(
            "Boost::program_options",
            patched_sources[Path("cmake/DakotaFindSystemTPLs.cmake")],
        )
        self.assertIn(
            "Boost::regex",
            patched_sources[Path("cmake/DakotaFindSystemTPLs.cmake")],
        )
        for relative_path, patched in patched_sources.items():
            self.assertNotIn("Boost::system", patched, str(relative_path))


if __name__ == "__main__":
    unittest.main()
