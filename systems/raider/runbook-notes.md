# Raider system notes

Use `stack-planning/docs/runbook.md` for every command and common promotion
gate. This file records only Raider-specific facts, choices, and findings.

## System identity

- Platform: generic Rocky/RHEL-family Linux.
- Scheduler: Slurm.
- Fabric: InfiniBand.
- GPU: NVIDIA A100; expected architecture `sm_80` on the current GPU
  partition.
- Provider shape: compiler, MPI, and CUDA compatibility must be established
  from the refreshed profile and pilot policy rather than inferred from names.

## Current pilot posture

- Keep the exact compiler decision in the reviewed build values.
- The current non-Cray direction is a CSE-built OpenMPI paired with that
  compiler. Express it with `mpi.source: build`; do not teach `render-static`
  that all non-Cray systems build OpenMPI.
- Consume the compatible CUDA scope as an external.
- If a reviewed decision uses a site OpenMPI instead, record the exception and
  prove its compiler pairing before changing `mpi.source` to `external`.
- Keep Foundation/Core/Common/Serial/MPI/GPU package intent in the CSE pilot
  roster rather than the static platform catalog.

## Profile and catalog review additions

In addition to the common runbook checks:

- reject false `/usr` GCC discoveries attached to unrelated library modules;
- confirm compiler versions from driver output, not module names alone;
- when a site MPI is considered, confirm its compiler, prefix, and module chain;
- confirm every intended CUDA generation has an exact version, prefix, module,
  and runtime-node architecture;
- confirm the GPU node reports `sm_80` and the chosen CUDA generation supports
  that node.

## Restricted build and cache gates

- The selected compiler and CSE-built OpenMPI toolchain must be explicit in the
  generated environments.
- CUDA remains a non-buildable external. If Spack proposes downloading a CUDA
  installer, fix the profile/catalog rather than the workspace.
- Serial contains no MPI implementation.
- MPI and GPU use the same approved OpenMPI pairing.
- Every lane is exercised on Raider before its concrete specs enter the private
  CSE build cache.
- The cache contains the built OpenMPI and CSE-owned packages required by the
  approved locks; it does not package the external CUDA installation.

## Publication gates

- Copy the approved restricted lockfiles; do not reconcretize the publication
  workspace.
- Install with `--only-concrete --use-buildcache=only` into the published
  prefix. A missing OpenMPI or package binary holds publication.
- Load the same compiler and CUDA modules used during restricted validation.
- Verify all published hashes match the restricted hashes.
- Regenerate package modules and test the compiler front door followed by one
  lane selector from clean login and compute sessions.

## Runtime acceptance

Apply `stack-planning/docs/generic_linux_acceptance_checklist_v1.md`. At minimum
verify:

- compiler and MPI wrappers resolve from the selected surface;
- multi-node MPI launch through Slurm;
- CUDA device visibility and a representative CUDA/Kokkos workload on A100;
- an external CUDA package is used rather than fetched;
- a representative package through the published module hierarchy.

## Current run record

- Profile release/date:
- Catalog release/path:
- Restricted build values/workspace:
- Publication values/workspace:
- Selected compiler:
- Selected MPI:
- Selected CUDA/GPU architecture:
- CSE group and approved roots:
- Private build-cache URL/signing policy:
- Concretization status:
- Per-lane build/runtime/cache status:
- Cache-only publication and hash comparison:
- Published runtime/module findings:
- Release-owner approval:
