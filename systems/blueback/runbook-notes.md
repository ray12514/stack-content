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

## Blueback command map (current `~/STACK_TESTING` layout)

Assume the repos are checked out as siblings:

```text
~/STACK_TESTING/
  cluster-inspector/
  stack-composer/
  stack-content/
```

Set these once per shell:

```bash
export WORK_ROOT="$HOME/STACK_TESTING"
export CONTENT="$WORK_ROOT/stack-content"
export COMPOSER="$WORK_ROOT/stack-composer"
export BLUEBACK="$CONTENT/systems/blueback"
export RENDER_ROOT="$WORK_ROOT/rendered"
```

Update the local checkouts before building/rendering. If you have local
Blueback edits, commit them or stash them before `git pull --ff-only`.

```bash
git -C "$WORK_ROOT/cluster-inspector" pull --ff-only
git -C "$WORK_ROOT/stack-composer" pull --ff-only
git -C "$WORK_ROOT/stack-content" pull --ff-only
```

Build the local `stack-composer.pyz` release artifact. Do this in a repo-local
virtual environment so no packages are installed into the site/CSE environment.
Run the build script with `bash`; it is a shell script, not a Python script.

```bash
cd "$COMPOSER"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
bash scripts/build-pyz.sh
```

Source the local Spack activation script before writing `deployment.yaml`, then
fail fast if it did not set `SPACK_ROOT`:

```bash
source /path/to/use-spack.sh
: "${SPACK_ROOT:?SPACK_ROOT is not set; source use-spack.sh first}"
spack --version
```

The profile produced by the fragment merge should live at:

```bash
export PROFILE="$BLUEBACK/profile.yaml"
```

Create the first-pass deployment file from the example. The values below keep
the first render/build contained under the operator's test area; replace them
with the approved shared install/cache/buildcache roots before publishing any
real stack.

```bash
cat > "$BLUEBACK/deployment.yaml" <<EOF
schema_version: 1
system: blueback

install_tree:
  root: $WORK_ROOT/install/spack/opt
  padded_length: 128

build_stage:
  default: $WORK_ROOT/stage/spack-stage

caches:
  source: $WORK_ROOT/cache/spack/source-cache
  misc: $WORK_ROOT/cache/misc

roots:
  views: $WORK_ROOT/views
  modules: $WORK_ROOT/modules

modules:
  publish_root: null

buildcache:
  destinations:
    - { name: payload, url: "file://$WORK_ROOT/buildcache/payload" }

spack:
  root: $SPACK_ROOT
EOF
```

Use the `stack-composer.pyz` from the local build without installing it into the
site environment:

```bash
export STACK_COMPOSER="$COMPOSER/dist/stack-composer.pyz"
```

Validate first:

```bash
python "$STACK_COMPOSER" validate \
  --profile "$PROFILE" \
  --deployment "$BLUEBACK/deployment.yaml" \
  --stack "$CONTENT/stacks/blueback-smoke/stack.yaml" \
  --templates "$CONTENT/templates" \
  --package-sets "$CONTENT/package-sets" \
  --package-repos "$CONTENT/package-repos" \
  --report "$BLUEBACK/validate-report.yaml"
```

Render only after validation passes:

```bash
python "$STACK_COMPOSER" render \
  --profile "$PROFILE" \
  --deployment "$BLUEBACK/deployment.yaml" \
  --stack "$CONTENT/stacks/blueback-smoke/stack.yaml" \
  --templates "$CONTENT/templates" \
  --package-sets "$CONTENT/package-sets" \
  --package-repos "$CONTENT/package-repos" \
  --output-root "$RENDER_ROOT" \
  --release blueback-smoke-001 \
  --rendered-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --source-repo "local-blueback-smoke" \
  --source-commit "$(git -C "$CONTENT" rev-parse --short=12 HEAD)" \
  --source-dirty
```

`--source-repo` may be a development identifier for this first run. The
`--source-commit` value must look like a git hex digest; using the current
`stack-content` commit is enough. Keep `--source-dirty` while the Blueback files
are locally edited and not yet committed.

Expected rendered workspace:

```text
$RENDER_ROOT/blueback/blueback-smoke/blueback-smoke-001/
```

After render, inspect:

```bash
find "$RENDER_ROOT/blueback/blueback-smoke/blueback-smoke-001/modulefiles" -type f | sort
sed -n '1,160p' "$RENDER_ROOT/blueback/blueback-smoke/blueback-smoke-001/configs/common/config.yaml"
sed -n '1,220p' "$RENDER_ROOT/blueback/blueback-smoke/blueback-smoke-001/configs/mpi/cray-mpich/packages.yaml"
sed -n '1,220p' "$RENDER_ROOT/blueback/blueback-smoke/blueback-smoke-001/configs/gpu/amd-rocm/packages.yaml"
```

## Decisions this build relies on (beyond the generic runbook)

1. **Oracle diff (de-risks the render).** Your hand-built Kokkos on Blueback is
   ground truth. After `render`, diff the generated `cray-mpich` + ROCm externals
   and compiler entries against that working config *before* building. Only build
   once they match — turns "does the pipeline work on real HW" into a checkable
   comparison.
2. **Modules are a split responsibility.** The renderer emits front-door
   compiler-init and lane modulefiles. Spack still generates package modulefiles
   (`spack -e <env> module tcl refresh`). For run #1, inspect the rendered
   lane prereqs and use Spack-generated package modules or the view.
3. **Module loading is a compiler-init → lane → package chain.** The compiler
   init module, e.g. `science_init_gcc`, exposes the GCC foundation/core view
   and makes the GCC lane modules visible. The user then loads one lane module,
   e.g. `science/mpi`, which prereqs the platform modules and prepends only that
   lane's package-module root. Do not expose all lane package roots at once from
   the init module.

## Definition of done (pipeline gates)

1. `cluster-inspector` profile reviews clean against Blueback.
2. `render` succeeds **and** diff-matches the known-good Kokkos config (oracle).
3. All four roots install (cmake / osu / hdf5 / kokkos).
4. Rendered compiler-init and lane modulefiles exist. The compiler init module
   exposes only the selected foundation/core view plus lane modules, and after
   Spack package module generation each lane module exposes only that lane's
   packages.
5. **Runtime:** `cmake --version` (serial) · **`osu_bw D D`** device-to-device
   over `cray-mpich` (headline — proves rocm + GPU-aware MPI end-to-end) · a
   Kokkos test on the MI300A reporting the HIP/`gfx942` backend.

## Open / watch (carry back per runbook)

- Inspector-profile correctness on the real box: does it probe `cray-mpich`'s
  GPU-aware flavor, `gfx942`, and the CPU + APU node types correctly?
- Module exposure — record MODULEPATH / module-prereq behavior for rendered
  compiler-init/lane modules plus Spack-generated package modules.
- `node_types[0]` cpu asymmetry — confirm one portable `x86_64_v3` build is
  acceptable across all CPU partitions (else per-uarch native cpu fan-out is the
  follow-up model change).
