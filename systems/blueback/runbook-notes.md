# Blueback system notes

Use `stack-planning/docs/runbook.md` for every command and common promotion
gate. This file records only Blueback-specific facts, choices, and findings.

## System identity

- Platform: HPE Cray EX / Cray Programming Environment.
- Scheduler: Slurm.
- Fabric: Slingshot/CXI.
- GPU: AMD MI300A APU; expected architecture `gfx942` on the current GPU
  partition.
- Provider shape: one coherent CPE release must supply the compiler, Cray
  MPICH flavor, ROCm runtime, and platform modules selected for the pilot.

## Current pilot posture

- Keep the exact compiler decision in the reviewed build values; do not infer
  it from Blueback's default module state.
- Use the platform-provided `cray-mpich` paired with that compiler and CPE.
- Consume the compatible ROCm scope as an external.
- Select exact versions from the live profile and current catalog. Blueback
  carries multiple CPE releases, and its default has changed before.
- Keep Foundation/Core/Common/Serial/MPI/GPU package intent in the CSE pilot
  roster. Do not add Blueback package policy to `render-static`.

## Profile and catalog review additions

In addition to the common runbook checks:

- confirm the selected CPE is the intended current release;
- confirm the compiler provider includes the complete program-environment and
  compiler module chain plus the exact prefix;
- confirm the selected Cray MPICH record has the matching compiler flavor and
  real flavor prefix;
- confirm ROCm, HIP, HSA runtime, and `gfx942` facts describe the same
  CPE/runtime generation;
- confirm fabric/runtime externals refer to the active CXI/Cray PE stack;
- reject cross-CPE compiler/MPI/GPU combinations even when every individual
  module exists.

## Restricted build and cache gates

- Cray MPICH and ROCm packages remain non-buildable externals at live prefixes.
- Serial contains no MPI implementation.
- MPI and GPU use the same selected Cray MPICH pairing.
- Every lane is exercised under the selected CPE modules before its concrete
  specs enter the private CSE build cache.
- GPU-aware MPI includes explicit GTL/runtime validation. Record whether the
  run still uses an `LD_PRELOAD` workaround or links the matching GTL directly.
- The cache contains CSE-built packages only; it does not attempt to package or
  relocate the platform-owned CPE, Cray MPICH, or ROCm installations.

## Publication gates

- Copy the approved restricted lockfiles; do not reconcretize the publication
  workspace.
- Install CSE-owned packages with `--only-concrete --use-buildcache=only` into
  the published prefix.
- Load the same CPE/compiler/Cray MPICH/ROCm module chain used during the
  restricted validation. Cache promotion does not remove runtime dependence on
  those externals.
- Verify all published hashes match the restricted hashes.
- Regenerate package modules, then verify the compiler front door followed by
  exactly one of Serial, MPI, or GPU from clean login and compute sessions.

## Runtime acceptance

Apply `stack-planning/docs/cray_pe_acceptance_checklist_v1.md`. At minimum
verify:

- C, C++, `mpif.h`, `use mpi`, and `use mpi_f08` compile/link behavior;
- multi-node MPI launch through Slurm;
- ROCm device visibility on an allocated MI300A node;
- GPU-aware MPI with the exact selected Cray MPICH/GTL/runtime tuple;
- a representative package through the published module hierarchy.

## Current run record

- Profile release/date:
- Catalog release/path:
- Restricted build values/workspace:
- Publication values/workspace:
- Selected CPE:
- Selected compiler:
- Selected Cray MPICH:
- Selected ROCm/GPU architecture:
- CSE group and approved roots:
- Private build-cache URL/signing policy:
- Concretization status:
- Per-lane build/runtime/cache status:
- Cache-only publication and hash comparison:
- Published runtime/module findings:
- Release-owner approval:
