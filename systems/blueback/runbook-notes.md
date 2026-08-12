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

## Profile and catalog review additions

In addition to the common runbook checks:

- confirm the selected CPE is the intended current release;
- confirm the compiler provider includes the complete program-environment and
  compiler module chain plus the exact prefix;
- confirm the selected Cray MPICH record has the matching compiler flavor and
  real flavor prefix;
- confirm fabric/runtime externals refer to the active CXI/Cray PE stack;
- reject cross-CPE compiler/MPI combinations even when every individual module
  exists.

## Restricted build and cache gates

- Cray MPICH remains a non-buildable external at its live prefix.
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
