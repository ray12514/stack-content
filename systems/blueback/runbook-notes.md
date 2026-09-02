# Blueback system notes

Use `stack-planning/docs/runbook.md` for every command and common promotion
gate. This file records only Blueback-specific facts, choices, and findings.

## System identity

- Platform: HPE Cray EX / Cray Programming Environment.
- Scheduler: Slurm.
- Fabric: Slingshot/CXI.
- Accelerator facts: AMD MI300A APU with `gfx942` is expected in the profile,
  but GPU builds are outside the Initial Conversion Trials.
- Provider shape: one coherent CPE release must supply each selected compiler,
  matching Cray MPICH flavor, and required platform module chain.

## Current trial posture

- Build the shared GCC 12.5.0 producer, Foundation, Core, and build tools with
  GCC.
- Select the exact external CCE compiler from the static catalog for the
  platform surface. Do not infer it from Blueback's default module state.
- Pair the GCC surface with the GNU-compatible Cray MPICH 9.x scope and the CCE
  surface with the CCE-compatible Cray MPICH 9.x scope from the same CPE.
- Select exact versions from the live profile and current catalog. Blueback
  carries multiple CPE releases, and its default has changed before.
- Keep Foundation/Core/Common/Serial/MPI package intent in the CSE trial roster.
  Do not add Blueback package policy to `render-static`.

## Provisional module snapshot (2026-08-12)

This snapshot guides the first profile review; the live Cluster Inspector
profile remains authoritative.

- `PrgEnv-cray/8.7.0`
- `cce/21.0.0`
- `cray-mpich/9.1.0`
- `libfabric/2.3.1`
- CCE Cray MPICH flavor observed at
  `/opt/cray/pe/mpich/9.1.0/ofi/cray/20.0`
- GNU Cray MPICH flavor observed at
  `/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3`

The flavor directories are compatibility baselines, not replacement compiler
versions. Confirm that the live profile pairs CCE 21.0.0 and the CSE GCC 12.5.0
surface with those real supported prefixes.

Keep the complete observed Cray MPICH flavor map in the profile. A flavor does
not have to name an installed `compiler_provider`: the suffix is a same-family
minimum baseline. In particular, CSE-built GCC 12.5.0 may consume the
`ofi/gnu/12.3` flavor, while a GCC version below 12.3 may not. The loaded or
default PrgEnv is review evidence only and does not narrow the supported map.

## Profile and catalog review additions

In addition to the common runbook checks:

- use the committed `inspector-hints.yaml` when probing system facts; its MPI
  exclusion removes Cray MPICH ABI compatibility modules from native Cray
  MPICH activation chains without changing generic provider discovery;
- confirm the selected CPE is the intended current release;
- confirm the compiler provider includes the complete program-environment and
  compiler module chain plus the exact prefix;
- confirm the selected Cray MPICH record has the matching compiler flavor and
  real flavor prefix;
- confirm fabric/runtime externals refer to the active CXI/Cray PE stack;
- confirm `libfabric` is present in the common static scope and `cray-pmi` is
  present in each Cray MPICH scope;
- reject cross-CPE compiler/MPI combinations even when every individual module
  exists.

### Cray MPICH ABI-module exclusion

Blueback's committed `inspector-hints.yaml` excludes
`cray-mpich-abi*`. Cluster Inspector applies this MPI category exclusion to
discovered provider candidates and to every module recorded in the native Cray
MPICH activation chain. Do not add a Blueback name, CPE release, or Cray MPICH
version to Cluster Inspector for this rule.
For another Cray system, place the same pattern in that system's own hints file
after its module inventory confirms the same ABI compatibility siblings; do
not turn the Blueback decision into a global default.

After changing the hint or updating the relevant Cluster Inspector behavior,
synchronize both repositories and rebuild the inspector:

```bash
git -C "$INSPECTOR" pull --ff-only
git -C "$CONTENT" pull --ff-only

source "$CSE_OPERATOR_SESSION_FILE"
cse_rebuild_tools inspector
```

Compiler, MPI, fabric, and module inventory are system facts. Rerun only the
system probe with the committed hint; retain the existing reviewed node
fragments:

```bash
"$INSPECTOR/cluster-inspector" probe-system \
  --system "$SYSTEM_NAME" \
  --hints "$CONTENT/systems/blueback/inspector-hints.yaml" \
  --record "$PROBE_DIR/system-probe-transcript.yaml" \
  --output "$PROBE_DIR/system.frag.yaml"

if grep -n 'cray-mpich-abi' "$PROBE_DIR/system.frag.yaml"; then
  echo "unexpected Cray MPICH ABI module in Blueback system facts" >&2
  return 2 2>/dev/null || exit 2
fi
```

Merge the regenerated system fragment with the existing Blueback node
fragments, then verify the complete profile:

```bash
"$INSPECTOR/cluster-inspector" merge \
  --system-fragment "$PROBE_DIR/system.frag.yaml" \
  --node "$PROBE_DIR/login.frag.yaml" \
  --node "$PROBE_DIR/compute.frag.yaml" \
  --node "$PROBE_DIR/apu.frag.yaml" \
  --output "$PROBE_DIR/profile.yaml"

"$INSPECTOR/cluster-inspector" verify "$PROBE_DIR/profile.yaml"

if grep -n 'cray-mpich-abi' "$PROBE_DIR/profile.yaml"; then
  echo "unexpected Cray MPICH ABI module in Blueback profile" >&2
  return 2 2>/dev/null || exit 2
fi
```

Do not rerun `probe-node` solely for this hint change. A static catalog or
restricted workspace rendered from the previous profile is stale. Before any
installation, regenerate it through the common runbook's overwrite path. If
installation has started, preserve that release and create a new one.

## Restricted build and cache gates

### Refresh `cse-build` without replacing the workspace

Use this shortcut when Blueback already has a valid initialized workspace and
lockfiles, but Stack Content changed `cse-build` or one of its generated helper
files. It does not rerender the static catalog, replace environment YAML,
reconcretize, clear caches, or touch installed packages.

Stop active `cse-build` processes first. From the existing operator session,
synchronize only the two inputs used by this refresh and rebuild Stack Composer
when its checkout changed:

```bash
source "$CSE_OPERATOR_SESSION_FILE"

for repo in stack-composer stack-content; do
  git -C "$WORK_ROOT/$repo" status --short --branch
done
# Stop here if either checkout contains unreviewed work.

for repo in stack-composer stack-content; do
  git -C "$WORK_ROOT/$repo" pull --ff-only
done

source "$CSE_OPERATOR_SESSION_FILE"
cse_rebuild_tools composer
```

Refresh the declared control set in place, then run the read-only status and
lock verification checks:

```bash
"$CSE_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/create-build-values.py"

"$CSE_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --composer "$STACK_COMPOSER" \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --values "$BUILD_VALUES" \
  --workspace "$BUILD_WORKSPACE"

cd "$BUILD_WORKSPACE"
./cse-build login status
./cse-build login verify
```

The refresh renders a disposable workspace, confirms the blueprint, Blueback
system, and catalog release match, and atomically replaces only `cse-build`,
the common config, its environment helpers, the lock verifier, and the builder
handoff note, plus the generated workspace `modulefiles/` and `presentation/`
control trees. Those workspace trees do not contain Spack's release package
modules. A mismatch stops without changing the existing controls. If
environment inputs or package overlays changed, use the common runbook's
appropriate workspace or release recovery instead of this shortcut.

The same shared control set is used on every trial system. For Blueback it
places the builder's misc/provider and concretization indexes below
`$CSE_RESTRICTED_ROOT/cache/misc/$USER`. Before and after Spack it restores and
verifies the CSE group, group read/write access, directory search/setgid access,
and no-world-access policy across the workspace, source/misc caches, views,
modules, and file-backed build cache. The source cache remains shared without a
builder suffix; installed prefixes remain governed by Spack package permissions.

### Blueback shared generated-content recovery

Use this complete Blueback procedure when the existing workspace predates the
common generated-permission helper, a second builder receives
`PermissionError`, or the accidental recursive `chmod 660` removed directory
traversal below the misc cache. No other runbook section is required for this
Blueback recovery.

The permanent refreshed control is not limited to Blueback's misc cache. It
enforces the common owner/`cse` group contract for the workspace and lockfiles,
source cache, builder misc partitions, views, modules, file-backed build cache,
and Spack-created install prefixes through the rendered package-permission
policy. Only the emergency commands below are misc-specific because that is the
tree that was manually changed.

First stop every process using the Blueback workspace or misc cache. Then
restore traversal and owner/`cse` parity on the exact misc-cache tree that was
changed. The ownership filters are deliberate: a builder repairs that builder's
entries; another owner or a filesystem administrator repairs entries owned by
someone else.

```bash
source "$CSE_OPERATOR_SESSION_FILE"

test "$SYSTEM_NAME" = "blueback"
test "$CSE_GROUP" = "cse"
export BROKEN_ROOT="$CSE_RESTRICTED_ROOT/cache/misc"
test -d "$BROKEN_ROOT"

# Restore traversal in preorder so find can descend into nested 0660 dirs.
chmod 0770 "$BROKEN_ROOT"
find "$BROKEN_ROOT" -xdev -user "$USER" -type d \
  -exec chmod 0770 {} \;

find "$BROKEN_ROOT" -xdev -user "$USER" -type d \
  -exec chgrp "$CSE_GROUP" {} +
find "$BROKEN_ROOT" -xdev -user "$USER" -type f \
  -exec chgrp "$CSE_GROUP" {} +
find "$BROKEN_ROOT" -xdev -user "$USER" -type d \
  -exec chmod 2770 {} +
find "$BROKEN_ROOT" -xdev -user "$USER" -type f -perm -0100 \
  -exec chmod 0770 {} +
find "$BROKEN_ROOT" -xdev -user "$USER" -type f ! -perm -0100 \
  -exec chmod 0660 {} +
```

Synchronize Stack Content and replace the generated controls in the existing
Blueback workspace. Pulling the repository alone does not update that already
rendered workspace:

```bash
git -C "$CONTENT" status --short --branch
# Stop here if the checkout contains unreviewed work.
git -C "$CONTENT" pull --ff-only origin codex/simplified-render-plan

"$CSE_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/create-build-values.py"

"$CSE_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --composer "$STACK_COMPOSER" \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --values "$BUILD_VALUES" \
  --workspace "$BUILD_WORKSPACE"

grep -F 'misc_cache: ${SPACK_MISC_CACHE_PATH}' \
  "$BUILD_WORKSPACE/configs/common/config.yaml"

cd "$BUILD_WORKSPACE"
./cse-build login status
./cse-build login verify
```

The originating builder exits the prepared shell and reruns `./cse-build login
status`. The second Blueback builder then sources that builder's own operator
session, enters the same workspace, and runs the same status command. A clean
status from both accounts is the handoff gate. Each account uses its own
`cache/misc/$USER` partition while sharing the workspace, source cache, install
tree, views, modules, and file-backed build cache.

Do not point `BROKEN_ROOT` at the restricted trial root, release root, or Spack
install tree, and do not recursively apply `660` to a directory tree. After the
one-time traversal repair and controls refresh, every builder must enter through
the refreshed `cse-build`; it normalizes that builder's generated content on
entry and exit and verifies the complete handoff surfaces with `status`.

Use this reviewed Step 7 selection:

```bash
export CSE_SHARED_COMPILER_REF="gcc@12.5.0"
export CSE_SHARED_COMPILER_PUBLIC_NAME="init-GCC"
export CSE_SHARED_MPI_REF="cray-mpich@9.1.0"
export CSE_SHARED_MPI_SOURCE="external"
export CSE_PLATFORM_COMPILER_REF="cce@21.0.0"
export CSE_PLATFORM_COMPILER_PUBLIC_NAME="init-CCE"
export CSE_PLATFORM_MPI_REF="cray-mpich@9.1.0"
export CSE_PLATFORM_MPI_SOURCE="external"
export CSE_LOGIN_NODE_TYPE="login"
export CSE_COMPUTE_NODE_TYPE="cpu_compute"
export BUILD_JOBS="<approved-job-count>"
```

These are the only required Blueback-specific Step 7 selections. The helper
normally selects the newest verified installed GCC older than 12.5.0 as the
compiler used to build GCC 12.5.0. If catalog review requires another installed
compiler, set `CSE_SHARED_COMPILER_SEED_REF="<provider>@<version>"` explicitly.
This seed compiler is separate from the Cray MPICH flavor selection.

The values above assume the standard profile keys `login` and `cpu_compute`.
Replace either value when the Blueback catalog uses a different exact key. The
helper records both contexts. `./cse-build login`
selects the reviewed login candidates and `./cse-build compute` selects the
reviewed compute candidates; both retain a context-specific `${WORKDIR}`
fallback.

For MPI, the helper must select the GNU baseline scope for the CSE GCC surface
and the CCE baseline scope for the CCE surface. For the provisional snapshot
those physical MPI flavor paths end in `gcc-12.3` and `cce-20.0`, respectively.
They remain baseline identities even when the catalog also observes newer GCC
or CCE compilers. You do not type either scope path. You provide
`cray-mpich@9.1.0` for both MPI refs; the helper selects the compatible catalog
scope and fails rather than substituting one surface's Cray MPICH prefix for
the other.

- Cray MPICH remains a non-buildable external at its live prefix.
- Do not manually preload `PrgEnv-gnu`, `PrgEnv-cray`, `gcc`, `cce`, or
  `cray-mpich` before entering through `cse-build`. The generated external
  package records own the exact module chains. If a prepared shell inherited a
  conflicting `PrgEnv-*` module or `PE_ENV` compiler-family marker, use the
  targeted recovery below rather than hand-loading a second toolchain.
- Both Serial environments contain no MPI implementation.
- Each MPI environment uses the Cray MPICH flavor matched to its compiler
  surface.
- Every lane is exercised under the selected CPE modules before its concrete
  specs enter the private CSE build cache.
- The cache contains CSE-built packages only; it does not attempt to package or
  relocate the platform-owned CPE or Cray MPICH installations.

### CCE ncurses 6.6 LLD version-map failure

This recovery applies when ncurses 6.6 with `+termlib` reaches the shared
`libtinfo` link and CCE reports repeated errors of this form:

```text
ld.lld: error: version script assignment of 'NCURSES6_5.0.19991023' to
symbol 'COLORS' failed: symbol not defined
```

The ncurses version map intentionally covers symbols from several library and
configuration combinations. The split `libtinfo` library does not define every
symbol in that map. GNU `ld` permits those absent entries by default, while the
LLVM linker used by current CCE releases rejects them. The trial ncurses
overlay retains symbol versioning and adds `-Wl,--undefined-version` only to
`ncurses@6.6 %cce` links.

Do not export an ad hoc `LDFLAGS` value and retry the old lock. The linker input
must be represented by the package recipe and concrete hash. This recovery is
valid only while the CCE lock set is still an unaccepted release candidate. If
that lock set was already accepted or pushed, create a new release instead.

Exit any prepared compute shell. Pull Stack Content, then enter the workspace's
prepared login shell:

```bash
git -C "$CONTENT" pull --ff-only

cd "$BUILD_WORKSPACE"
./cse-build login shell
```

Inside that shell, copy only the tracked ncurses overlay into the existing
workspace package repository and retain CSE group access:

```bash
: "${CSE_BUILD_WORKSPACE:?Run this block inside ./cse-build login shell}"

NCURSES_SOURCE="$CONTENT/pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/packages/ncurses"
NCURSES_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials/packages/ncurses"

install -d -m 2770 -g "$CSE_GROUP" "$NCURSES_DESTINATION"
install -m 0660 -g "$CSE_GROUP" \
  "$NCURSES_SOURCE/package.py" \
  "$NCURSES_DESTINATION/package.py"
```

Force reconcretization of all four CCE environments so every lock records the
same corrected ncurses recipe. The failed ncurses hash and any dependent hashes
must change; already installed dependencies whose concrete identities are
unchanged remain reusable.

```bash
for environment in core common serial "mpi-$PLATFORM_MPI_NAME"; do
  PLATFORM_ENV="$CSE_BUILD_WORKSPACE/environments/$PLATFORM_COMPILER_NAME/$environment"

  spack -e "$PLATFORM_ENV" repo list
  spack -e "$PLATFORM_ENV" find -cl ncurses
  spack -e "$PLATFORM_ENV" concretize -f --reuse-deps -j 1
  spack -e "$PLATFORM_ENV" find -cl ncurses
done
```

The repository list must place `cse_trials` before `builtin`. Compare the
before and after listings and retain them with the failed-link output. Exit the
prepared login shell, verify all updated locks, then resume only the CCE
surface from the approved compute allocation:

```bash
exit

cd "$BUILD_WORKSPACE"
./cse-build login verify
./cse-build compute install --surface platform
```

The successful link command must contain `--undefined-version`, and the final
`libtinfo.so.6.6` must retain its version definitions. This option permits map
entries that are absent from this library configuration; it does not permit
unresolved object or library references.

### GNU LAPACK reports `-sinteger64`

LAPACK 3.12.1 uses `PE_ENV=CRAY` to select the CCE `-sinteger64` flag for its
ILP64 targets. If the build command shows GNU `gfortran` followed by
`unrecognized command-line option '-sinteger64'`, the GCC surface inherited a
Cray programming-environment marker from the login shell. This is not a LAPACK
version or BLAS-provider error, and it does not require reconcretization.

To resume a failed install, run from its prepared shell:

```bash
unset PE_ENV
./cse-build compute install --surface shared
```

The failed LAPACK prefix is incomplete, so Spack retries it while retaining
the completed Core prefixes and any successful Common dependencies in the
shared store. The workspace-template automation is tracked separately; until
it is released and the workspace is regenerated, repeat this cleanup in each
new prepared shell that inherited the wrong marker.

### GNU FFTW cannot link `MPI_Init` with Cray MPICH

This recovery applies when the GCC MPI environment selects the reviewed
Cray MPICH GNU flavor but FFTW configure reports all of the following:

- `mpicc` resolves to
  `/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3/bin/mpicc`;
- the `MPI_Init`, `-lmpi`, and `-lmpich` link probes fail; and
- configure ends with `could not find mpi library for --enable-mpi`.

This is a difference between the interactive module environment and Spack's
clean package build environment. It is not, by itself, a reason to
reconcretize, edit `spack.yaml`, or replace the Cray MPICH external. The
`cray-mpich` module uses the selected Cray programming-environment family to
establish `CRAY_MPICH_PREFIX`, `CRAY_MPICH_DIR`, `MPICH_DIR`, MPI search paths,
and `CRAY_LD_LIBRARY_PATH`. The accelerator-specific `PE_MPICH_GTL_*` values
are not required for the CPU-only trial lane.

Remain in the prepared `cse-build compute` shell. First inspect the active
selection:

```bash
env |
  grep -E '^(PE_ENV|CRAY_MPICH_(BASEDIR|PREFIX|DIR)|MPICH_DIR|CRAY_LD_LIBRARY_PATH)='
```

If the GNU-specific values are absent or do not select
`9.1.0/ofi/gnu/12.3`, reload only Cray MPICH with the GNU family selector for
an interactive control probe. Do not load the complete `PrgEnv-gnu` module
because it can replace the CSE GCC 12.5 compiler with the site-default
compiler.

```bash
module unload cray-mpich/9.1.0 2>/dev/null || true

export PE_ENV=GNU
module load cray-mpich/9.1.0
unset PE_ENV
```

Verify the exact external wrapper before restarting the environment install:

```bash
MPI_PROBE="$CSE_BUILD_STAGE/.cse-mpi-probe-$$"

printf '#include <mpi.h>\nint main(int argc,char **argv){MPI_Init(&argc,&argv);MPI_Finalize();return 0;}\n' \
  > "$MPI_PROBE.c"

/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3/bin/mpicc \
  "$MPI_PROBE.c" -o "$MPI_PROBE"

"$MPI_PROBE"
probe_status=$?
rm -f "$MPI_PROBE.c" "$MPI_PROBE"
printf 'MPI probe status: %s\n' "$probe_status"
```

The interactive probe is only a control. A zero status proves that the prefix
and native wrapper work in the current shell; it does not prove that Spack's
clean FFTW build environment contains the same compiler and link state. Do not
retry the full install by exporting `PE_ENV=GNU` around `spack install`: that
selector is necessary for the GNU flavor, but Blueback testing showed that it
is not sufficient to make FFTW link `MPI_Init`.

Reproduce the failed link inside the exact locked FFTW build environment. The
following block derives the concrete FFTW hash from its retained stage, prints
only the variables relevant to the compiler/MPI boundary, shows the native
wrapper command, and compiles one MPI program through the same Spack build
environment:

```bash
environment="$SHARED_COMPILER_NAME/mpi-$SHARED_MPI_NAME"
MPI_ENV="$CSE_BUILD_WORKSPACE/environments/$environment"
MPI_CONFIG_LOG="$(
  find "$CSE_BUILD_STAGE" \
    -type f \
    -path '*spack-stage-fftw-3.3.11-*/spack-src/*/config.log' \
    -print |
    tail -1
)"
MPI_STAGE_NAME="$(
  printf '%s\n' "$MPI_CONFIG_LOG" |
    tr '/' '\n' |
    grep -E '^spack-stage-fftw-3[.]3[.]11-[[:alnum:]]+$' |
    tail -1
)"

if [ -z "$MPI_STAGE_NAME" ]; then
  echo "could not derive the failed FFTW stage from: $MPI_CONFIG_LOG" >&2
else
  MPI_HASH="${MPI_STAGE_NAME#spack-stage-fftw-3.3.11-}"
  MPI_BUILD_PROBE="$CSE_BUILD_STAGE/.cse-fftw-mpi-build-probe-$$"

  printf 'FFTW config log: %s\n' "$MPI_CONFIG_LOG"
  printf 'failed FFTW hash: %s\n' "$MPI_HASH"

  module unload cray-mpich/9.1.0 2>/dev/null || true
  export PE_ENV=GNU

  spack -e "$MPI_ENV" build-env "/$MPI_HASH" -- bash -c '
    set -x
    env | grep -E \
      "^(PE_ENV|CRAY_MPICH_(BASEDIR|PREFIX|DIR)|MPICH_DIR|CRAY_LD_LIBRARY_PATH|LD_LIBRARY_PATH|LIBRARY_PATH|CC|SPACK_CC|MPICC|MPICH_CC|MPICH_CXX|MPICH_FC)=" \
      | sort
    command -v mpicc
    "$MPICC" -show 2>/dev/null || "$MPICC" --showme 2>/dev/null || true
    printf "#include <mpi.h>\nint main(int argc,char **argv){MPI_Init(&argc,&argv);MPI_Finalize();return 0;}\n" \
      > "$1.c"
    if "$MPICC" -v "$1.c" -o "$1.spack" && "$1.spack"; then
      spack_bound_status=0
    else
      spack_bound_status=$?
    fi
    printf "Spack-bound MPICH wrapper status: %s\n" "$spack_bound_status"

    unset MPICH_CC MPICH_CXX MPICH_FC MPICH_F77 MPICH_F90
    "$MPICC" -show 2>/dev/null || "$MPICC" --showme 2>/dev/null || true
    if "$MPICC" -v "$1.c" -o "$1.native" && "$1.native"; then
      native_wrapper_status=0
    else
      native_wrapper_status=$?
    fi
    printf "Native MPICH wrapper status: %s\n" "$native_wrapper_status"

    rm -f "$1.c" "$1.spack" "$1.native"
    test "$spack_bound_status" -eq 0
  ' bash "$MPI_BUILD_PROBE"
  build_probe_status=$?

  unset PE_ENV
  rm -f "$MPI_BUILD_PROBE.c" \
    "$MPI_BUILD_PROBE" \
    "$MPI_BUILD_PROBE.spack" \
    "$MPI_BUILD_PROBE.native"
  printf 'Spack FFTW build-environment MPI probe status: %s\n' \
    "$build_probe_status"
fi
```

Preserve the first linker diagnostic from this probe and the matching FFTW
configure excerpt:

```bash
grep -nE -B12 -A35 \
  'checking for mpicc|checking for MPI_Init|cannot find|undefined reference|collect2:|ld:|error:' \
  "$MPI_CONFIG_LOG"
```

Interpret the result before changing policy:

- If `MPICC`, `PE_ENV`, or the `CRAY_MPICH_*` values select the wrong flavor,
  correct generic external-provider activation.
- If the wrapper's shown command selects the wrong underlying compiler,
  correct the compiler-to-MPI toolchain binding; do not add an FFTW override.
- If the native-wrapper control passes but the Spack-bound wrapper fails, the
  failure is specifically in the `MPICH_CC` compiler override used to bind the
  MPI consumer to CSE GCC 12.5. Do not accept the native result as a fix: it
  would silently build the package with the Cray flavor's baseline compiler.
- If the wrapper selects the intended compiler but the linker cannot resolve a
  Cray MPI dependency, compare the printed clean-build library variables with
  the interactive control and carry only the provider-owned link state needed
  by the external.
- If this exact build-environment probe passes while FFTW configure fails, the
  remaining fault is in how the FFTW recipe invokes MPI rather than in the
  external provider activation.

#### Resolved Blueback cause and workspace recovery

The retained Blueback failure reached the fourth case above. The exact Spack
build environment selected GCC 12.5 and
`/opt/cray/pe/mpich/9.1.0/ofi/gnu/12.3`, but the linker reported that
`libfabric.so.1` was not found and then emitted unresolved `FABRIC_1.x`
symbols from `libmpi_gnu.so`.

The permanent renderer fix attaches the selected Cray platform libfabric to
the external Cray MPICH record through Spack's supported external environment
metadata. The libfabric version and prefix come from the inspected profile;
the Blueback result is expected to contain:

```yaml
extra_attributes:
  environment:
    prepend_path:
      LD_LIBRARY_PATH: /opt/cray/libfabric/2.3.1/lib64
```

Do not paste that version into source policy. Verify the value after rerender;
it must track the selected `/opt/cray/libfabric` fact from the current profile.

After pulling the updated Stack Composer and Stack Content branches, rerender
the static catalog and refresh the workspace through the normal runbook steps.
Freshly reconcretize only the affected MPI environment, then retry its install:

