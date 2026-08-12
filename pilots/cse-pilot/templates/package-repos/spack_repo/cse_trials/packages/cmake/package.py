from spack_repo.builtin.packages.cmake.package import Cmake as BuiltinCmake

from spack.package import *


class Cmake(BuiltinCmake):
    """CMake recipe extension for the initial conversion trials."""

    version(
        "4.4.2",
        sha256="1db9e61e60b6e0874c86386340b910382f3c5e75b9fbfb44d122063129a2789d",
    )
    version(
        "3.31.12",
        sha256="5f3fd5a54dfa65602bdbed64f981a72673cc19f2d304cc2955cf0dfa0cfd8272",
        preferred=True,
    )
