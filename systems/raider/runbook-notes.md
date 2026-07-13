# Raider runbook notes

Raider: generic Linux cluster (Rocky/RHEL family), Slurm, InfiniBand,
NVIDIA A100 (sm_80). Site GCC + site OpenMPI consumed as externals — this
system is the NVIDIA/generic-Linux twin of the Blueback procedure, and the
container smoke (systems/smoke) already validated the same path end to end
with one exception: the CUDA lane, which only this machine can prove.

## First science run (2026-07-10 procedure)

0. Pull all repos; rebuild the inspector binary and composer pyz. Stale
   artifacts caused false failures twice in the container runs.
1. Probe → merge → verify. Check the fact sheet before using it:
   - compiler_providers: the real site GCC modules only — no gcc entries at
     /usr riding library modules (the inspector now rejects those, and it
     takes MPI/compiler versions from the drivers' own reports);
   - mpi_providers: openmpi entries with real versions and the gcc they
     were built with (module naming like openmpi/x.y.z/gcc-a.b.c);
   - gpu_toolkit_modules.cudatoolkit: every CUDA generation with version,
     module, and prefix; node arch_target sm_80.
2. Commit profile.yaml + deployment.yaml here (systems/raider/) via PR —
   this directory is the system's record.
3. Validate + render `stacks/linux-science/stack.yaml`. Expect core,
   serial, mpi-openmpi, and gpu-openmpi-sm_80 lanes under the gcc surface.
4. **Outstanding check from the last Raider session:** the earlier run had
   Spack fetching cuda_12.9_linux.run. Before building, confirm
   `configs/gpu/nvidia-cuda/packages.yaml` pins cuda buildable false at the
   real prefix and that the gpu environment's spack.yaml includes that
   scope. If the file is empty, the profile's cudatoolkit facts are wrong —
   fix the fact sheet, never the rendered files.
5. Concretize all lanes. Gates (same as Blueback): externals used never
   fetched (gcc, openmpi, cuda, openssl); serial lock has zero MPI nodes;
   coherent hdf5 chains; two pythons in core.
6. Install, regenerate views/modules, front-door check:
   `module load cse/GCC` → one lane → package. Conflicts fail loudly.
   Lane-agnostic check (same as Blueback): from the MPI lane,
   `module avail openblas` shows the serial-built openblas/netlib-lapack/
   gnuplot via `<compiler>/shared`; loading one resolves to the same
   install the Serial lane sees (one hash). boost is dual-build: each lane
   shows its own boost (~mpi vs +mpi) under the same clean name.
7. Generate the platform catalog (`render-static`) and commit it under
   systems/raider/static/<release>/ for the app managers building outside
   the stack.
8. Second surface (AOCC) only after the GCC surface is green end to end.
