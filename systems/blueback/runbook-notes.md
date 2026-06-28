# Blueback — Runbook Notes (first iteration, run #1)

Per-system instance of the procedure in `stack-planning/docs/runbook.md`. That
runbook is the source of truth for *how*; this file records only *what* for
Blueback plus the few decisions the generic runbook doesn't cover. Bring findings
back to the source repos after each stage (per the runbook).

## System

**Blueback** — Cray (CPE), AMD CPUs + **MI300A APU** (gfx942, CDNA3, unified
memory). Mixed topology: CPU-only partitions **and** APU partitions.

## Run #1 scope — one package per kind, all CMake-buildable

| kind | package(s) | proves |
|---|---|---|
| cpu (serial) | `cmake` | foundation/core + serial path |
| mpi | `osu-micro-benchmarks`, `hdf5 +mpi` | `cray-mpich` |
| gpu | `kokkos +rocm` (gfx942) over GPU-aware `cray-mpich` | rocm/gfx942 + GPU-aware MPI |

## Selection (defaults + per-build overrides)

- `compilers: baseline` → **gcc** for every lane. Proven: Kokkos already builds
  on Blueback with gcc + ROCm (gcc-host + ROCm-as-dependency; Kokkos gets
  `hipcc` via the `hip` dep). No `rocmcc`.
- `target: baseline` → **x86_64_v3** (portable across CPU partitions — see the
  multi-partition target note in runbook Stage 2).
- `mpi: { provider: cray-mpich, source: auto }` → platform `cray-mpich` (gcc
  flavor; GPU-aware for the kokkos lane).
- gpu archs → `gfx942` (the APU nodes).
- CPE → pin the **latest** CPE version. Blueback carries multiple CPE releases;
  within one, gcc and its `cray-mpich` are a tied pair (the toolchain). Run #1
  uses the latest only; multi-CPE handling is a later item.

## Inputs to author (Stage 0 / Pre-flight)

- **`profile.yaml`** — generate with `cluster-inspector`, then review against what
  you already know is on Blueback from the Kokkos build: gcc, `cray-mpich` +
  GPU-aware flavor, ROCm/gfx942, CPU + APU node types, Slingshot/libfabric.
- **`deployment.yaml`** — start from `systems/blueback/deployment.example.yaml`
  and fill from the Kokkos build's **known-good** paths (install tree on the
  shared FS, build stage, source/misc caches, view root, module root,
  buildcache dest). No guessing.
- **`stack.yaml`** — start from `stacks/blueback-smoke/stack.yaml`; it keeps
  run #1 narrow: baseline gcc, baseline CPU target, `cray-mpich`, and
  `kokkos+rocm amdgpu_target=gfx942`.
- **Spack** — reuse the **site checkout you built Kokkos with** (≥ 1.1.1 floor):
  `spack-build --spack-root <that checkout> --skip-push`. Don't bootstrap.

## Decisions this build relies on (beyond the generic runbook)

1. **Oracle diff (de-risks the render).** Your hand-built Kokkos on Blueback is
   ground truth. After `render`, diff the generated `cray-mpich` + ROCm externals
   and compiler entries against that working config *before* building. Only build
   once they match — turns "does the pipeline work on real HW" into a checkable
   comparison.
2. **Modules are NOT a pipeline success metric.** The pipeline does not render
   modulefiles (Phase 9, still open — runbook Stage 4). For run #1, generate them
   with Spack directly (`spack -e <env> module tcl refresh`) or use `spack load` /
   the view. "Modules load" tests Spack, not the pipeline.

## Definition of done (pipeline gates)

1. `cluster-inspector` profile reviews clean against Blueback.
2. `render` succeeds **and** diff-matches the known-good Kokkos config (oracle).
3. All four roots install (cmake / osu / hdf5 / kokkos).
4. **Runtime:** `cmake --version` (serial) · **`osu_bw D D`** device-to-device
   over `cray-mpich` (headline — proves rocm + GPU-aware MPI end-to-end) · a
   Kokkos test on the MI300A reporting the HIP/`gfx942` backend.

Module generation is an interim Spack step, explicitly out of this bar.

## Open / watch (carry back per runbook)

- Inspector-profile correctness on the real box: does it probe `cray-mpich`'s
  GPU-aware flavor, `gfx942`, and the CPU + APU node types correctly?
- Phase 9 modules — record MODULEPATH / module-prereq behavior for the module
  design.
- `node_types[0]` cpu asymmetry — confirm one portable `x86_64_v3` build is
  acceptable across all CPU partitions (else per-uarch native cpu fan-out is the
  follow-up model change).
