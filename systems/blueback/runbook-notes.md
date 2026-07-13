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
| serial | `cmake` | foundation/core + serial path |
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
export INSPECTOR="$WORK_ROOT/cluster-inspector"
export BLUEBACK="$CONTENT/systems/blueback"
export RENDER_ROOT="$WORK_ROOT/rendered"
export STACK_BRANCH="codex/simplified-render-plan"
```

Update the local checkouts onto the current test branch before
building/rendering. If you have local Blueback edits, commit them or stash them
before `git switch` / `git pull --ff-only`.

```bash
for repo in cluster-inspector stack-composer stack-content; do
  git -C "$WORK_ROOT/$repo" fetch origin
  git -C "$WORK_ROOT/$repo" switch "$STACK_BRANCH"
  git -C "$WORK_ROOT/$repo" pull --ff-only
done

# Optional: update the planning docs too if stack-planning is checked out.
if [ -d "$WORK_ROOT/stack-planning/.git" ]; then
  git -C "$WORK_ROOT/stack-planning" fetch origin
  git -C "$WORK_ROOT/stack-planning" switch "$STACK_BRANCH"
  git -C "$WORK_ROOT/stack-planning" pull --ff-only
fi
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
export STACK_GROUP="${STACK_GROUP:-cse}"

cat > "$BLUEBACK/deployment.yaml" <<EOF
schema_version: 1
system: blueback
access:
  group: $STACK_GROUP
  read: group
  write: group

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
export RELEASE=blueback-smoke-001

python "$STACK_COMPOSER" render \
  --profile "$PROFILE" \
  --deployment "$BLUEBACK/deployment.yaml" \
  --stack "$CONTENT/stacks/blueback-smoke/stack.yaml" \
  --templates "$CONTENT/templates" \
  --package-sets "$CONTENT/package-sets" \
  --package-repos "$CONTENT/package-repos" \
  --output-root "$RENDER_ROOT" \
  --release "$RELEASE" \
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
$RENDER_ROOT/blueback/blueback-smoke/$RELEASE/
```

After render, inspect:

```bash
export WORKSPACE="$RENDER_ROOT/blueback/blueback-smoke/$RELEASE"

find "$WORKSPACE/modulefiles" -type f | sort
sed -n '1,160p' "$WORKSPACE/configs/common/config.yaml"
sed -n '1,220p' "$WORKSPACE/reports/render-plan.yaml"
sed -n '1,220p' "$WORKSPACE/configs/mpi/cray-mpich/packages.yaml"
sed -n '1,80p' "$WORKSPACE/configs/mpi/cray-mpich/toolchains.yaml"
sed -n '1,220p' "$WORKSPACE/configs/gpu/amd-rocm/packages.yaml"
```

Before building, verify the MPI selection matches the Blueback smoke intent:

```bash
grep -R "configs/mpi/openmpi" "$WORKSPACE/environments" -n || true
grep -R "configs/mpi/cray-mpich" "$WORKSPACE/environments" -n
```

The OpenMPI grep should return no environment includes for this smoke stack.
The Cray MPICH grep should show one combined MPI lane plus the GPU lane.

Also check the network plan before building:

```bash
grep -n "platform_plan:" "$WORKSPACE/reports/render-plan.yaml"
grep -n "older_than_selected_platform_version" "$WORKSPACE/reports/render-plan.yaml" || true
grep -n "fabric_userspace:" "$WORKSPACE/reports/render-plan.yaml"
grep -n "cray-gtl\\|cray-pmi\\|cray-pals" "$WORKSPACE/reports/render-plan.yaml" || true
grep -n "requires_explicit_package_repo_policy" "$WORKSPACE/reports/render-plan.yaml" || true
grep -n "cray-gtl\\|cray-pmi\\|cray-pals" "$WORKSPACE/configs/common/packages.yaml" && false || true
grep -n "cray-libsci@" "$WORKSPACE/configs/common/packages.yaml" || true
```

If Cluster Inspector observes Cray GTL, PMI, or PALS, they should appear in the
render plan as observed network/runtime facts. They should not appear in
`configs/common/packages.yaml` during this smoke run; those package names need
an explicit package repo policy before they are safe to render as Spack
externals. `libfabric` and `ucx` may still be rendered as common fabric
externals.

If Cluster Inspector observes multiple Cray LibSci generations, Stack Composer
should render only the selected/latest generation in `configs/common/packages.yaml`
and list the older generations in `platform_plan.ignored_system_externals`.

Build from the rendered workspace with the shipped `spack-build` helper. The
first command builds one cheap lane and stops on the first failure. The second
command builds all lanes after the cheap lane succeeds. Keep `--skip-push` for
the first Blueback pass; add buildcache destinations only after the install path
is trusted.

```bash
bash "$COMPOSER/scripts/spack-build" \
  --workspace "$WORKSPACE" \
  --spack-root "$SPACK_ROOT" \
  --lanes "gcc/serial-cmake" \
  --reports "$WORKSPACE/reports" \
  --skip-push \
  --fail-fast

bash "$COMPOSER/scripts/spack-build" \
  --workspace "$WORKSPACE" \
  --spack-root "$SPACK_ROOT" \
  --reports "$WORKSPACE/reports" \
  --skip-push \
  --fail-fast
```

`spack-build` runs per-lane `spack concretize --force`, `spack fetch -D`,
`spack install`, view regeneration, `spack verify libraries`, and manifest
verification. It writes lane logs and summary YAML under:

```text
$WORKSPACE/reports/
```

## Decisions this build relies on (beyond the generic runbook)

1. **Oracle diff (de-risks the render).** Your hand-built Kokkos on Blueback is
   ground truth. After `render`, diff the generated `cray-mpich` + ROCm externals
   and compiler entries against that working config *before* building. Include
   `configs/mpi/cray-mpich/toolchains.yaml` in that diff — it encodes the actual
   gcc+cray-mpich pairing (for example a spec-token-safe binding like
   `%gcc1330_craympich910`), not just which externals exist. Only build once
   they match — turns "does the pipeline work on real HW" into a checkable
   comparison.
2. **Modules are a split responsibility.** The renderer emits front-door
   compiler-init and lane modulefiles. Spack still generates package modulefiles
   (`spack -e <env> module tcl refresh`). For run #1, inspect the rendered
   lane prereqs and use Spack-generated package modules or the view.
3. **Module loading is a compiler-surface → lane → package chain.** The compiler
   surface module, `cse/GCC`, exposes the GCC foundation/core view
   and makes the GCC lane modules visible. The user then loads one lane module,
   e.g. `MPI` after loading `cse/GCC`; it prereqs the platform modules and prepends only that
   lane's package-module root. Do not expose all lane package roots at once from
   the init module.

## Definition of done (pipeline gates)

1. `cluster-inspector` profile reviews clean against Blueback.
2. `render` succeeds **and** diff-matches the known-good Kokkos config (oracle).
3. All four roots install across three lanes (cmake / osu + hdf5 / kokkos).
4. Rendered compiler-init and lane modulefiles exist. The compiler init module
   exposes only the selected foundation/core view plus lane modules, and after
   Spack package module generation each lane module exposes only that lane's
   packages.
5. **Runtime:** `cmake --version` (serial) · **`osu_bw D D`** device-to-device
   over `cray-mpich` (headline — proves rocm + GPU-aware MPI end-to-end) · a
   Kokkos test on the MI300A reporting the HIP/`gfx942` backend.

## Run #1 CPE note (2026-07-01)

The pulled profile captured Blueback's default CPE, which is now the **newest
(ROCm 7-era) release** that landed the week of 2026-06-22 — the known-good
Kokkos baseline was built on the previous CPE (cray-mpich 8.1.29 / ROCm 6 era).
Consequences:

- The oracle diff (Decisions §1) is **structural**, not version-exact: check
  flavor prefixes, toolchain binding shape, and external layout — the
  cray-mpich/ROCm/CCE versions will legitimately differ from the baseline.
- Do not mix components across the two CPEs. Cross-major ROCm/cray-mpich
  pairings are unsupported in both directions — rules and sources in
  `stack-planning/docs/cpe_rocm_compatibility_note_v1.md`.

## Blueback smoke baseline (2026-07-05)

The `codex/simplified-render-plan` branch produced a working first real-system
Blueback smoke path through:

```text
cluster-inspector -> profile.yaml -> stack-composer validate/render -> spack-build
```

The successful run used the latest observed Blueback platform set:

- `PrgEnv-gnu` with the Cray PE GNU compiler module;
- `cray-mpich` 9.1.0;
- ROCm 7.0.0 for `gfx942`;
- selected Cray platform runtime facts in the render plan;
- conservative rendering of network/runtime facts that need site package
  definitions.

The critical fixes that must be present before reproducing this run are:

1. Compiler providers are deduplicated by `(name, version)` so soft-linked
   compiler prefixes do not create multiple indistinguishable Spack externals.
2. Stack Composer renders the lane-selected Cray MPICH external only, while
   compiler binding lives in `toolchains.yaml`.
3. Cray MPICH package externals use plain provider specs such as
   `cray-mpich@9.1.0`; toolchain specs carry `%gcc@...`.
4. ROCm HIP externals use the ROCm toolkit root prefix proven by `bin/hipcc`,
   not a guessed `$ROCM_ROOT/hip` prefix.
5. Cray GTL, PMI, and PALS are reported as observed platform runtime facts but
   are not rendered as package externals unless a site package repo policy is
   provided.

Known acceptable smoke-run finding:

- `spack verify libraries` can report a Cray MPICH lane library issue involving
  external system/runtime libraries such as XPM/hugepages. This does not fail
  the blueprint purpose of the run. Record it, then model the relevant runtime
  package only if the managed stack needs to own it.

Retest rule: after any Cluster Inspector change, regenerate `system.frag.yaml`,
`login.frag.yaml`, `compute.frag.yaml`, and `profile.yaml`. Do not reuse an old
Blueback profile with a newly built inspector.

## GPU-aware MPI at runtime (run #1 workaround)

Nothing in the rendered stack links GTL at build time (upstream's mechanism is
per-package opt-in; OSU/Kokkos never opted in — see
`stack-planning/docs/cray_runtime_package_repo_note_v1.md`). Scope it right:

- The Kokkos HIP test needs **no** GTL — Kokkos makes no MPI calls. Only
  binaries passing GPU buffers to MPI need it (`osu_bw D D`, Kokkos-based apps).
- Sanctioned run #1 workaround for `osu_bw D D` (adjust version/paths to the
  render-plan report):

  ```bash
  export MPICH_GPU_SUPPORT_ENABLED=1
  export LD_PRELOAD=/opt/cray/pe/mpich/<version>/gtl/lib/libmpi_gtl_hsa.so
  ```

  Without the preload, `MPICH_GPU_SUPPORT_ENABLED=1` aborts at MPI_Init with
  "must be linked against the GTL library" — that error is the confirmation,
  not a new problem.
- **Diagnostic while on the box** (two minutes, settles whether a no-preload
  bridge exists). GTL injection is done by the craype driver (`cc`), which our
  stack never invokes — we expose gcc outright. The open question is whether
  the mpich-prefix `mpicc` (what `+wrappers` hands to dependent builds)
  consults the accel/GTL env or just execs gcc with a fixed link line:

  ```bash
  module load cray-mpich craype-accel-amd-gfx942
  env | grep -i gtl        # PE_MPICH_GTL_DIR/LIBS_amd_gfx942 present?
  mpicc -show              # execs craype cc, or gcc directly? gtl in link line?
  ```

  If `mpicc` routes through the craype driver, loading the accel module during
  Spack builds links GTL with no preload. If it execs gcc with a static line,
  the near-term options are the preload above or adding HPE's documented
  manual flags to the OSU spec
  (`$PE_MPICH_GTL_DIR_amd_gfx942 -lmpi_gtl_hsa`). Record the result either
  way; the PE_MPICH_GTL_* vars are also candidate inspector facts.

## Open / watch (carry back per runbook)

- GPU-aware cray-mpich currently requires the `LD_PRELOAD` workaround above.
  Eliminating the preload is a tracked follow-up (own package-repo GTL package
  or site-style package definitions; starting clue:
  https://github.com/llnl/benchpark/pull/1226 — not yet researched). Tracked in
  stack-composer `PHASE_STATUS.md` Deferred/open.

- Inspector-profile correctness on the real box: does it probe `cray-mpich`'s
  GPU-aware flavor, `gfx942`, and the CPU + APU node types correctly?
- Module exposure — record MODULEPATH / module-prereq behavior for rendered
  compiler-init/lane modules plus Spack-generated package modules.
- `node_types[0]` cpu asymmetry — confirm one portable `x86_64_v3` build is
  acceptable across all CPU partitions (else per-uarch native cpu fan-out is the
  follow-up model change).

## Science run (2026-07-10 — blueback-science, current procedure)

Everything below assumes `git pull` in stack-composer, stack-content, and
cluster-inspector first, and a **rebuilt inspector binary + composer pyz** —
stale artifacts caused two false failures in the container; assume nothing.

1. Re-probe with the current inspector (it now takes MPI versions from the
   driver's own report and rejects ride-along compiler modules). Verify:
   PASS schema + semantic; cray-mpich with per-compiler flavors; gcc from
   PrgEnv-gnu; rocm generations listed under gpu_toolkit_modules.
2. Validate + render `stacks/blueback-science/stack.yaml`. Expect four gcc
   lanes: core, serial, mpi-craympich, gpu-craympich-gfx942. Any skipped
   build prints its reason; GPU toolkit warnings mean the profile lost the
   rocm facts — stop and fix the fact sheet.
3. Oracle checks before building:
   - `configs/common/repos.yaml` pins builtin to the recipe generation from
     defaults (`spack-packages` tag v2026.06.0).
   - `configs/mpi/cray-mpich/{packages,toolchains}.yaml`: externals at real
     `/opt/cray/pe/mpich/...` flavor prefixes; toolchain names versioned.
   - `configs/gpu/amd-rocm/packages.yaml`: hip etc. buildable false at real
     /opt/rocm prefixes.
4. Concretize every lane before any install. Gates:
   - externals used, never fetched (cray-mpich, rocm, openssl);
   - serial lane lockfile has **zero MPI nodes** (grep the lock — purity is
     checked in the lock, never assumed);
   - each netcdf chain resolves exactly its pinned hdf5; two pythons,
     not four, in core.
5. Install lanes (independent, parallelizable), regenerate views/modules.
6. Front-door check (first real test of the naming): `module load cse/GCC`
   → core tools appear; then exactly one of Serial / MPI / GPU; loading a
   second lane must fail loudly. `module whatis` shows provenance.
   Lane-agnostic exposure (first on-system test): from the **MPI** lane,
   `module avail openblas` shows the serial-built openblas/netlib-lapack/
   gnuplot via the `<compiler>/shared` module root; loading one from
   MPI must resolve to the same install the Serial lane sees (one hash).
   boost is dual-build: each lane shows its own boost (~mpi vs +mpi) under
   the same clean name.
7. Runtime: GPU-aware MPI still uses the run #1 LD_PRELOAD workaround (see
   section above) until the GTL packaging work lands.
8. Commit the refreshed profile.yaml (and this file's findings) back to
   systems/blueback/.
