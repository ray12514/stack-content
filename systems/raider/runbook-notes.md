# Raider system notes

Use `stack-planning/docs/runbook.md` for every command and common promotion
gate. This file records only Raider-specific facts, choices, and findings.

## System identity

- Platform: generic Rocky/RHEL-family Linux.
- Scheduler: Slurm.
- Fabric: InfiniBand.
- Accelerator facts: NVIDIA A100 with `sm_80` is expected in the profile, but
  GPU builds are outside the Initial Conversion Trials.
- Provider shape: each compiler and OpenMPI pairing must be explicit rather
  than inferred from names.

## Current trial posture

- Build the shared GCC 12.5.0 producer, Foundation, Core, and build tools with
  GCC.
- Keep the exact external platform compiler decision in the reviewed build
  values.
- Build OpenMPI 4.1.8 once with GCC 12.5.0 and once with the selected platform
  compiler. Express both with `mpi.source: build`; do not teach
  `render-static` that all non-Cray systems build OpenMPI.
- Keep Foundation/Core/Common/Serial/MPI package intent in the CSE trial roster
  rather than the static platform catalog.

## Profile and catalog review additions

In addition to the common runbook checks:

- reject false `/usr` GCC discoveries attached to unrelated library modules;
- confirm compiler versions from driver output, not module names alone;
- confirm the selected platform compiler prefix and full module chain.

## Restricted build and cache gates

- Both compiler surfaces and both CSE-built OpenMPI toolchains must be explicit
  in the generated environments.
- Both Serial environments contain no MPI implementation.
- Each MPI environment uses the OpenMPI 4.1.8 producer built with its compiler.
- Every lane is exercised on Raider before its concrete specs enter the private
  CSE build cache.
- The cache contains both built OpenMPI producers and the CSE-owned packages
  required by the approved locks.

## Publication gates

- Copy the approved restricted lockfiles; do not reconcretize the publication
  workspace.
- Install with `--only-concrete --use-buildcache=only` into the published
  prefix. A missing OpenMPI or package binary holds publication.
- Load the same external platform compiler modules used during restricted
  validation. The GCC and OpenMPI producer modules come from the CSE release.
- Verify all published hashes match the restricted hashes.
- Regenerate package modules and test the compiler front door followed by one
  lane selector from clean login and compute sessions.

## Runtime acceptance

Apply `stack-planning/docs/generic_linux_acceptance_checklist_v1.md`. At minimum
verify:

- compiler and MPI wrappers resolve from the selected surface;
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
- Selected compiler:
- Selected MPI:
- CSE group and approved roots:
- Private build-cache URL/signing policy:
- Concretization status:
- Per-lane build/runtime/cache status:
- Cache-only publication and hash comparison:
- Published runtime/module findings:
- Release-owner approval:
