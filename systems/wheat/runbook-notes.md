# Wheat system notes

Use `stack-planning/docs/runbook.md` for every common command and gate. This
file records only Wheat-specific facts and open checks.

## System identity

- Platform: generic Linux.
- Scheduler: PBS.
- GPU builds: outside the Initial Conversion Trials.

## Provisional module snapshot (2026-08-12)

The screenshot shows the following baseline. Cluster Inspector must verify the
driver family, versions, prefixes, and complete module chains before they are
used in values files.

- `intel/2024.2.1/compiler/latest`
- `intel/2024.2.1/compiler-rt/latest`
- `intel/2024.2.1/tbb/latest`
- `gcc/12.2.1` as a loaded default

The module names suggest the LLVM-based oneAPI compiler, but the profile must
decide from the actual drivers. Report `oneapi` for `icx`, `icpx`, and `ifx`;
report Classic Intel only if `icc`, `icpc`, and `ifort` are the provided
drivers.

## Trial surfaces

| Surface | Compiler | MPI |
|---|---|---|
| Shared CSE | GCC 12.5.0 | CSE-built OpenMPI 4.1.8 |
| Platform | Intel 2024.2.1 provider verified by drivers | CSE-built OpenMPI 4.1.8 |

The static scope path retains the observed provider identity. The values file
uses the manifest's Spack `package` identity. Build OpenMPI separately with
each compiler surface.

For an LLVM-based oneAPI platform surface, the generated workspace also
includes the verified GCC seed scope. That GCC is present only to provide the
`gcc-runtime` dependency required by `intel-oneapi-runtime`; Wheat payload roots
remain bound to the oneAPI compiler.

## Verify or recover the GCC `+binutils` producer

The complete GCC 12.5.0 policy is owned by the CSE trial blueprint in Stack
Content. It requires `+binutils` on the producer, every downstream GCC root,
and the shared C/C++/Fortran provider requirements. It is not supplied by
Cluster Inspector, `render-static`, or the static catalog. Updating only
Cluster Inspector or Stack Composer therefore does not update this policy.

After loading the Wheat operator session, verify the source, generated
environment inputs, and concrete locks in that order:

```bash
source "$CSE_OPERATOR_SESSION_FILE"

git -C "$CONTENT" pull --ff-only origin codex/simplified-render-plan
git -C "$CONTENT" log -1 --oneline

grep -R -n --include=spack.yaml \
  '%gcc@12.5.0+binutils' \
  "$BUILD_WORKSPACE/environments/gcc"

cd "$BUILD_WORKSPACE"
./cse-build login verify
```

The `grep` command must show managed downstream constraints in all four GCC
environments. `verify` checks the producer, downstream constraints, language
provider preferences, and concrete compiler hashes. A passing result proves
that no current Wheat root can reuse an older `gcc@12.5.0~binutils` prefix.

If the managed constraints are absent or verification reports mixed compiler
hashes, a controls-only refresh is insufficient because it preserves the old
environment YAML and lockfiles. When no Wheat package installation has been
accepted, follow the canonical runbook's **Pre-install workspace refresh**
procedure. It uses `init-workspace --overwrite`, then reconcretizes and verifies
all eight environments. The static catalog does not need to be regenerated for
this blueprint-only correction.

Do not select an arbitrary latest external GCC for that runtime dependency.
The helper reuses the same newest verified compiler older than GCC 12.5.0 that
the reviewed catalog selects to build the GCC 12.5.0 producer. Use
`CSE_SHARED_COMPILER_SEED_REF` only when catalog review deliberately selects a
different installed GCC scope.

For Step 7, use `gcc@12.5.0` and build-sourced `openmpi@4.1.8` for the shared
surface. For the platform surface, copy the exact provider reference reported
by the live profile: `oneapi@...` for `icx`/`icpx`/`ifx`, or `intel@...` for
`icc`/`icpc`/`ifort`. Do not translate the module suite label into a compiler
product version by guess. Both MPI selections use `openmpi@4.1.8` with
`source=build`. Record the reviewed node contexts with the other Step 7
selections:

```bash
export CSE_LOGIN_NODE_TYPE="login"
export CSE_COMPUTE_NODE_TYPE="cpu_compute"
```

These values assume the standard context keys. Replace either value when
Wheat's catalog uses a different exact key.

## Required profile and catalog checks

- Verify whether the compiler drivers are oneAPI or Classic Intel.
- Preserve the complete Intel runtime/compiler module chain.
- Capture the supported fabric userspace and choose an explicit OpenMPI fabric
  policy before the build solve.
- Confirm the platform compiler scope contains exact driver paths.
- Confirm no site MPI is selected merely because it is loaded by default.

## Current run record

- Profile release/date:
- Catalog release/path:
- Restricted build values/workspace:
- Selected Intel provider/package identity:
- Selected Intel module chain and driver paths:
- Selected OpenMPI fabric policy:
- CSE roots and build stage:
- Work-tree review status:
- Exact next command:
