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
export BUILD_JOBS="<approved-job-count>"
```

These are the only required Blueback-specific Step 7 selections. The helper
normally selects the newest verified installed GCC older than 12.5.0 as the
compiler used to build GCC 12.5.0. If catalog review requires another installed
compiler, set `CSE_SHARED_COMPILER_SEED_REF="<provider>@<version>"` explicitly.
This seed compiler is separate from the Cray MPICH flavor selection.

The standard profile keys are `login` and `cpu_compute`. Set
`CSE_LOGIN_NODE_TYPE` or `CSE_COMPUTE_NODE_TYPE` only when the Blueback catalog
uses different keys. The helper records both contexts. `./cse-build login`
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
  package records own the exact module chains and `cse-build` clears only a
  selected provider module that was already loaded before Spack needs it.
- Both Serial environments contain no MPI implementation.
- Each MPI environment uses the Cray MPICH flavor matched to its compiler
  surface.
- Every lane is exercised under the selected CPE modules before its concrete
  specs enter the private CSE build cache.
- The cache contains CSE-built packages only; it does not attempt to package or
  relocate the platform-owned CPE or Cray MPICH installations.

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
