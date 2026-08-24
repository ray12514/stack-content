# Local Smoke Fixture Notes

This file records the reusable local/generic-Linux smoke fixture. It is not the
per-system notes template. For a new target system, copy
`systems/_template/runbook-notes.md`, then use
`stack-planning/docs/runbook.md` for the common procedure.

The goal is to prove the full-render path on Cray, generic
Linux/Penguin-style systems, and future vendor platforms:

```text
cluster-inspector -> profile.yaml -> stack-composer validate/render -> spack-build
```

This fixture does not exercise the Initial Conversion Trials
`render-static`/`init-workspace` path. Use the canonical trial runbook and the
matching system notes for that workflow.

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

Create the per-system notes file from the system-notes template. Do not copy
this smoke fixture directory into a live system directory.

```bash
mkdir -p "$CONTENT/systems"
mkdir -p "$SYSTEM_DIR"
if [ ! -f "$SYSTEM_DIR/runbook-notes.md" ]; then
  cp "$CONTENT/systems/_template/runbook-notes.md" \
    "$SYSTEM_DIR/runbook-notes.md"
fi
```

Build local tools:

```bash
cd "$INSPECTOR"
make clean
make build

cd "$COMPOSER"
export CSE_BOOTSTRAP_PYTHON="<absolute-path-to-reviewed-python-3.9-or-newer>"
test -x "$CSE_BOOTSTRAP_PYTHON"
"$CSE_BOOTSTRAP_PYTHON" -c \
  'import sys; assert sys.version_info >= (3, 9), sys.version'
"$CSE_BOOTSTRAP_PYTHON" -m venv .venv
export CSE_PYTHON="$COMPOSER/.venv/bin/python"
"$CSE_PYTHON" -m pip install --upgrade \
  pip \
  "setuptools>=77" \
  "wheel>=0.44,<1" \
  "build>=1.2,<2"
"$CSE_PYTHON" -m pip install -e '.[dev]'
PYTHON="$CSE_PYTHON" bash scripts/build-pyz.sh

export STACK_COMPOSER="$COMPOSER/dist/stack-composer.pyz"
"$CSE_PYTHON" "$STACK_COMPOSER" --help >/dev/null
```

Source the Spack setup for the target test and verify the pinned version:

```bash
source /path/to/use-spack.sh
: "${SPACK_ROOT:?SPACK_ROOT is not set; source use-spack.sh first}"
spack --version
```

Use the approved Spack 1.2.2 tag and commit for the current control run. Treat
any different Spack release as an explicit adoption test until its smoke matrix
passes.

## Stage 1 — Profile fragments

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

If a profile fact is wrong, fix Cluster Inspector or the reviewed system hint
and regenerate the fragment and profile. Do not hand-edit `profile.yaml` or
render from a diagnostic copy.

## Stage 2 — Deployment input

Create `deployment.yaml` from the selected test roots. These are installer-owned
paths, not discovered facts.

```bash
export STACK_GROUP="${STACK_GROUP:-cse}"

cat > "$SYSTEM_DIR/deployment.yaml" <<EOF
schema_version: 1
system: $SYSTEM_NAME
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

"$CSE_PYTHON" "$STACK_COMPOSER" validate \
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

"$CSE_PYTHON" "$STACK_COMPOSER" render \
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
