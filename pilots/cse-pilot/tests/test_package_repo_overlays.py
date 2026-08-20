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


class PackageRepoOverlayTests(unittest.TestCase):
    def test_dakota_overlay_limits_boost_system_fix_to_trial_versions(self) -> None:
        recipe = (PACKAGE_ROOT / "dakota" / "package.py").read_text(encoding="utf-8")

        ast.parse(recipe)
        self.assertIn(
            'patch("boost-system-header-only.patch", when="@6.23.0:6.24.0")',
            recipe,
        )

    @unittest.skipUnless(shutil.which("patch"), "patch is not installed")
    def test_dakota_patch_removes_only_removed_boost_system_component(self) -> None:
        source = """\
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
        patch_path = PACKAGE_ROOT / "dakota" / "boost-system-header-only.patch"

        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "cmake" / "DakotaFindSystemTPLs.cmake"
            source_path.parent.mkdir()
            source_path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                ["patch", "-p1", "--input", str(patch_path)],
                cwd=temporary,
                check=False,
                text=True,
                capture_output=True,
            )
            patched = source_path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "set(dakota_boost_libs program_options regex serialization)", patched
        )
        self.assertIn("Boost::serialization)", patched)
        self.assertNotIn("Boost::system", patched)
        self.assertIn("Boost::program_options", patched)
        self.assertIn("Boost::regex", patched)


if __name__ == "__main__":
    unittest.main()
