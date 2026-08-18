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