```bash
environment="$SHARED_COMPILER_NAME/mpi-$SHARED_MPI_NAME"
MPI_ENV="$CSE_BUILD_WORKSPACE/environments/$environment"

grep -R -nA3 -B4 \
  'LD_LIBRARY_PATH:' \
  "$CSE_BUILD_WORKSPACE/catalog/scopes/mpi/cray-mpich"

spack -e "$MPI_ENV" concretize -f --reuse-deps -j 1
spack -e "$MPI_ENV" install --only-concrete -j "$BUILD_JOBS" --fail-fast
```

The grep must show the profile-selected Cray libfabric path before the retry.
The `-f` option is required because the MPI roots already exist in the lock;
`--fresh` alone changes reuse policy but does not replace an existing concrete
root. `--reuse-deps` retains unchanged dependency hashes while the affected
roots are regenerated.
No rebuild of already completed Core, Common, or Serial packages is required;
their concrete DAGs and installed prefixes did not depend on this external MPI
activation metadata.

Do not add `--dirty`. The permanent fix must work in Spack's normal clean build
environment. Do not encode `PE_ENV=GNU` as a Blueback- or FFTW-specific rule;
the generic Cray provider policy must derive the compiler-family selector and
provider-owned link state from the selected compiler/Cray MPICH pairing.

#### Dakota 6.23/6.24 recovery with Boost 1.90

Dakota 6.23.0 and 6.24.0 still request the compiled Boost.System CMake
component and `Boost::system` target. Boost.System is header-only for every
Boost release those Dakota versions support, and Boost 1.89 removed the
compiled compatibility stub. A failure looking for
`boost_systemConfig.cmake` is therefore a Dakota source-compatibility issue,
not a missing Boost variant or a reason to rebuild Boost.

When package installation has already started, do not overwrite the complete
workspace. Pull Stack Content, copy only the tracked Dakota overlay into the
workspace package repository, and retain group access:

```bash
git -C "$CONTENT" pull --ff-only

DAKOTA_SOURCE="$CONTENT/pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/packages/dakota"
DAKOTA_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials/packages/dakota"

install -d -m 2770 -g "$CSE_GROUP" "$DAKOTA_DESTINATION"
install -m 0660 -g "$CSE_GROUP" \
  "$DAKOTA_SOURCE/package.py" \
  "$DAKOTA_SOURCE/boost-system-header-only.patch" \
  "$DAKOTA_DESTINATION/"
```

Force reconcretization of only the shared MPI environment. The Dakota package
hash must change because the source patch is part of its concrete identity;
the already installed compiler, Foundation, build-tool, Boost, HDF5, NetCDF,
FFTW, and other dependency hashes remain reusable. `--fresh` is not sufficient
for this recovery: it does not replace roots already recorded in `spack.lock`.

```bash
environment="$SHARED_COMPILER_NAME/mpi-$SHARED_MPI_NAME"
MPI_ENV="$CSE_BUILD_WORKSPACE/environments/$environment"

spack -e "$MPI_ENV" repo list
spack -e "$MPI_ENV" find -cl dakota
spack -e "$MPI_ENV" concretize -f --reuse-deps -j 1
spack -e "$MPI_ENV" find -cl dakota

cd "$CSE_BUILD_WORKSPACE"
./cse-build compute verify

spack -e "$MPI_ENV" install --only-concrete \
  -j "$BUILD_JOBS" --fail-fast \
  dakota@6.23.0 dakota@6.24.0
```

The repository list must place `cse_trials` before `builtin`. Compare the two
`find -cl` results: both Dakota hashes must change. If concretization reports
`No new specs to concretize` and retains the old hashes, stop; the patch is not
in the concrete roots. A controlled Spack 1.2.2 replay verified that
`-f --reuse-deps` changes the patched Dakota roots while retaining every
unchanged dependency hash.

The final CMake configure must continue finding the approved Boost 1.90.0
prefix, but it must no longer request `boost_systemConfig.cmake`. Do not create
a fake Boost.System package, change global CMake lookup policy, or remove the
remaining Program Options, Regex, or Serialization components.

If the configure log reports an `MPIEXEC` under an unrelated site MPI such as
`/usr/lib64/mpi/gcc/mvapich2`, record it as a separate launcher-selection
failure. The selected `MPI_CXX_COMPILER` and MPI libraries must still resolve
to the lane's Cray MPICH flavor. An ambient launcher does not explain the
Boost.System failure, but it must not be used for configure run tests or final
MPI validation. Do not filter all of `/usr`, add a Blueback-only source patch,
or assume that the MPI library prefix provides the site launcher. The durable
policy is an explicit launcher command selected from the rendered MPI and
scheduler policy.

### Build-stage execution diagnosis

A Spack build stage must be writable and searchable, have usable space and
inodes, and permit both scripts and newly linked executables to run. The
generated `cse-build` entry point checks the selected node context and chooses
the first approved stage that passes its script execution probe. A normal
`noexec` mount is therefore rejected before Spack starts. The message `C
compiler cannot create executables` does not, by itself, prove that the stage
is mounted `noexec`.

When a build reports that message, remain in the same `cse-build` shell and run
the following checks before changing the workspace or reconcretizing:

```bash
printf 'selected stage: %s\n' "$CSE_BUILD_STAGE"
findmnt -T "$CSE_BUILD_STAGE" -o TARGET,SOURCE,FSTYPE,OPTIONS

STAGE_PROBE="$CSE_BUILD_STAGE/.cse-exec-probe-$$"

printf '#!/bin/sh\nexit 0\n' > "${STAGE_PROBE}.sh"
chmod 0700 "${STAGE_PROBE}.sh"
if "${STAGE_PROBE}.sh"; then
  echo "stage script execution: PASS"
else
  echo "stage script execution: FAIL"
fi

TRUE_PROGRAM="$(type -P true)"
cp "$TRUE_PROGRAM" "${STAGE_PROBE}.bin"
chmod 0700 "${STAGE_PROBE}.bin"
if "${STAGE_PROBE}.bin"; then
  echo "stage binary execution: PASS"
else
  echo "stage binary execution: FAIL"
fi

rm -f "${STAGE_PROBE}.sh" "${STAGE_PROBE}.bin"

CONFIG_LOG="$(
  find "$CSE_BUILD_STAGE" \
    -type f \
    -path '*spack-stage-gmake*' \
    -name config.log \
    -print | tail -1
)"
printf 'gmake config log: %s\n' "$CONFIG_LOG"
grep -nE -B10 -A20 \
  'C compiler cannot create executables|Permission denied|cannot execute|collect2:|ld:|error:' \
  "$CONFIG_LOG"
```

If both stage probes pass, reproduce only the failed compiler check in Spack's
concrete `gmake` build environment. This prints the wrapper, the underlying
compiler selected through `SPACK_CC`, and the modules visible to that exact
build environment. The environment contains several `gmake@4.4.1` dependency
specs, so the probe derives the exact failed DAG hash from `CONFIG_LOG` rather
than selecting by package version:

```bash
GMAKE_ENV="$CSE_BUILD_WORKSPACE/environments/gcc/core"
CC_PROBE="$CSE_BUILD_STAGE/.cse-gmake-compiler-probe-$$"
GMAKE_STAGE_NAME="$(
  printf '%s\n' "$CONFIG_LOG" |
    tr '/' '\n' |
    grep -E '^spack-stage-gmake-4[.]4[.]1-[[:alnum:]]+$' |
    tail -1
)"

if [ -z "$GMAKE_STAGE_NAME" ]; then
  echo "could not derive the failed gmake stage from: $CONFIG_LOG" >&2
else
  GMAKE_HASH="${GMAKE_STAGE_NAME#spack-stage-gmake-4.4.1-}"
  printf 'failed gmake hash: %s\n' "$GMAKE_HASH"

  if spack -e "$GMAKE_ENV" build-env "/$GMAKE_HASH" -- bash -c '
    set -x
    printf "CC=%s\n" "${CC:-<unset>}"
    printf "SPACK_CC=%s\n" "${SPACK_CC:-<unset>}"
    printf "LOADEDMODULES=%s\n" "${LOADEDMODULES:-<unset>}"
    printf "int main(void) { return 0; }\n" > "$1.c"
    "$CC" --version
    "$CC" -v "$1.c" -o "$1"
    "$1"
  ' bash "$CC_PROBE"; then
    echo "gmake compiler environment: PASS"
  else
    echo "gmake compiler environment: FAIL"
  fi
fi

rm -f "$CC_PROBE.c" "$CC_PROBE"
```

Interpret the result as follows:

- If either execution probe fails, stop the build and preserve its log. The
  selected stage is not usable in that Blueback context. Do not edit a
  generated `spack.yaml` or `spack.lock` to work around it.
- If `findmnt` reports `noexec`, the stage selection is wrong and the owning
  node facts or stage-selection logic must be corrected before retrying.
- If both probes pass, the stage is executable. Use the reported `config.log`
  error to diagnose the compiler, linker, runtime, or module environment; do
  not replace the workspace merely because configure printed its generic
  failure message.
- If the `gmake` compiler-environment probe fails, preserve its complete
  output. The `SPACK_CC` value and the compiler's own diagnostic distinguish an
  incomplete external compiler module chain from a bad compiler path, a
  wrapper problem, or a target/linker failure. Do not retry the full install
  until that output identifies which input owns the correction.
- If the `gmake` compiler-environment probe passes, the selected compiler and
  stage work together outside the package configure step. Preserve the
  original `config.log`; the failure is then specific to the package build
  invocation rather than the prepared shell or stage.

The script probe covers the common mount-policy failure. The copied executable
probe also checks Blueback-specific execution controls that may allow a shell
script but reject a binary. Keep both results with the failed Spack log when
requesting a code or policy correction.

### Cray PMI/Cray MPICH concretization guard

If concretization reports both `Cannot build cray-pmi` and `Cannot build
cray-mpich`, stop. That message means the workspace is treating Cray MPICH as a
source-built MPI producer. `cray-pmi` appears because the Spack `cray-mpich`
recipe declares it as a dependency; it is not a CSE build target. A correct
Blueback MPI environment includes the compiler-matched Cray MPICH external
scope and has no `group: mpi` producer root.

Check the owning inputs and generated result:

```bash
grep -nE 'CSE_(SHARED|PLATFORM)_MPI_(REF|SOURCE)' \
  "$CSE_PROVIDER_SELECTIONS"
sed -n '/^shared:/,/^platform:/p' "$BUILD_VALUES"
sed -n '/^platform:/,/^catalog_scopes:/p' "$BUILD_VALUES"
grep -nE 'group: mpi|catalog/scopes/mpi|cray-mpich' \
  "$BUILD_WORKSPACE/environments/gcc/mpi-cray-mpich/spack.yaml" \
  "$BUILD_WORKSPACE/environments/cce/mpi-cray-mpich/spack.yaml"
```

