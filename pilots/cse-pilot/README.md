# CSE Initial Conversion Trials workspace

This blueprint combines one reviewed `render-static` catalog with the approved
CPU-only trial package roster. It renders Core, Common, Serial, and MPI
environments for the CSE GCC 12.5 surface and the selected platform-compiler
surface. GPU work is out of scope.

Each environment is self-contained. A GCC environment contains a `compiler`
group followed by Foundation, Core/build-tool, MPI-provider when needed, and
payload groups connected with Spack 1.2 `needs`. An external-compiler
environment starts at Foundation. Nothing registers a built GCC view as an
external compiler.

The same GCC producer spec is repeated in all four GCC environments. Identical
configuration produces one GCC hash. The shared Spack store reuses that hash;
on filesystems with working prefix locks, concurrent installs wait for the
same prefix instead of rebuilding it. Run the generated lockfile verifier
before installation and run the lock smoke test on the real shared filesystem
before starting concurrent Spack processes. Sequential Core, Common, Serial,
then MPI installation is the default trial sequence.

GCC still needs an already available compiler to build GCC itself. The values
helper selects the newest verified older GCC scope from the static catalog and
records it under `shared.compiler.build_with`. This is a direct compiler
dependency in each GCC environment, not a separate preparatory environment.

The initializer does not probe the machine. `scripts/create-build-values.py`
resolves reviewed provider selections against the static catalog. For a
build-sourced OpenMPI it requires verified development externals in the common
scope and emits explicit variants:

- verified UCX with thread-multiple support, or verified libfabric/OFI, never
  `fabrics=auto`;
- `schedulers=slurm` or `schedulers=tm` for PBS;
- Lustre and ROMIO only when the Lustre development external was verified;
- PMI only when `CSE_OPENMPI_PMI=enabled` was explicitly reviewed.

The helper automatically selects UCX when the static common scope contains a
`ucx+thread_multiple` external; otherwise it selects verified libfabric/OFI.
It selects the scheduler when exactly one of `slurm` or `pbs` is present. Use
`CSE_OPENMPI_FABRICS` or `CSE_OPENMPI_SCHEDULER` only to resolve a reviewed
ambiguity; the selected dependency must still exist in the catalog.

The operator selects one reviewed build node type with
`CSE_BUILD_NODE_TYPE`. The helper reads that node type's inspected stage facts
from the catalog manifest, drops candidates that were unwritable, empty, or on
a known `noexec` mount, and emits a complete ordered Spack fallback list:

1. writable temporary or node-local storage;
2. other writable inspected scratch paths;
3. `${WORKDIR}` as the final fallback.

Each inspected path is namespaced by the current Spack user, system, and trial
release. The generated setup script requires the builder's `WORKDIR` to be an
absolute writable directory. This keeps the workspace portable between CSE
builders while preventing an unset variable from becoming an unintended
relative stage path.

```sh
stack-composer init-workspace \
  --blueprint stack-content/pilots/cse-pilot \
  --catalog rendered-static/<system>/static/<catalog-release> \
  --values systems/<system>/cse-trials-build-values.yaml \
  --output restricted/workspaces/<system>/initial-conversion-trials/<release>
```

`init-workspace` snapshots the catalog under `catalog/`; every generated
environment uses relative includes. Hand the entire initialized workspace and
its reviewed lockfiles to the builder.

The selected package-build CMake is 3.31.12. CMake 4.4.2 is the second public
version. The workspace overlay recipe adds those two versions to the pinned
`spack-packages` generation.

After all eight environments concretize, run:

```sh
python3 scripts/verify-lockfiles.py
```

The verifier checks repeated producer hashes, compiler-provider bindings,
CMake selection, Serial/MPI separation, MPI provider selection, and the
approved NetCDF/HDF5 version chains.
