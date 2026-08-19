# Fran system notes

Use `stack-planning/docs/runbook.md` for every common command and gate. This
file records only Fran-specific facts and open checks.

## System identity

- Platform: HPE Cray / Cray Programming Environment.
- Scheduler: confirm from the live profile and site commands.
- GPU builds: outside the Initial Conversion Trials.

## Provisional module snapshot (2026-08-12)

The screenshot shows the following baseline. Cluster Inspector must verify the
versions, prefixes, driver reports, and complete module chains before they are
used in values files.

- `PrgEnv-cray/8.6.0`
- `cce/20.0.0`
- `cray-mpich/9.0.1`
- a `libfabric/2.2...` module; exact version and prefix still require capture
- `craype-x86-genoa`
- `craype-network-ofi`
- `cray-libsci/25.09.0`

## Trial surfaces

| Surface | Compiler | MPI |
|---|---|---|
| Shared CSE | GCC 12.5.0 | platform Cray MPICH 9.0.1 GNU flavor |
| Platform | CCE 20.0.0 | platform Cray MPICH 9.0.1 CCE flavor |

Build the GCC 12.5.0 compiler producer inside each GCC-surface environment.
Matching hashes let the shared store reuse it across those environments. Cray
MPICH, libfabric, and Cray PMI remain platform externals.

Use this reviewed Step 7 selection after the live catalog confirms the module
chains and flavor prefixes:

```bash
export CSE_SHARED_COMPILER_REF="gcc@12.5.0"
export CSE_SHARED_COMPILER_PUBLIC_NAME="init-GCC"
export CSE_SHARED_MPI_REF="cray-mpich@9.0.1"
export CSE_SHARED_MPI_SOURCE="external"
export CSE_PLATFORM_COMPILER_REF="cce@20.0.0"
export CSE_PLATFORM_COMPILER_PUBLIC_NAME="init-CCE"
export CSE_PLATFORM_MPI_REF="cray-mpich@9.0.1"
export CSE_PLATFORM_MPI_SOURCE="external"
export CSE_LOGIN_NODE_TYPE="login"
export CSE_COMPUTE_NODE_TYPE="cpu_compute"
export BUILD_JOBS="<approved-job-count>"
```

The values above assume the standard context keys `login` and `cpu_compute`.
Replace either value when Fran's catalog uses a different exact key.

## Required profile and catalog checks

- Capture the exact `ofi/cray/<baseline>` prefix paired with CCE 20.0.0.
- Capture the exact `ofi/gnu/<baseline>` prefix compatible with GCC 12.5.0.
- Capture the exact libfabric and Cray PMI versions and prefixes.
- Confirm the common static scope contains libfabric.
- Confirm each Cray MPICH static scope contains the matching Cray MPICH
  external and the inspected `cray-pmi` external.
- Reject cross-CPE combinations even when individual modules load.
- Do not manually preload `PrgEnv-gnu`, `PrgEnv-cray`, `gcc`, `cce`, or
  `cray-mpich` before `cse-build`. The workspace's external package records
  own the exact module chains.

## Current run record

- Profile release/date:
- Catalog release/path:
- Restricted build values/workspace:
- Selected CPE/module chain:
- Selected CCE and Cray MPICH flavor:
- Selected GCC and Cray MPICH flavor:
- Selected libfabric and Cray PMI:
- CSE roots and build stage:
- Work-tree review status:
- Exact next command:
