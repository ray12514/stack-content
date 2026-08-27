from spack_repo.builtin.packages.hdf5.package import Hdf5 as BuiltinHdf5

from spack.package import *


class Hdf5(BuiltinHdf5):
    """HDF5 fixes required by the initial conversion trials."""

    # HDF5 2.1.0's high-level parallel Fortran targets omit the separate
    # module directory reported by CMake's FindMPI. OpenMPI installations
    # may place mpi_f08_types.mod there instead of in MPI_Fortran_INCLUDE_DIRS.
    patch("parallel-fortran-module-dir.patch", when="@2.1.0+mpi+fortran+hl")
