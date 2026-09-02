from spack_repo.builtin.packages.ncurses.package import Ncurses as BuiltinNcurses

from spack.package import *


class Ncurses(BuiltinNcurses):
    """Ncurses linker compatibility required by the CCE trial surface."""

    def flag_handler(self, name, flags):
        flags, env_flags, build_system_flags = super().flag_handler(name, flags)

        # CCE uses LLVM lld, which rejects ncurses' intentionally broad version
        # map when the split terminfo library does not define every listed symbol.
        if name == "ldflags" and self.spec.satisfies("@6.6 %cce"):
            flags.append("-Wl,--undefined-version")

        return flags, env_flags, build_system_flags
