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

cd "$INSPECTOR"
make build
./cluster-inspector --help >/dev/null
git rev-parse HEAD > "$CSE_TOOL_STATE_ROOT/cluster-inspector.commit"
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

Do not add `--dirty`. The permanent fix must work in Spack's normal clean build
environment. Do not encode `PE_ENV=GNU` as a Blueback- or FFTW-specific rule;
the generic Cray provider policy must derive the compiler-family selector and
provider-owned link state from the selected compiler/Cray MPICH pairing.

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

## Publication gates

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
