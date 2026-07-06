# Smoke Runbook Notes

Per-system instance of `stack-planning/docs/runbook.md` for real-system smoke
tests. Use this directory as the starting point for a new target system, then
copy it to the actual system name.

The goal is to prove the common path on Cray, generic Linux/Penguin-style
systems, and future vendor platforms:

```text
cluster-inspector -> profile.yaml -> stack-composer validate/render -> spack-build
```

Platform-specific facts should come from the generated profile and the
stack/default policy. The runbook should not require a Blueback-style directory
layout or any preexisting project checkouts on the target system.

## Stage 0 — Create the stack test area

Start from a fresh shell on the target system. The only assumption is that you
can create a working directory, clone the project repos, and source a supported
Spack install.

Set these once per shell. Replace `<system-name>` with the actual short system
name before running anything else.

```bash
export WORK_ROOT="$HOME/STACK_TESTING"
export STACK_BRANCH="codex/simplified-render-plan"
export SYSTEM_NAME="<system-name>"

export CONTENT="$WORK_ROOT/stack-content"
export COMPOSER="$WORK_ROOT/stack-composer"
export INSPECTOR="$WORK_ROOT/cluster-inspector"
export PLANNING="$WORK_ROOT/stack-planning"
export SYSTEM_DIR="$CONTENT/systems/$SYSTEM_NAME"
export RENDER_ROOT="$WORK_ROOT/rendered"

mkdir -p "$WORK_ROOT"
cd "$WORK_ROOT"
```

The working tree should end up in this shape:

```text
~/STACK_TESTING/
  cluster-inspector/
  stack-composer/
  stack-content/
  stack-planning/          # optional docs checkout
  rendered/                # generated; do not commit
```

Clone the repos if this is the first run on the system. Use HTTPS on HPC
systems unless SSH keys are already configured there; the SSH-style
`git@github.com:...` form will fail with `Permission denied (publickey)` on many
login nodes. During alpha, these URLs may be GitHub. After migration, use the
internal GitLab HTTPS URLs with the same local directory names.

```bash
if [ ! -d "$INSPECTOR/.git" ]; then
  git clone https://github.com/ray12514/cluster-inspector.git "$INSPECTOR"
fi

if [ ! -d "$COMPOSER/.git" ]; then
  git clone https://github.com/ray12514/stack-composer.git "$COMPOSER"
fi

if [ ! -d "$CONTENT/.git" ]; then
  git clone https://github.com/ray12514/stack-content.git "$CONTENT"
fi

if [ ! -d "$PLANNING/.git" ]; then
  git clone https://github.com/ray12514/stack-planning.git "$PLANNING"
fi
```

Check out the test branch. Use `git -C` with explicit repo paths instead of
running bare `git` from `$WORK_ROOT`; on HPC systems, `$HOME`, project storage,
and cloned repos may cross filesystem boundaries, which can trigger Git
discovery errors.

```bash
for repo in cluster-inspector stack-composer stack-content stack-planning; do
  git -C "$WORK_ROOT/$repo" fetch origin
  git -C "$WORK_ROOT/$repo" switch "$STACK_BRANCH"
  git -C "$WORK_ROOT/$repo" pull --ff-only
done
```

Bootstrap the per-system notes directory from this smoke template. After this
command, work from `$SYSTEM_DIR/runbook-notes.md` for the actual system.

```bash
mkdir -p "$CONTENT/systems"
if [ "$SYSTEM_NAME" != "smoke" ] && [ ! -d "$SYSTEM_DIR" ]; then
  cp -R "$CONTENT/systems/smoke" "$SYSTEM_DIR"
fi
```

Build local tools:

```bash
cd "$INSPECTOR"
make clean
make build

cd "$COMPOSER"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
bash scripts/build-pyz.sh

export STACK_COMPOSER="$COMPOSER/dist/stack-composer.pyz"
```

Source the Spack setup for the target test and verify the pinned version:

```bash
source /path/to/use-spack.sh
: "${SPACK_ROOT:?SPACK_ROOT is not set; source use-spack.sh first}"
spack --version
```

Use Spack 1.1.1 or newer for the control run. Treat a new Spack minor release
as an explicit adoption test until its smoke matrix passes.

## Stage 1 — Manual profile fragments

Ensure the system directory exists:

```bash
mkdir -p "$SYSTEM_DIR"
```

On the login node:

```bash
cd "$INSPECTOR"

./cluster-inspector probe-system \
  --system "$SYSTEM_NAME" \
  --output "$SYSTEM_DIR/system.frag.yaml"

./cluster-inspector probe-node \
  --node-type login \
  --role both \
  --runner this \
  --output "$SYSTEM_DIR/login.frag.yaml"
```

On a representative compute/runtime node, using the same repo path:

```bash
cd "$INSPECTOR"

./cluster-inspector probe-node \
  --node-type compute \
  --role runtime \
  --runner this \
  --output "$SYSTEM_DIR/compute.frag.yaml"
```

If build nodes differ from runtime nodes, run this on a representative build
node:

```bash
cd "$INSPECTOR"

./cluster-inspector probe-node \
  --node-type build \
  --role build_host \
  --runner this \
  --output "$SYSTEM_DIR/build.frag.yaml"
```

