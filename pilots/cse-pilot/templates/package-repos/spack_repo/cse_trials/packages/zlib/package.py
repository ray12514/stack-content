from spack_repo.builtin.packages.zlib.package import Zlib as BuiltinZlib

from spack.package import *


class Zlib(BuiltinZlib):
    """Zlib linker compatibility required by the CCE trial surface."""

    patch("cce-lld-version-map.patch", when="@1.2.13:1.3.2+shared %cce")
