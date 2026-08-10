# Raider system notes

Use `stack-planning/docs/runbook.md` for every command and common gate. This
file records only Raider-specific facts, choices, and findings.

## System identity

- Platform: generic Rocky/RHEL-family Linux.
- Scheduler: Slurm.
- Fabric: InfiniBand.
- GPU: NVIDIA A100; expected architecture `sm_80` on the current GPU
  partition.
- Provider shape: selected site compiler, MPI, and CUDA compatibility must be
  established from the refreshed profile rather than inferred from names.

## Current pilot posture

- Start with the platform GCC surface and a compatible site OpenMPI when the
  refreshed profile proves that pairing.
- Consume the compatible CUDA scope as an external.
- Treat AOCC and stack-built MPI surfaces as follow-up comparisons after the
  GCC surface passes end to end.
- If the profile has no usable site GCC/OpenMPI pairing, stop and record the
  fact before choosing a stack-built MPI experiment.

## Profile review additions

In addition to the common runbook checks:

- reject false `/usr` GCC discoveries attached to unrelated library modules;
- confirm compiler and MPI versions from their driver output, not module names
  alone;
- confirm the selected OpenMPI record names the GCC it was built with and its
  real prefix/modules;
- confirm every intended CUDA generation has an exact version, prefix, module,
  and runtime-node architecture;
- confirm the GPU node reports `sm_80` and the chosen CUDA generation supports
  that node.

## Catalog and workspace gates

- The selected GCC and OpenMPI scopes must describe the same compiler pairing.
- CUDA packages must be non-buildable externals at the live CUDA prefix. If
  Spack proposes downloading a CUDA installer, fix the profile/catalog rather
  than the initialized workspace.
- The Serial environment must contain no MPI implementation.
- The MPI and GPU environments must use the same selected OpenMPI pairing.
- Common packages must resolve to one install reused from Serial, MPI, and GPU.

## Runtime acceptance

After the common build and module checks, apply
`stack-planning/docs/generic_linux_acceptance_checklist_v1.md`. At minimum
verify:

- compiler and MPI wrappers resolve from the selected surface;
- multi-node MPI launch through Slurm;
- CUDA device visibility and a representative CUDA/Kokkos workload on A100;
- compiler front door followed by exactly one of Serial, MPI, or GPU;
- an external CUDA package is used rather than fetched.

## Current run record

- Profile release/date:
- Catalog release:
- Pilot release:
- Selected compiler:
- Selected MPI:
- Selected CUDA/GPU architecture:
- Approved roots/group:
- Concretization status:
- Build status:
- Runtime/module findings:
