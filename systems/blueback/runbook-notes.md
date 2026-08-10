# Blueback system notes

Use `stack-planning/docs/runbook.md` for every command and common gate. This
file records only Blueback-specific facts, choices, and findings.

## System identity

- Platform: HPE Cray EX / Cray Programming Environment.
- Scheduler: Slurm.
- Fabric: Slingshot/CXI.
- GPU: AMD MI300A APU; expected architecture `gfx942` on the current GPU
  partition.
- Provider shape: one coherent CPE release must supply the compiler, Cray
  MPICH flavor, ROCm runtime, and platform modules selected for the pilot.

## Current pilot posture

- Start with the platform GCC surface. Treat a stack-built common CSE GCC as a
  later comparison, not as the critical path.
- Consume the compatible `cray-mpich` and ROCm scopes from the refreshed static
  catalog.
- Select exact versions from the live profile and current catalog. Do not copy
  versions from an earlier Blueback run; the system carries multiple CPE
  releases and its default has changed before.
- Keep Foundation/Core/Common/Serial/MPI/GPU package intent in the CSE pilot
  blueprint. Do not add Blueback package policy to `render-static`.

## Profile review additions

In addition to the common runbook checks:

- confirm the selected CPE is the intended current release;
- confirm the GCC provider includes the required `PrgEnv-gnu`/compiler module
  chain and exact prefix;
- confirm the selected Cray MPICH record has the GNU flavor that accepts the
  selected GCC and points at the real flavor prefix;
- confirm ROCm, HIP, HSA runtime, and GPU architecture facts all describe the
  same CPE/runtime generation;
- confirm fabric/runtime externals refer to the active CXI/Cray PE stack;
- reject cross-CPE compiler/MPI/GPU combinations even when every individual
  module exists.

## Catalog and workspace gates

- The selected compiler, MPI, GPU, and platform catalog scopes must all come
  from the same reviewed runtime tuple.
- Cray MPICH and ROCm packages must be non-buildable externals at live prefixes.
- The Serial environment must contain no MPI implementation.
- The MPI and GPU environments must use the same selected Cray MPICH pairing.
- GPU-aware MPI currently needs explicit GTL validation. Record whether the
  run still uses an `LD_PRELOAD` workaround or links the matching GTL directly.

## Runtime acceptance

After the common build and module checks, apply
`stack-planning/docs/cray_pe_acceptance_checklist_v1.md`. At minimum verify:

- C, C++, `mpif.h`, `use mpi`, and `use mpi_f08` compile/link behavior;
- multi-node MPI launch through Slurm;
- ROCm device visibility on an allocated MI300A node;
- GPU-aware MPI with the exact selected Cray MPICH/GTL/runtime tuple;
- compiler front door followed by exactly one of Serial, MPI, or GPU.

## Current run record

- Profile release/date:
- Catalog release:
- Pilot release:
- Selected CPE:
- Selected compiler:
- Selected Cray MPICH:
- Selected ROCm/GPU architecture:
- Approved roots/group:
- Concretization status:
- Build status:
- Runtime/module findings:
