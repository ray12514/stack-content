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
Every GCC 12.5.0 producer explicitly enables `+binutils`. Downstream groups do
not repeat `%gcc@12.5.0` as a legacy compiler constraint. They order and expose
the producer through `needs: [compiler]` and select the managed compiler through
the conditional `%cse_shared` toolchain. Shared C/C++/Fortran preferences remain
defaults, not enforcement. The workspace-input verifier rejects an incomplete
producer, a missing toolchain selector, a missing `needs` relationship, or an
incomplete language-provider preference before concretization or installation.
New managed-GCC locks are resolved with concrete-spec reuse disabled; platform
lanes retain their existing reuse policy. Identical resulting hashes are still
reused by the shared store and build cache during installation.
An older `gcc@12.5.0~binutils` prefix may remain in the restricted trial store,
but it is ineligible for every newly rendered GCC root and is not part of an
approved lock set. The lock verifier also requires every downstream GCC-surface
root to use the exact same concrete hash as the single
`gcc@12.5.0+binutils` producer. Release publication follows the verified locks,
views, modules, and build-cache entries; it does not publish an unreachable
older compiler merely because that prefix still exists in the trial store.

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
environment. Ninja's unconditional build-only Python edge and Dakota's Python
edge are pinned to 3.12.13. The verifier rejects any additional Python version
and requires the repeated 3.12.13 producer to keep one hash per compiler
surface.

The pinned Boost recipe does not enable its usual compiled libraries for a
bare root. Common package policy enables the recipe's standard compiled
library set for both public Boost versions. Dakota is also bound to the
approved Python 3.12.13, netlib-lapack 3.12.1, Boost 1.90 MPI, CMake 3.31.12,
and lane MPI producers so it cannot silently create parallel producer DAGs.

The restricted trial workspace is collaborative. Generated package policy uses
the installer-recorded CSE collaboration group (`cse` for the current trials)
with group read and write access. The setup requires this group explicitly; it
does not infer a default. The surrounding workspace, caches, build cache, views,
modules, evidence, and release roots must use setgid group-writable directories
or an equivalent default ACL. Publication values use `read: world` and
`write: group`. CSE package managers retain write access, while users outside
the CSE group receive read/search/execute access without write access. The
final publication modes are `2775` for directories, `0775` for executable
files, and `0664` for ordinary files. The leading `2` is setgid, not sticky;
it causes new entries to inherit the CSE group. The private build cache remains
below the restricted root.

For external Cray MPICH, the compiler scope and MPI scope intentionally carry
different version semantics. The compiler scope names the exact selected
compiler. The MPI scope names the physical product-tree flavor baseline, such
as `gcc-12.3` or `cce-20.0`. The helper accepts that scope only when the selected
compiler is from the same family and is at or above the baseline.

The helper records two reviewed execution contexts from the catalog manifest.
The generated provider-selection file starts with `CSE_LOGIN_NODE_TYPE=login`
and `CSE_COMPUTE_NODE_TYPE=cpu_compute`; the operator must verify or replace
both values with exact keys from `profile_facts.node_types`. The values helper
requires both selections and does not silently choose another node type. For
each context it drops candidates that were unwritable,
empty, or on a known `noexec` mount and adds a separate `${WORKDIR}` fallback.
The generated `cse-build` command then tests candidates by executing a small
probe before Spack starts. This catches site execution policy that is not
visible in the reported mount options.

Use `./cse-build login` for the connected login-node session and
`./cse-build compute` from the compute allocation. Each command creates or
reattaches a context-specific tmux session. Direct actions may name the context
as well: `./cse-build login concretize`, `./cse-build login fetch`, and
`./cse-build compute install`. Commands launched inside a prepared session
inherit its context.

The two contexts use the same environments, lockfiles, install tree, shared
source cache, builder-partitioned misc/concretization cache and bootstrap
store, views, modules, and portable CPU target. Only the build stage and
per-context mutable command cache differ. Each misc-cache partition lives
under the shared restricted cache root. The generated entry/exit hook restores
and verifies the owner/group permission contract across the workspace,
source/misc caches, views, modules, and file-backed build cache because tools
can create artifacts with user-only modes. Separate builder partitions prevent
two users from concurrently replacing one mutable index. Installed prefixes
remain governed by Spack package permissions; the bootstrap store remains
private. This lets a login-node concretization prepare Clingo once for
later compute-node use. Each stage is namespaced by the current Spack user,
system, trial release, and context. The generated setup requires an absolute
writable `WORKDIR` and fails if no executable stage is available.

On a builder's first concretization, Spack may install Clingo support and helper
packages such as re2c, gmake, CMake, Python venv, and GCC runtime below that
builder's bootstrap store. That is Spack preparing its concretizer. It is not
the CSE Core or `core-independent` group, does not install the trial package
roster, and is not a separate CSE bootstrap environment. The same builder and
approved Spack identity normally reuse it for the remaining environments.

Before this workspace exists, the operator resumes work through a separate
operator-local session entry point. Run `scripts/create-operator-session.py`
once for an exact system/catalog/trial tuple and pass the installer-confirmed
Unix collaboration group with `--group`; then source the generated
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
environment uses relative includes. The exact reviewed facts are available at
`catalog/profile.yaml`. Restricted build workspaces are created with group
read/write/search access: directories `2770`, ordinary files `0660`, and
executable entry points `0770`. The setgid parent supplies the recorded
collaboration-group ownership.
Hand the entire initialized workspace and its reviewed lockfiles to the builder.

## Builder-selected user module entrance

To update Stack Composer while finishing an existing build, use
[Stack Composer update during the current trial](STACK-COMPOSER-UPDATE.md).
It covers rebuilding only Composer, comparing a temporary candidate, and
testing an optional native executable without refreshing the active workspace.

The release builder/operator chooses the trial's public compiler front-door
suffixes in the reviewed provider selections before creating the build-values
file. `CSE_SHARED_COMPILER_PUBLIC_NAME` and
`CSE_PLATFORM_COMPILER_PUBLIC_NAME` produce `cse/<public-name>` modules; the
current Blueback and Fran selections are `cse/init-GCC` and `cse/init-CCE`.
Those names are release presentation policy, not values inferred from the
login shell, default `PrgEnv-*`, or compiler executable. Once published, a user
enters one compiler surface and one lane:

```sh
module load cse/init-GCC   # or the release's recorded platform front door
module load Serial        # or MPI
module load <package>/<version>
```

The `init-` prefix is a trial convention. The full Stack Composer renderer's
canonical form is `cse/<Compiler>` followed by the same short lane selector.
The compiler front door activates the reviewed compiler-module chain. Lane
selection is separate. A CSE-built MPI lane adds its provider-module root and
loads the exact generated MPI provider module. A platform Cray MPI lane does
not replace the site programming environment; it requires the exact reviewed
Cray MPI module to already be active, then exposes that lane's package-module
root. The front door and lane record the resolved commands in `CSE_CC`,
`CSE_CXX`, `CSE_FC`, `CSE_MPICC`, `CSE_MPICXX`, and `CSE_MPIFC`. This
consumption entrance is separate from the clean build environment established
by `cse-build`.

For CSE-built GCC with external Cray MPICH, the completed locked package builds
establish that the selected headers, link inputs, and runtime closure work for
the Spack build plane. The generated workspace `MPI` selector makes the same
exact-prefix wrapper interface available for ordinary validation. It prepends
the selected Cray MPICH `bin` directory and reviewed runtime paths, binds
`MPICH_CC`, `MPICH_CXX`, and the Fortran overrides to the compiler already
activated by `cse/<public-name>`, and exposes `mpicc`, `mpicxx`, `mpifort`,
`mpif90`, and `mpif77`. It does not load a compiler-selecting `PrgEnv-*`, load
the platform Cray MPICH module chain, or replace `CC`, `CXX`, or `FC`.

The values helper derives this consumer interface from the selected static
catalog scope and records it in
`presentation/mpi-consumer-candidates.yaml`. The record is presentation data
only. It is not referenced by a `spack.yaml`, package roster, package overlay,
or toolchain constraint. The selector deliberately does not declare a launcher.
The approved `srun` MPI plugin or Cray site launcher remains a live system fact.

After all package installs and module refreshes are complete, copy the
presentation layer into the module root recorded by the current values with:

```bash
./cse-build login publish-modules
```

For restricted trial values, this is a restricted CSE team-review checkpoint,
not public promotion. The command does not publish the static catalog, create a
publication workspace, change filesystem audience, run `spack module refresh`,
or delete or replace a package module tree. It copies the two
`cse/<public-name>` front doors and only the ready lane selectors. A
CSE-GCC/external-Cray-MPICH selector marked
`multi-node-validation-required` remains available from the workspace
`modulefiles/` tree but is withheld from the release module root. Publish it
only after a native multi-node launch succeeds through the site's approved
Slurm or Cray launch path. There is no bypass flag.

The in-place workspace control refresh also replaces the workspace's generated
`modulefiles/` and `presentation/` control trees. Those trees are separate from
`values.paths.modules_root`, where Spack writes the package modulefiles, so the
refresh continues to preserve every environment YAML, lockfile, view, cache,
installed prefix, and generated package module. Rerun
`scripts/create-build-values.py` from the reviewed operator session immediately
before this refresh. Current values include the exact compiler and MPI command
metadata required by the presentation modules; refreshing with an older values
file fails validation instead of guessing those commands.

The `cse-build` entry point first appears inside that initialized workspace.
Use the operator session through profile/catalog/value preparation, then use
`<workspace>/cse-build` for concretize, fetch, install, verify, and builder
handoff. It is executable Bash and can be run directly from a default `tcsh`
login; it must not be sourced. The two scripts do not overlap in ownership.
Before Spack starts, `cse-build` removes any ambient Cray `PrgEnv-*` module and
clears `PE_ENV`. The reviewed external compiler module chain then establishes
the correct programming environment when Spack activates that compiler. This
prevents a login-node default such as `PE_ENV=CRAY` from making a GCC build
select CCE-only compiler flags.

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
detects whether zero, some, or all lockfiles already exist. `login` and
`compute` create or reattach separate context-specific tmux sessions; `shell`
bypasses tmux, and the default falls back to a direct shell when tmux is
unavailable.
Its `concretize`
action creates only missing locks; its `install` action verifies all locks and
continues with `spack install --only-concrete`. Already installed hashes are
reused from the shared restricted store. The default `install` action remains
sequential. After all locks pass verification and the real shared install tree
passes the cross-node prefix-lock test, one builder may split the work across
two nodes with `install --surface shared` for GCC and
`install --surface platform` for the selected platform compiler. Do not run
both commands for the same surface, and do not let the per-process job budgets
oversubscribe one node. The two processes receive separate
node-context/surface-scoped `SPACK_USER_CACHE_PATH` directories while retaining
the same locked package store and shared source cache. Each process uses the
same CSE-group-accessible `SPACK_MISC_CACHE_PATH` partition for its builder.

The selected package-build CMake is 3.31.12. CMake 4.4.2 is the second public
version. The workspace overlay recipe adds those two versions to the pinned
`spack-packages` generation.

The same workspace package repository carries reviewed trial source fixes.
Its HDF5 overlay applies `parallel-fortran-module-dir.patch` only to
`hdf5@2.1.0+mpi+fortran+hl`, adding CMake's separately discovered MPI Fortran
module directory to the static and shared high-level Fortran targets. The
workspace verifier rejects a missing, stale, or broadened overlay before
concretization or installation.

Start with the [offline package fix quickstart](templates/PACKAGE-OVERLAY-QUICKSTART.md)
to locate the pinned original recipe and deployed overlay, retry one package
with direct Spack commands, and transfer its files to another workspace without
Git. The guide is copied into generated workspaces for offline use; an existing
workspace can receive this Markdown file directly.

Use [CSE trial package overlay workflow](PACKAGE-OVERLAY-WORKFLOW.md) to
diagnose a new package failure, develop and validate a correction inside an
existing workspace, reconcretize affected unaccepted locks, and return the
approved overlay to canonical Stack Content. The procedure also contains the
task contract for an on-system agent.

After all eight environments concretize, run:

```sh
./cse-build login verify
```

The verifier checks repeated producer hashes, compiler-provider bindings,
CMake selection, Serial/MPI separation, MPI provider selection, and the
approved NetCDF/HDF5 version chains.
