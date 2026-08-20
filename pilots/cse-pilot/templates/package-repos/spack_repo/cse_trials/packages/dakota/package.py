from spack_repo.builtin.packages.dakota.package import Dakota as BuiltinDakota

from spack.package import *


class Dakota(BuiltinDakota):
    """Dakota fixes required by the initial conversion trials."""

    # Boost.System is header-only for every Boost release Dakota 6.23+
    # supports. Boost 1.89 removed its compiled compatibility stub, but these
    # Dakota releases still request the removed CMake component and target.
    patch("boost-system-header-only.patch", when="@6.23.0:6.24.0")