Back on the login node, merge the fragments. Omit `build.frag.yaml` if compute
is also the build host. For the common case where login and compute are enough,
use:

```bash
cd "$INSPECTOR"

./cluster-inspector merge \
  --system-fragment "$SYSTEM_DIR/system.frag.yaml" \
  --node "$SYSTEM_DIR/login.frag.yaml" \
  --node "$SYSTEM_DIR/compute.frag.yaml" \
  --output "$SYSTEM_DIR/profile.yaml"

./cluster-inspector verify "$SYSTEM_DIR/profile.yaml"
```

If the site has a distinct build node fragment, include it:

```bash
./cluster-inspector merge \
  --system-fragment "$SYSTEM_DIR/system.frag.yaml" \
  --node "$SYSTEM_DIR/login.frag.yaml" \
  --node "$SYSTEM_DIR/compute.frag.yaml" \
  --node "$SYSTEM_DIR/build.frag.yaml" \
  --output "$SYSTEM_DIR/profile.yaml"
```

Review `profile.yaml` before rendering:

- compiler providers: names, exact versions, prefixes, modules, and
  `provider_family`;
- MPI providers: site/system/platform classification, prefixes, modules, and
  compiler compatibility if discoverable;
- GPU toolkit modules if the system has NVIDIA or AMD GPU partitions;
- system externals such as OpenSSL, curl, libfabric, UCX, CUDA/ROCm components;
- node CPU target and build-stage candidates.

If a profile fact is wrong, fix Cluster Inspector or the discovery policy. Do
not hand-edit `profile.yaml` except to unblock a test while recording the bug.

## Stage 2 — Deployment input

Create `deployment.yaml` from the selected test roots. These are installer-owned
paths, not discovered facts.

```bash
cat > "$SYSTEM_DIR/deployment.yaml" <<EOF
schema_version: 1
system: $SYSTEM_NAME

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

Create the directories named by the deployment file for the first smoke run:

```bash
mkdir -p \
  "$WORK_ROOT/install/spack/opt" \
  "$WORK_ROOT/stage/spack-stage" \
  "$WORK_ROOT/cache/spack/source-cache" \
  "$WORK_ROOT/cache/misc" \
  "$WORK_ROOT/views" \
  "$WORK_ROOT/modules" \
  "$WORK_ROOT/buildcache/payload" \
  "$RENDER_ROOT"
```

For the first smoke, use the existing `stacks/mpi-smoke/stack.yaml` if MPI is
available. If no external MPI should be used, use or create a serial-only smoke
stack and record that decision.

## Stage 3 — Validate and render

```bash
export PROFILE="$SYSTEM_DIR/profile.yaml"
export STACK="$CONTENT/stacks/mpi-smoke/stack.yaml"

python "$STACK_COMPOSER" validate \
  --profile "$PROFILE" \
  --deployment "$SYSTEM_DIR/deployment.yaml" \
  --stack "$STACK" \
  --templates "$CONTENT/templates" \
  --package-sets "$CONTENT/package-sets" \
  --package-repos "$CONTENT/package-repos" \
  --report "$SYSTEM_DIR/validate-report.yaml"
```

Render only after validation passes:

```bash
export RELEASE="$SYSTEM_NAME-smoke-001"

python "$STACK_COMPOSER" render \
  --profile "$PROFILE" \
  --deployment "$SYSTEM_DIR/deployment.yaml" \
  --stack "$STACK" \
  --templates "$CONTENT/templates" \
  --package-sets "$CONTENT/package-sets" \
  --package-repos "$CONTENT/package-repos" \
  --output-root "$RENDER_ROOT" \
  --release "$RELEASE" \
  --rendered-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --source-repo "local-$SYSTEM_NAME-smoke" \
  --source-commit "$(git -C "$CONTENT" rev-parse --short=12 HEAD)" \
  --source-dirty
```

Inspect:

```bash
export WORKSPACE="$RENDER_ROOT/$SYSTEM_NAME/mpi-smoke/$RELEASE"

sed -n '1,220p' "$WORKSPACE/reports/render-plan.yaml"
find "$WORKSPACE/environments" -name spack.yaml -print | sort
find "$WORKSPACE/configs" -name packages.yaml -print | sort
find "$WORKSPACE/modulefiles" -type f | sort
```

On a non-Cray system, check specifically that no Cray-only scopes or packages
are selected:

```bash
grep -R "vendor/cray\\|cray-mpich\\|cray-gtl\\|cray-libsci" "$WORKSPACE" -n && false || true
```

## Stage 4 — Build

Build one cheap lane first, then all lanes:

```bash
bash "$COMPOSER/scripts/spack-build" \
  --workspace "$WORKSPACE" \
  --spack-root "$SPACK_ROOT" \
  --lanes "<compiler>/<lane>" \
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

`spack-build` writes per-step logs under `$WORKSPACE/reports`. To watch a long
install from another shell:

```bash
tail -f "$WORKSPACE/reports/<compiler>/<lane>/install.log"
```

## Definition of done

1. Manual fragment collection produces a verified `profile.yaml`.
2. `stack-composer validate` and `render` succeed.
3. Render plan selects the expected platform scopes and runtime packages.
4. One cheap lane concretizes and installs.
5. The full smoke stack builds or fails with a recorded system/package issue,
   not a missing profile/render contract.