Both saved selections and both generated MPI values must say
`source: external`. Each environment must include its selected catalog MPI
scope, and neither environment may contain `group: mpi`. Correct
`$CSE_PROVIDER_SELECTIONS`, reload the operator session, and regenerate the
values/workspace from their owners. Do not edit `spack.yaml` directly. If this
release has produced only diagnostic lockfiles and no installation or cache
promotion, replace the complete workspace through the common runbook's
pre-installation `--overwrite` recovery. If installation began, preserve it and
create a new trial release.

## Restricted review and publication gates

### Phase Zero restricted module review after both surfaces finish

Do not add a package, root spec, environment, or replacement lock to create the
consumer entrance. Refresh the declared workspace controls, finish all eight
existing environments, and then run:

```bash
cd "$BUILD_WORKSPACE"
./cse-build login verify
./cse-build login publish-modules
```

The command requires the existing Foundation views and package-module roots. It
copies only `cse/init-GCC`, `cse/init-CCE`, and the ready short lane selectors
into the module root recorded by the restricted build values. Despite the
command name, this is not public stack promotion. It does not write under the
published root, publish the static catalog, create the cache-only publication
workspace, or grant access to users outside CSE. This is the CSE team-review
checkpoint for the restricted module presentation.

The CSE-GCC/Cray-MPICH selector is reported as withheld because its
simple-wrapper interface remains
`multi-node-validation-required`; the CCE selector continues to use the
reviewed platform module chain. The completed locked GCC MPI package builds
establish the build-plane compiler, link, and runtime closure.

Load the withheld GCC MPI selector from the generated workspace `modulefiles/`
tree. Confirm that `mpicc`, `mpicxx`, `mpifort`, `mpif90`, and `mpif77` resolve
under the recorded Cray MPICH prefix and that their `MPICH_*` overrides select
CSE GCC. Then run the candidate across multiple nodes through Blueback's
approved Slurm MPI plugin or Cray native launch path. Record that result with
`presentation/mpi-consumer-candidates.yaml` and publish the selector only after
the native launch succeeds. `publish-modules` has no bypass flag. The command
does not run a Spack module refresh or change the package roster, environment
YAML, lockfiles, views, package-module trees, caches, or installed prefixes.

Validate the candidate from a clean module state:

```bash
module --force purge
module load cse/init-GCC
module use "$BUILD_WORKSPACE/modulefiles/gcc/lanes"
module load MPI
module list
command -v "$CSE_MPICC" "$CSE_MPICXX" "$CSE_MPIFC"
printf '%s\n' "$MPICH_CC" "$MPICH_CXX" "$MPICH_FC"
"$CSE_MPICC" -show
srun --mpi=list

# Inside the approved allocation, substitute Blueback's reviewed plugin.
CSE_SLURM_MPI_PLUGIN="REPLACE_WITH_REVIEWED_PLUGIN"
srun --mpi="$CSE_SLURM_MPI_PLUGIN" -N 2 -n 2 ./cse-mpi-smoke
```

If Blueback uses a Cray native launcher rather than a Slurm MPI plugin for this
lane, record and run that site command instead. Do not infer a launcher from the
Cray MPICH compiler-wrapper prefix.

Stop at this checkpoint for team review. If the restricted module presentation
and runtime evidence are accepted, record the lanes as `runtime-passed`, push
their exact hashes to the
private build cache, and continue with the common runbook's public static
catalog and cache-only publication steps. If only module presentation changes,
refresh the workspace controls and repeat this checkpoint without rebuilding or
reconcretizing. A package, provider, compiler, MPI, or dependency change follows
the common runbook's DAG-changing recovery rules.

### After team acceptance: public promotion

- Copy the approved restricted lockfiles; do not reconcretize the publication
  workspace.
- Install CSE-owned packages with `--only-concrete --use-buildcache=only` into
  the published prefix.
- Load the same CPE/compiler/Cray MPICH module chain used during the restricted
  validation. Cache promotion does not remove runtime dependence on those
  externals.
- Verify all published hashes match the restricted hashes.
- Regenerate package modules, then verify each compiler front door followed by
  exactly one of Serial or MPI from clean login and compute sessions.

## Runtime acceptance

Apply `stack-planning/docs/cray_pe_acceptance_checklist_v1.md`. At minimum
verify:

- C, C++, `mpif.h`, `use mpi`, and `use mpi_f08` compile/link behavior;
- multi-node MPI launch through Slurm;
- a representative package through the published module hierarchy.

## Current run record

- Current release state:
- Last successful checkpoint (1-8):
- Held checkpoint/lane, if any:
- Exact failed command, exit status, and evidence path:
- Durable input or concrete hash changed (`yes` or `no`):
- Recovery decision (`resume same release` or `new release`):
- Earliest checkpoint to rerun and exact next command:
- Profile release/date:
- Catalog release/path:
- Restricted build values/workspace:
- Publication values/workspace:
- Selected CPE:
- Selected compiler:
- Selected Cray MPICH:
- CSE group and approved roots:
- Private build-cache URL/signing policy:
- Concretization status:
- Per-lane build/runtime/cache status:
- Cache-only publication and hash comparison:
- Published runtime/module findings:
- Release-owner approval:
