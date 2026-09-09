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
BLUEBACK_NOTES = Path(__file__).resolve().parents[3] / "systems" / "blueback" / "runbook-notes.md"
OVERLAY_WORKFLOW = Path(__file__).resolve().parents[1] / "PACKAGE-OVERLAY-WORKFLOW.md"


class PackageRepoOverlayTests(unittest.TestCase):
    def test_overlay_workflow_preserves_trial_release_boundaries(self) -> None:
        workflow = OVERLAY_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Do not edit Spack's cached `builtin` repository", workflow)
        self.assertIn("cse_trials` repository must appear before `builtin", workflow)
        self.assertIn("concretize -f --reuse-deps -j 1", workflow)
        self.assertIn("./cse-build login verify", workflow)
        self.assertIn("./cse-build compute install --surface platform", workflow)
        self.assertIn("Return the correction to Stack Content", workflow)
        self.assertIn("Recipe correction request", workflow)

    def test_blueback_perl_zlib_diagnosis_targets_the_cce_core_lock(self) -> None:
        notes = BLUEBACK_NOTES.read_text(encoding="utf-8")
        diagnosis = notes.split(
            "### CCE Perl 5.42 zlib library-discovery failure", 1
        )[1].split("### GNU LAPACK reports", 1)[0]

        self.assertIn(
            'PLATFORM_CORE_ENV="$CSE_BUILD_WORKSPACE/environments/'
            '$PLATFORM_COMPILER_NAME/core"',
            diagnosis,
        )
        self.assertIn('spec -Il perl@5.42.0', diagnosis)
        self.assertIn('find -clpv zlib@1.3.1', diagnosis)
        self.assertIn('ZLIB_PREFIX="<CCE-zlib-prefix-from-the-listing>"', diagnosis)
        self.assertIn("-name 'libz.so*'", diagnosis)
        self.assertIn("-name 'libz.a'", diagnosis)
        self.assertIn('"$ZLIB_PREFIX/.spack/spack-build-out.txt"', diagnosis)
        self.assertIn("Do not reconcretize", diagnosis)

    def test_blueback_zlib_recovery_updates_every_cce_lock(self) -> None:
        notes = BLUEBACK_NOTES.read_text(encoding="utf-8")
        recovery = notes.split(
            "#### Confirmed Blueback cause and workspace recovery", 1
        )[1].split("### GNU LAPACK reports", 1)[0]

        shell_entry = 'cd "$BUILD_WORKSPACE"\n./cse-build login shell'
        workspace_guard = (
            ': "${CSE_BUILD_WORKSPACE:?Run this block inside '
            './cse-build login shell}"'
        )
        destination = (
            'ZLIB_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/'
            'spack_repo/cse_trials/packages/zlib"'
        )

        self.assertIn(shell_entry, recovery)
        self.assertIn(workspace_guard, recovery)
        self.assertIn(
            'ZLIB_SOURCE="$CONTENT/pilots/cse-pilot/templates/'
            'package-repos/spack_repo/cse_trials/packages/zlib"',
            recovery,
        )
        self.assertIn(destination, recovery)
        self.assertIn('"$ZLIB_SOURCE/cce-lld-version-map.patch"', recovery)
        self.assertIn(
            'for environment in core common serial "mpi-$PLATFORM_MPI_NAME"',
            recovery,
        )
        self.assertIn("concretize -f --reuse-deps -j 1", recovery)
        self.assertIn("./cse-build compute install --surface platform", recovery)
        self.assertIn("libz.so.1.3.1", recovery)

    def test_blueback_recovery_installs_ncurses_overlay_before_reconcretizing(self) -> None:
        notes = BLUEBACK_NOTES.read_text(encoding="utf-8")
        recovery = notes.split("### CCE ncurses 6.6 LLD version-map failure", 1)[1].split(
            "### GNU LAPACK reports", 1
        )[0]

        shell_entry = 'cd "$BUILD_WORKSPACE"\n./cse-build login shell'
        workspace_guard = (
            ': "${CSE_BUILD_WORKSPACE:?Run this block inside '
            './cse-build login shell}"'
        )
        destination = (
            'NCURSES_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/'
            'spack_repo/cse_trials/packages/ncurses"'
        )

        self.assertIn(shell_entry, recovery)
        self.assertIn(workspace_guard, recovery)
        self.assertLess(recovery.index(workspace_guard), recovery.index(destination))
        self.assertIn(
            'NCURSES_SOURCE="$CONTENT/pilots/cse-pilot/templates/'
            'package-repos/spack_repo/cse_trials/packages/ncurses"',
            recovery,
        )
        self.assertIn(destination, recovery)
        self.assertIn("concretize -f --reuse-deps -j 1", recovery)
        self.assertIn("./cse-build compute install --surface platform", recovery)

    def test_raider_recovery_uses_rendered_dakota_overlay_paths(self) -> None:
        notes = RAIDER_NOTES.read_text(encoding="utf-8")
        recovery = notes.split(
            "### Recover an already-rendered Raider workspace", 1
        )[1].split("## AOCC HDF5 2.1.0 parallel-Fortran failure", 1)[0]
        shell_entry = 'cd "$BUILD_WORKSPACE"\n./cse-build login shell'
        workspace_guard = (
            ': "${CSE_BUILD_WORKSPACE:?Run this block inside '
            './cse-build login shell}"'
        )
        destination = (
            'RAIDER_DAKOTA_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/'
            'spack_repo/cse_trials/packages/dakota"'
        )

        self.assertIn(shell_entry, recovery)
        self.assertIn(workspace_guard, recovery)
        self.assertLess(
            recovery.index(workspace_guard), recovery.index(destination)
        )

        self.assertIn(
            'RAIDER_DAKOTA_SOURCE="$CONTENT/pilots/cse-pilot/templates/'
            'package-repos/spack_repo/cse_trials/packages/dakota"',
            recovery,
        )
        self.assertIn(destination, recovery)
        self.assertIn("-name 'spack-stage-dakota-6.2[34].0-*'", notes)
        self.assertIn(
            '"$SHARED_COMPILER_NAME/mpi-$SHARED_MPI_NAME"',
            recovery,
        )
        self.assertIn(
            '"$PLATFORM_COMPILER_NAME/mpi-$PLATFORM_MPI_NAME"',
            recovery,
        )

    def test_raider_recovery_uses_rendered_hdf5_overlay_paths(self) -> None:
        notes = RAIDER_NOTES.read_text(encoding="utf-8")
        recovery = notes.split(
            "### Recover the already-rendered Raider AOCC workspace", 1
        )[1]

        shell_entry = 'cd "$BUILD_WORKSPACE"\n./cse-build login shell'
        workspace_guard = (
            ': "${CSE_BUILD_WORKSPACE:?Run this block inside '
            './cse-build login shell}"'
        )
        destination = (
            'RAIDER_HDF5_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/'
            'spack_repo/cse_trials/packages/hdf5"'
        )

        self.assertIn(shell_entry, recovery)
        self.assertIn(workspace_guard, recovery)
        self.assertLess(
            recovery.index(workspace_guard), recovery.index(destination)
        )

        self.assertIn(
            'RAIDER_HDF5_SOURCE="$CONTENT/pilots/cse-pilot/templates/'
            'package-repos/spack_repo/cse_trials/packages/hdf5"',
            recovery,
        )
        self.assertIn(destination, recovery)
        self.assertIn(
            'RAIDER_AOCC_MPI_ENV="$CSE_BUILD_WORKSPACE/environments/'
            '$PLATFORM_COMPILER_NAME/mpi-$PLATFORM_MPI_NAME"',
            recovery,
        )
        self.assertIn("concretize -f --reuse-deps -j 1", recovery)
        self.assertIn("--fail-fast hdf5@2.1.0", recovery)

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

    def test_ncurses_overlay_allows_lld_undefined_versions_only_for_cce_6_6(self) -> None:
        recipe = (PACKAGE_ROOT / "ncurses" / "package.py").read_text(encoding="utf-8")

        ast.parse(recipe)
        self.assertIn('self.spec.satisfies("@6.6 %cce")', recipe)
        self.assertIn('flags.append("-Wl,--undefined-version")', recipe)

    def test_zlib_overlay_covers_verified_cce_shared_versions(self) -> None:
        recipe = (PACKAGE_ROOT / "zlib" / "package.py").read_text(encoding="utf-8")
        patch = (PACKAGE_ROOT / "zlib" / "cce-lld-version-map.patch").read_text(
            encoding="utf-8"
        )

        ast.parse(recipe)
        self.assertIn(
            'patch("cce-lld-version-map.patch", '
            'when="@1.2.13:1.3.2+shared %cce")',
            recipe,
        )
        self.assertIn("--undefined-version,--version-script", patch)
        self.assertEqual(patch.count("--undefined-version"), 1)

    @unittest.skipUnless(shutil.which("patch"), "patch is not installed")
    def test_zlib_patch_preserves_versioning_and_accepts_missing_probe_symbols(self) -> None:
        configure_source = """\
  case "$uname" in
  Linux* | linux* | *-linux* | GNU | GNU/* | solaris*)
        case "$mname" in
        *sparc*)
            LDFLAGS="${LDFLAGS} -Wl,--no-warn-rwx-segments" ;;
        esac
        LDSHARED=${LDSHARED-"$cc -shared -Wl,-soname,libz.so.1,--version-script,${SRCDIR}zlib.map"} ;;
  *BSD | *bsd* | DragonFly)
"""
        patch_path = PACKAGE_ROOT / "zlib" / "cce-lld-version-map.patch"

        with tempfile.TemporaryDirectory() as temporary:
            configure_path = Path(temporary) / "configure"
            configure_path.write_text(configure_source, encoding="utf-8")
            result = subprocess.run(
                ["patch", "-p1", "--input", str(patch_path)],
                cwd=temporary,
                check=False,
                text=True,
                capture_output=True,
            )
            patched = configure_path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "-Wl,-soname,libz.so.1,--undefined-version,--version-script,",
            patched,
        )
        self.assertNotIn(
            "-Wl,-soname,libz.so.1,--version-script,",
            patched,
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
