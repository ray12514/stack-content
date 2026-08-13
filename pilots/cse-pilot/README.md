# CSE Initial Conversion Trials workspace

This blueprint combines a reviewed `render-static` catalog with the approved
CPU-only trial package roster. It renders one GCC 12.5 bootstrap environment,
one shared GCC Core environment, and Common, Serial, and MPI environments for
the CSE GCC and the system's platform compiler surfaces.

The initializer does not probe the system or select a baseline compiler. Copy
`site-values.example.yaml`, then enter the exact compiler, MPI, module, prefix,
and scope choices from the reviewed static catalog. Use each recommendation's
`package` value as the corresponding `name` in the values file; the scope path
continues to use the observed provider name. This distinction matters for
Classic Intel (`intel-oneapi-compilers-classic`) and Intel MPI
(`intel-oneapi-mpi`). On non-Cray systems,
OpenMPI 4.1.8 is rendered as a build producer for both compiler surfaces. On
Cray systems, each surface selects the matching site Cray MPICH 9.x scope and
module chain.

The selected platform compiler scope is the explicit compiler for the GCC
12.5.0 bootstrap environment, so concretization does not depend on automatic
compiler discovery or shell state. Build and install that environment first,
then regenerate its `cse_compiler` view. The other seven environments consume
GCC 12.5.0 from that fixed view path as a non-buildable external. Foundation,
Core/build tools, and the CSE GCC payloads bind to that compiler explicitly.

```sh
stack-composer init-workspace \
  --blueprint stack-content/pilots/cse-pilot \
  --catalog rendered-static/<system>/static/<catalog-release> \
  --values systems/<system>/cse-trials-build-values.yaml \
  --output restricted/workspaces/<system>/initial-conversion-trials/<release>
```

The restricted and publication values retain identical package and provider
intent. They differ only in `workspace.role` and deployment paths. Publication
copies the approved lockfiles and installs with `--only-concrete
--use-buildcache=only`; it never reconcretizes or builds from source.

## Producer and reuse behavior

The bootstrap and payload workspaces use this sequence:

1. build GCC 12.5 with the selected platform compiler;
2. expose that exact installation at the fixed GCC compiler view;
3. build GCC-built Foundation and Core/build tools, including CMake 3.31.12
   and 4.4.2;
4. build a surface-specific MPI producer when the selected MPI source is
   `build`;
5. build each payload with its explicit compiler or compiler-plus-MPI
   toolchain.

The fixed compiler view separates compiler bootstrap from downstream
concretization. This is required because Spack accepts only external or already
concrete language providers for a new solve. Foundation remains single-version,
ABI-stable, and non-modular. Spack 1.2 `needs` orders and reuses Foundation,
build-tool, MPI, and payload groups within each downstream environment. The
selected CMake dependency for trial package builds is 3.31.12.
CMake 4.4.2 is installed as the second public version but is not the default
package build dependency.

The shared Spack store prevents rebuilding an already installed concrete hash.
The lockfiles remain the acceptance boundary: the downstream external GCC
identity and repeated Foundation and build-tool producers must have matching
hashes before package installation starts.

After all eight environments concretize, run the rendered
`scripts/verify-lockfiles.py`. It fails if producer hashes diverge, a payload
selects CMake 4.4.2 instead of 3.31.12, a Serial DAG contains MPI, or an MPI DAG
does not use the provider selected for its compiler surface. It also checks the
approved NetCDF-C/NetCDF-Fortran/NetCDF-CXX4 to HDF5 version chains. For Cray
MPICH, it also requires the concrete DAG to retain the inspected libfabric and
Cray PMI externals.

## Environment set

The initializer renders eight independent environments:

1. GCC bootstrap;
2. shared GCC Core;
3. GCC Common;
4. GCC Serial;
5. GCC MPI;
6. platform-compiler Common;
7. platform-compiler Serial;
8. platform-compiler MPI.

GPU work is outside the Initial Conversion Trials and is not rendered.
