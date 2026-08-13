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

Build GCC 12.5.0 in the bootstrap environment. Cray MPICH, libfabric, and
Cray PMI remain platform externals.

## Required profile and catalog checks

- Capture the exact `ofi/cray/<baseline>` prefix paired with CCE 20.0.0.
- Capture the exact `ofi/gnu/<baseline>` prefix compatible with GCC 12.5.0.
- Capture the exact libfabric and Cray PMI versions and prefixes.
- Confirm the common static scope contains libfabric.
- Confirm each Cray MPICH static scope contains the matching Cray MPICH
  external and the inspected `cray-pmi` external.
- Reject cross-CPE combinations even when individual modules load.

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
