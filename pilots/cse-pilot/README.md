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

An LLVM-based Intel oneAPI surface also includes that verified GCC scope as a
runtime-support provider. Spack's `intel-oneapi-runtime` depends on
`gcc-runtime`; registering the GCC external satisfies that dependency without
changing the selected compiler for Foundation, Core, Serial, MPI, or payload
roots. Classic Intel, AOCC, and CCE surfaces do not receive this extra scope.

The initializer does not probe the machine. `scripts/create-build-values.py`
resolves reviewed provider selections against the static catalog and the
tracked `openmpi-policy.yaml`. For the initial non-Cray builds that policy is:

- Open MPI 4.1.8 with UCX and verified thread-multiple support;
- at most one verified site scheduler, rendered as `schedulers=slurm` or
  `schedulers=tm` for PBS; when neither is present, `schedulers=none +rsh`
  retains ordinary `mpirun`/`mpiexec` launch without a scheduler dependency;
- both `mpirun` and direct `srun --mpi=pmi2` on Slurm, but only when the static
  manifest records both the advertised `pmi2` plugin and its development
  interface;
- legacy launchers on Slurm, with `+pmi` when that PMI2 path is verified and
  `~pmi` otherwise; CUDA and Lustre disabled; and
- ROMIO enabled without a Lustre filesystem plugin.

The generated Open MPI root includes an exact dependency constraint for the
selected UCX version and, when selected, the scheduler version from the common
catalog scope. A detected
Lustre filesystem or Lustre development external remains a useful system fact;
it does not enable Open MPI Lustre integration. When Slurm is selected, missing
Slurm launch capability facts fail values generation with instructions to
re-probe and re-render. A capability record without a verified PMI2 development
path produces an mpirun-only root instead of guessing. The helper never runs
`srun` itself.

The helper resolves one portable CPU target for the whole system from the CPU
facts of every cataloged build/runtime node. A node remains part of this
intersection when it also has a GPU; GPU packages are out of scope, but that
does not invalidate the node's CPU architecture. The helper selects the
highest common standard target in this order: `x86_64_v3`, `x86_64_v2`,
`x86_64`. It never selects `x86_64_v4`, a vendor microarchitecture, or the
native build-node target for these trials. Set `CSE_CPU_TARGET` only to choose
a lower reviewed target; the helper rejects a target that any relevant node
cannot run.
The initialized manifests place that target on every source-built root group
and make it the default preference for dependencies. Platform externals keep
their inspected architecture; the workspace does not require an external MPI
provider to claim the source-build target. Architecture-specific prebuilt
distributions are explicit exceptions: Miniforge uses the generic `x86_64`
family target instead of an `x86_64_v2` or `x86_64_v3` microarchitecture. The
generated lock verifier enforces target policy on built nodes.

The approved Core roster includes Python 3.8.20, 3.10.20, and 3.12.13.
Python 3.8.20 is marked deprecated in the pinned package recipe because that
release line is end-of-life. The generated `config.yaml` deliberately enables
deprecated versions so this explicit trial root can concretize; the lock
verifier requires all three approved Python roots in each compiler's Core
environment.

The restricted trial workspace is collaborative. Generated package policy uses
group `cse` with group read and write access. The surrounding workspace,
caches, build cache, views, modules, evidence, and release roots must use
setgid group-writable directories or an equivalent default ACL. Publication
values use `read: world` and `write: user`; after promotion, consumer-facing
directories and executables are readable/searchable/executable by users and
ordinary files are readable, while group and other write access is disabled.
The private build cache remains below the restricted root.

For external Cray MPICH, the compiler scope and MPI scope intentionally carry
different version semantics. The compiler scope names the exact selected
compiler. The MPI scope names the physical product-tree flavor baseline, such
as `gcc-12.3` or `cce-20.0`. The helper accepts that scope only when the selected
compiler is from the same family and is at or above the baseline.

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

Before this workspace exists, the operator resumes work through a separate
operator-local session entry point. Run `scripts/create-operator-session.py`
once for an exact system/catalog/trial tuple, then source the generated
`$HOME/STACK_TESTING/operator-sessions/<system>/<trial>/activate.sh` after each
login. It restores repository, profile, catalog, workspace, release, cache,
Spack, and Python paths and loads the reviewed provider selections saved beside
it. It does not pull repositories, rebuild tools, probe, render, or initialize
a workspace. That session belongs to the operator-controlled preparation
phase; it is not copied into the shared handoff.

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

The `cse-build` entry point first appears inside that initialized workspace.
Use the operator session through profile/catalog/value preparation, then use
`<workspace>/cse-build` for concretize, fetch, install, verify, and builder
handoff. The two scripts do not overlap in ownership.

The complete workspace is also the builder-resume boundary. It records the
approved Spack source, version, tag, and commit and contains the selected
catalog scopes, environment files, deployment configuration, and lockfiles.
The receiving builder may use either a shared CSE Spack checkout or an
identity-equivalent checkout under that builder's home directory. A different
checkout path does not require reconcretization when its verified runtime
identity is unchanged.

After the workspace and locks exist, the receiving builder does not need
Cluster Inspector, Stack Composer, this content repository, or the original
static catalog. The generated `./cse-build` entry point selects or provisions
the approved shared or builder-local Spack checkout, creates private per-user
Spack state, restores the environment list and deployment configuration, and
detects whether zero, some, or all lockfiles already exist. With no action it
creates or reattaches a tmux session for the system and release; `shell` bypasses
tmux, and the default falls back to a direct shell when tmux is unavailable.
Its `concretize`
action creates only missing locks; its `install` action verifies all locks and
continues with `spack install --only-concrete`. Already installed hashes are
reused from the shared restricted store. The default `install` action remains
sequential. After all locks pass verification and the real shared install tree
passes the cross-node prefix-lock test, one builder may split the work across
two nodes with `install --surface shared` for GCC and
`install --surface platform` for the selected platform compiler. Do not run
both commands for the same surface, and do not let the per-process job budgets
oversubscribe one node. The two processes receive separate surface-scoped
`SPACK_USER_CACHE_PATH` directories while retaining the same locked package
store and generated source/misc caches.

The selected package-build CMake is 3.31.12. CMake 4.4.2 is the second public
version. The workspace overlay recipe adds those two versions to the pinned
`spack-packages` generation.

After all eight environments concretize, run:

```sh
./cse-build verify
```

The verifier checks repeated producer hashes, compiler-provider bindings,
CMake selection, Serial/MPI separation, MPI provider selection, and the
approved NetCDF/HDF5 version chains.
