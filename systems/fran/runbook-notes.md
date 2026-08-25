# Fran system notes

Use `stack-planning/docs/runbook.md` for every common command and gate. This
file records only Fran-specific facts and open checks.

## System identity

- Platform: HPE Cray / Cray Programming Environment.
- Scheduler: confirm from the live profile and site commands.
- GPU builds: outside the Initial Conversion Trials.

## Provisional module snapshot (2026-08-12)

The screenshot shows the following baseline. Cluster Inspector must verify the
versions, prefixes, driver reports, and complete module chains before they are
used in values files.

- `PrgEnv-cray/8.6.0`
- `cce/20.0.0`
- `cray-mpich/9.0.1`
- a `libfabric/2.2...` module; exact version and prefix still require capture
- `craype-x86-genoa`
- `craype-network-ofi`
- `cray-libsci/25.09.0`

## Trial surfaces

| Surface | Compiler | MPI |
|---|---|---|
| Shared CSE | GCC 12.5.0 | platform Cray MPICH 9.0.1 GNU flavor |
| Platform | CCE 20.0.0 | platform Cray MPICH 9.0.1 CCE flavor |

Build the GCC 12.5.0 compiler producer inside each GCC-surface environment.
Matching hashes let the shared store reuse it across those environments. Cray
MPICH, libfabric, and Cray PMI remain platform externals.

Before Fran's first full concretization, synchronize Stack Content. The
generated preflight requires the GCC producer to request
`gcc@12.5.0+binutils`, requires downstream GCC groups to order and expose that
producer through `needs: [compiler]`, and binds their language/MPI virtuals
through the conditional `%cse_shared` toolchain. The lock verifier then
requires every downstream GCC-surface root to use that exact producer hash:

```bash
source "$CSE_OPERATOR_SESSION_FILE"
git -C "$CONTENT" pull --ff-only origin codex/simplified-render-plan
git -C "$CONTENT" log -1 --oneline
```

If Fran already has eight lockfiles, do not infer compliance from an older
`Lockfile verification passed` message. The earlier verifier checked shared
hashes but did not prove that the shared compiler producer had `+binutils` or
that every downstream GCC root reached that producer. Refresh only the
workspace controls first; this preserves every environment YAML file, lockfile,
cache, view, and installed prefix while installing the current verifier:

```bash
"$CSE_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/create-build-values.py"

"$CSE_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --composer "$STACK_COMPOSER" \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --values "$BUILD_VALUES" \
  --workspace "$BUILD_WORKSPACE"

cd "$BUILD_WORKSPACE"
./cse-build login verify
```

The same controls refresh also installs the common shared-generated-content
permission hook. The mutable misc/provider and concretization indexes use a
persistent builder-named partition below the shared restricted misc-cache root,
while the source cache remains shared. Before and after Spack, the launcher
restores and verifies the owner/group contract across Fran's workspace,
source/misc caches, views, modules, and file-backed build cache. This is the
required recovery if a second Fran builder reports a permission error on any
of those surfaces.

If both workspace-input and lockfile verification pass, keep all eight locks;
neither the GCC nor CCE surface needs another solve. If workspace-input
verification fails, the generated GCC environment YAML predates the corrected
producer/`needs`/toolchain inputs. If workspace-input verification passes but
lockfile verification reports the wrong GCC producer or downstream compiler
hash, only the four GCC locks are stale; preserve the output and use the
affected-lock recovery procedure in the main runbook. Do not reconcretize the
four CCE locks.

If Fran is still concretizing a workspace rendered before this correction and
does not yet have an accepted lock set, stop it with `Ctrl-C`, then replace the
unaccepted workspace and locks directly:

```bash
"$CSE_PYTHON" "$STACK_COMPOSER" init-workspace \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --catalog "$CATALOG" \
  --values "$BUILD_VALUES" \
  --output "$BUILD_WORKSPACE" \
  --overwrite

cd "$BUILD_WORKSPACE"
./cse-build login concretize
./cse-build login verify
```

This does not regenerate Fran's profile or static catalog. Use it only before
installation from the replaced locks has been accepted.

After workspace initialization, the common runbook's input check must pass for
all four GCC environments. After concretization,
`./cse-build login verify` must pass before fetching or installing. An older
GCC 12.5 prefix may coexist in the restricted trial store, but it is not
accepted when any current Fran root reaches it.

Use this reviewed Step 7 selection after the live catalog confirms the module
chains and flavor prefixes:

```bash
export CSE_SHARED_COMPILER_REF="gcc@12.5.0"
export CSE_SHARED_COMPILER_PUBLIC_NAME="init-GCC"
export CSE_SHARED_MPI_REF="cray-mpich@9.0.1"
export CSE_SHARED_MPI_SOURCE="external"
export CSE_PLATFORM_COMPILER_REF="cce@20.0.0"
export CSE_PLATFORM_COMPILER_PUBLIC_NAME="init-CCE"
export CSE_PLATFORM_MPI_REF="cray-mpich@9.0.1"
export CSE_PLATFORM_MPI_SOURCE="external"
export CSE_LOGIN_NODE_TYPE="login"
export CSE_COMPUTE_NODE_TYPE="cpu_compute"
export BUILD_JOBS="<approved-job-count>"
```

The values above assume the standard context keys `login` and `cpu_compute`.
Replace either value when Fran's catalog uses a different exact key.

## Required profile and catalog checks

- Capture the exact `ofi/cray/<baseline>` prefix paired with CCE 20.0.0.
- Capture the exact `ofi/gnu/<baseline>` prefix compatible with GCC 12.5.0.
- Capture the exact libfabric and Cray PMI versions and prefixes.
- Confirm the common static scope contains libfabric.
- Confirm each Cray MPICH static scope contains the matching Cray MPICH
  external and the inspected `cray-pmi` external.
- Reject cross-CPE combinations even when individual modules load.
- Do not manually preload `PrgEnv-gnu`, `PrgEnv-cray`, `gcc`, `cce`, or
  `cray-mpich` before `cse-build`. The workspace's external package records
  own the exact module chains.

## Diagnose an AOCC module omitted from the profile

Use this gate only when the live Fran module inventory exposes an AOCC module
but the merged profile does not contain the matching compiler provider. A Cray
MPICH or cray-libsci path ending in an AOCC flavor is compatibility evidence;
it is not proof that the compiler itself is installed or loadable. Do not add a
compiler provider from that product-tree suffix alone.

First update and rebuild Cluster Inspector, record the exact live AOCC module
inventory, and rerun only the system probe with a transcript:

```bash
source "$CSE_OPERATOR_SESSION_FILE"

git -C "$INSPECTOR" pull --ff-only origin codex/simplified-render-plan
make -C "$INSPECTOR" build

module -t avail aocc 2>&1 | tee "$PROBE_DIR/fran-aocc-module-inventory.txt"

HINTS_OPTION=()
if [ -f "$SYSTEM_DIR/inspector-hints.yaml" ]; then
  HINTS_OPTION=(--hints "$SYSTEM_DIR/inspector-hints.yaml")
fi

"$INSPECTOR/cluster-inspector" probe-system \
  --system "$SYSTEM_NAME" \
  "${HINTS_OPTION[@]}" \
  --record "$PROBE_DIR/system-probe-transcript.yaml" \
  --output "$PROBE_DIR/system.frag.yaml"

grep -nEi 'aocc|compiler_providers|verify_failed|candidate' \
  "$PROBE_DIR/system.frag.yaml" \
  "$PROBE_DIR/system-probe-transcript.yaml"
```

Review the exact module name, activation result, reported compiler version, and
prefix. If the current inspector emits the compiler provider, merge the new
system fragment with Fran's existing login and compute fragments and verify the
profile:

```bash
"$INSPECTOR/cluster-inspector" merge \
  --system-fragment "$PROBE_DIR/system.frag.yaml" \
  --node "$PROBE_DIR/login.frag.yaml" \
  --node "$PROBE_DIR/compute.frag.yaml" \
  --output "$PROBE_DIR/profile.yaml"

"$INSPECTOR/cluster-inspector" verify "$PROBE_DIR/profile.yaml"
```

If the exact reviewed AOCC module is loadable but was not enumerated, merge
that exact module name into `systems/fran/inspector-hints.yaml` rather than
guessing a compiler record. The relevant shape is:

```yaml
schema_version: 1
compilers:
  include:
    - <exact-reviewed-aocc-module-name>
```

Preserve any existing hint sections. Then rerun the system probe, merge, and
verification commands above. Both `PASS schema` and `PASS semantic` are
required. Regenerate the static catalog and workspace only after the reviewed
profile actually changes. If the transcript records a verification failure,
retain that evidence and fix the inspector or live module issue; do not force
the failed candidate into the profile.

## Recover profile verification after an empty fabric-driver inventory

Fran may directly expose a non-Ethernet CXI fabric while providing no separate
queryable driver package, module version, or driver prefix. In that case
Cluster Inspector records the observed fabric and retains `drivers: []`. That
profile is valid; the inspector must not invent a driver or reject the direct
device observation.

If schema validation passes but an older inspector reports `non-ethernet fabric
must include at least one fabric driver`, update and rebuild only Cluster
Inspector, then verify the existing merged profile again. The system and node
probes and the static catalog do not need to be regenerated for this validator
correction:

```bash
source "$CSE_OPERATOR_SESSION_FILE"

git -C "$INSPECTOR" pull --ff-only origin codex/simplified-render-plan
make -C "$INSPECTOR" build
"$INSPECTOR/cluster-inspector" verify "$PROBE_DIR/profile.yaml"
```

Both `PASS schema` and `PASS semantic` are required before rendering the Fran
static catalog.

## Restricted-network source transfer

Do not move individual Spack stage directories or source archives by hand. If
Fran's login and compute nodes cannot reach every source, create one cumulative
Spack source mirror on a connected staging system and copy it into Fran's
generated `config:source_cache`.

Use the sequence below after all eight Fran environments have been concretized
and `./cse-build login verify` passes. The original locked workspace remains on
Fran.
Only a temporary copy goes to the connected system, and only the resulting
source bundle comes back. Do not copy the connected system's workspace back
over the original Fran workspace.

### A. Package the locked workspace on Fran

Source Fran's saved operator session, then create a private transfer area under
the site-provided work filesystem. `FRAN_TRANSFER_ROOT` is the one path that
must be carried into the transfer commands on the other system.

```bash
source "$HOME/STACK_TESTING/operator-sessions/fran/fran-trial-001/activate.sh"

cd "$BUILD_WORKSPACE"
./cse-build login verify

export FRAN_TRANSFER_ROOT="$WORKDIR/$USER/cse-fran-transfer/$TRIAL_RELEASE"
export FRAN_WORKSPACE_ARCHIVE="$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz"
export FRAN_WORKSPACE_DIGEST="$FRAN_WORKSPACE_ARCHIVE.sha256"

umask 0077
install -d -m 0700 "$FRAN_TRANSFER_ROOT"
tar -C "$(dirname "$BUILD_WORKSPACE")" -czf "$FRAN_WORKSPACE_ARCHIVE" \
  "$(basename "$BUILD_WORKSPACE")"
(
  cd "$FRAN_TRANSFER_ROOT"
  sha256sum "$(basename "$FRAN_WORKSPACE_ARCHIVE")" \
    > "$(basename "$FRAN_WORKSPACE_DIGEST")"
  sha256sum -c "$(basename "$FRAN_WORKSPACE_DIGEST")"
)

printf 'FRAN_TRANSFER_ROOT=%s\n' "$FRAN_TRANSFER_ROOT"
printf 'FRAN_WORKSPACE_ARCHIVE=%s\n' "$FRAN_WORKSPACE_ARCHIVE"
printf 'FRAN_WORKSPACE_DIGEST=%s\n' "$FRAN_WORKSPACE_DIGEST"
```

The archive contains the complete workspace so relative `include::` paths from
each environment to `configs/` and the catalog snapshot remain valid. It does
not contain the restricted Spack install tree, views, modules, build stages, or
build cache.

### B. Copy and unpack the workspace on a connected system

First create the receiving directory on the connected staging system. Its path
is temporary per-user work space; it is not a CSE tools root, package install
tree, or build cache.

```bash
: "${WORKDIR:?WORKDIR must be set on the connected system}"
: "${USER:?USER must be set on the connected system}"

export TRIAL_RELEASE="fran-trial-001"
export CONNECTED_TRANSFER_ROOT="$WORKDIR/$USER/cse-fran-transfer/$TRIAL_RELEASE"
export CONNECTED_WORKSPACE_ARCHIVE="$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz"
export CONNECTED_WORKSPACE_DIGEST="$CONNECTED_WORKSPACE_ARCHIVE.sha256"
export FRAN_WORKSPACE="$CONNECTED_TRANSFER_ROOT/$TRIAL_RELEASE"

umask 0077
install -d -m 0700 "$CONNECTED_TRANSFER_ROOT"
printf 'CONNECTED_TRANSFER_ROOT=%s\n' "$CONNECTED_TRANSFER_ROOT"
```

Use one transfer route, not both.

For a direct connection, stay on the connected system, fill in the Fran login
endpoint, paste the exact `FRAN_TRANSFER_ROOT` printed on Fran, and pull the two
files:

```bash
export FRAN_SSH="<fran-user>@<fran-login-host>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"

rsync -av --partial --progress \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
  "$CONNECTED_WORKSPACE_ARCHIVE"
rsync -av --partial --progress \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz.sha256" \
  "$CONNECTED_WORKSPACE_DIGEST"
```

When the connected system cannot reach Fran directly, run the following on an
approved relay workstation. Fill in both SSH endpoints, paste the exact Fran
and connected transfer roots printed by the earlier blocks, and keep the relay
directory private:

```bash
export TRIAL_RELEASE="fran-trial-001"
export FRAN_SSH="<fran-user>@<fran-login-host>"
export CONNECTED_SSH="<connected-user>@<connected-login-host>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"
export CONNECTED_TRANSFER_ROOT="<exact-CONNECTED_TRANSFER_ROOT-printed-on-connected-system>"
export RELAY_TRANSFER_ROOT="$HOME/cse-fran-relay/$TRIAL_RELEASE"

umask 0077
install -d -m 0700 "$RELAY_TRANSFER_ROOT"
rsync -av --partial --progress \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
  "$RELAY_TRANSFER_ROOT/"
rsync -av --partial --progress \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz.sha256" \
  "$RELAY_TRANSFER_ROOT/"

(
  cd "$RELAY_TRANSFER_ROOT"
  sha256sum -c "${TRIAL_RELEASE}-workspace.tar.gz.sha256"
)

ssh "$CONNECTED_SSH" \
  "umask 0077 && install -d -m 0700 '$CONNECTED_TRANSFER_ROOT'"
rsync -av --partial --progress \
  "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
  "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/"
rsync -av --partial --progress \
  "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz.sha256" \
  "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/"
```

After either route, return to the connected system. Restore the variables from
the first block in this subsection if this is a new shell, then verify and
unpack the transferred workspace:

```bash
test -f "$CONNECTED_WORKSPACE_ARCHIVE"
test -f "$CONNECTED_WORKSPACE_DIGEST"

(
  cd "$CONNECTED_TRANSFER_ROOT"
  sha256sum -c "$(basename "$CONNECTED_WORKSPACE_DIGEST")"
)
test ! -e "$FRAN_WORKSPACE"
tar -C "$CONNECTED_TRANSFER_ROOT" -xzf "$CONNECTED_WORKSPACE_ARCHIVE"
test -f "$FRAN_WORKSPACE/workspace-manifest.yaml"
test -x "$FRAN_WORKSPACE/cse-build"

FRAN_LOCK_COUNT="$(
  find "$FRAN_WORKSPACE/environments" \
    -mindepth 3 -maxdepth 3 -type f -name spack.lock -print |
    tee /dev/stderr |
    wc -l |
    tr -d '[:space:]'
)"
test "$FRAN_LOCK_COUNT" -eq 8
```

### C. Create the cumulative source bundle on the connected system

Activate the same pinned Spack version, tag, commit, and package-recipe state
used for the trial. A matching CPU is not required because this operation reads
the locks and fetches source artifacts; it does not concretize or build them.

```bash
export FRAN_SOURCE_BUNDLE="$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror"
export CONNECTED_FETCH_STAGE="$CONNECTED_TRANSFER_ROOT/fetch-stage"
export CONNECTED_FETCH_CACHE="$CONNECTED_TRANSFER_ROOT/download-cache"
export SPACK_USER_CACHE_PATH="$CONNECTED_TRANSFER_ROOT/spack-user-cache"
export SPACK_DISABLE_LOCAL_CONFIG=true
export SPACK_VERSION="1.2.2"
export SPACK_TAG="v$SPACK_VERSION"
export SPACK_COMMIT="3e19345b6e12f5ff1b874f4059622fc6a1fd804a"
export SPACK_ROOT="<absolute-path-to-matching-pinned-spack-checkout>"

source "$SPACK_ROOT/share/spack/setup-env.sh"
SPACK_VERSION_OUTPUT="$(spack --version)"
test "${SPACK_VERSION_OUTPUT%% *}" = "$SPACK_VERSION"
test "$(git -C "$SPACK_ROOT" rev-parse HEAD)" = "$SPACK_COMMIT"
test "$(git -C "$SPACK_ROOT" rev-parse "${SPACK_TAG}^{commit}")" = \
  "$SPACK_COMMIT"
test -z "$(git -C "$SPACK_ROOT" status --porcelain --untracked-files=all)"

mkdir -p \
  "$FRAN_SOURCE_BUNDLE" \
  "$CONNECTED_FETCH_STAGE" \
  "$CONNECTED_FETCH_CACHE" \
  "$SPACK_USER_CACHE_PATH"

FRAN_ENVIRONMENT_COUNT=0
for environment_dir in "$FRAN_WORKSPACE"/environments/*/*; do
  test -f "$environment_dir/spack.lock" || {
    echo "missing lockfile: $environment_dir/spack.lock" >&2
    exit 1
  }
  spack \
    -c "config:build_stage:[$CONNECTED_FETCH_STAGE]" \
    -c "config:source_cache:$CONNECTED_FETCH_CACHE" \
    -e "$environment_dir" \
    mirror create -a -d "$FRAN_SOURCE_BUNDLE" || exit 1
  FRAN_ENVIRONMENT_COUNT=$((FRAN_ENVIRONMENT_COUNT + 1))
done
test "$FRAN_ENVIRONMENT_COUNT" -eq 8
```

The command may be rerun against the same bundle; Spack retains existing
archives and adds missing ones. Review any skipped or failed fetch, especially
license-restricted sources. Do not use `--private` unless storage and transfer
of those sources has been explicitly approved.

Package the completed source bundle and record its digest:

```bash
export FRAN_BUNDLE_ARCHIVE="$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar"
export FRAN_BUNDLE_DIGEST="$FRAN_BUNDLE_ARCHIVE.sha256"

tar -C "$CONNECTED_TRANSFER_ROOT" -cf "$FRAN_BUNDLE_ARCHIVE" \
  "$(basename "$FRAN_SOURCE_BUNDLE")"
(
  cd "$CONNECTED_TRANSFER_ROOT"
  sha256sum "$(basename "$FRAN_BUNDLE_ARCHIVE")" \
    > "$(basename "$FRAN_BUNDLE_DIGEST")"
  sha256sum -c "$(basename "$FRAN_BUNDLE_DIGEST")"
)

printf 'FRAN_BUNDLE_ARCHIVE=%s\n' "$FRAN_BUNDLE_ARCHIVE"
printf 'FRAN_BUNDLE_DIGEST=%s\n' "$FRAN_BUNDLE_DIGEST"
```

Source archives are normally already compressed, so the returned bundle uses
an uncompressed tar container. Use one return route, not both.

For a direct connection, stay on the connected system, restore the Fran
endpoint and exact Fran transfer root if necessary, and push both files:

```bash
export FRAN_SSH="<fran-user>@<fran-login-host>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"

rsync -av --partial --progress \
  "$FRAN_BUNDLE_ARCHIVE" \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
rsync -av --partial --progress \
  "$FRAN_BUNDLE_DIGEST" \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
```

When a relay is required, run the following on the approved relay workstation.
It pulls the finished bundle from the connected system, verifies it, and then
pushes the same two files to Fran:

```bash
export TRIAL_RELEASE="fran-trial-001"
export CONNECTED_SSH="<connected-user>@<connected-login-host>"
export FRAN_SSH="<fran-user>@<fran-login-host>"
export CONNECTED_TRANSFER_ROOT="<exact-CONNECTED_TRANSFER_ROOT-printed-on-connected-system>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"
export RELAY_TRANSFER_ROOT="$HOME/cse-fran-relay/$TRIAL_RELEASE"

umask 0077
install -d -m 0700 "$RELAY_TRANSFER_ROOT"
rsync -av --partial --progress \
  "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar" \
  "$RELAY_TRANSFER_ROOT/"
rsync -av --partial --progress \
  "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar.sha256" \
  "$RELAY_TRANSFER_ROOT/"

(
  cd "$RELAY_TRANSFER_ROOT"
  sha256sum -c "${TRIAL_RELEASE}-source-mirror.tar.sha256"
)

rsync -av --partial --progress \
  "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar" \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
rsync -av --partial --progress \
  "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar.sha256" \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
```

If `rsync` is unavailable on one approved transfer leg, use `scp -p` for that
same source file and destination directory, then run the same SHA-256 check at
the receiving endpoint. Do not return the copied workspace archive as a
replacement for Fran's original workspace.

### D. Install the source bundle into Fran's generated source cache

Back on Fran, source the saved operator session again and verify the returned
bundle before extracting it:

```bash
source "$HOME/STACK_TESTING/operator-sessions/fran/fran-trial-001/activate.sh"

export FRAN_TRANSFER_ROOT="$WORKDIR/$USER/cse-fran-transfer/$TRIAL_RELEASE"
export FRAN_BUNDLE_ARCHIVE="$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar"
export FRAN_BUNDLE_DIGEST="$FRAN_BUNDLE_ARCHIVE.sha256"
export FRAN_SOURCE_BUNDLE="$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror"

(
  cd "$FRAN_TRANSFER_ROOT"
  sha256sum -c "$(basename "$FRAN_BUNDLE_DIGEST")"
)
test ! -e "$FRAN_SOURCE_BUNDLE"
tar -C "$FRAN_TRANSFER_ROOT" -xf "$FRAN_BUNDLE_ARCHIVE"
test -d "$FRAN_SOURCE_BUNDLE"
```

Read the source-cache destination through an actual generated environment and
confirm that it is the restricted cache selected for this operator session.
Do not type or infer the destination path independently:

```bash
verify_spack_tool_root
source "$SPACK_ROOT/share/spack/setup-env.sh"
source "$BUILD_WORKSPACE/env/select-build-context.sh"
cse_select_build_context login
source "$BUILD_WORKSPACE/env/setup-build-env.sh"

export FRAN_REFERENCE_ENV="$BUILD_WORKSPACE/environments/$SHARED_COMPILER_NAME/core"
export FRAN_SOURCE_CACHE="$(
  spack -e "$FRAN_REFERENCE_ENV" python -c \
    'import spack.config; print(spack.config.get("config:source_cache"))'
)"

test -n "$FRAN_SOURCE_CACHE"
test "$FRAN_SOURCE_CACHE" = "$CSE_RESTRICTED_ROOT/cache/source"
printf 'FRAN_SOURCE_CACHE=%s\n' "$FRAN_SOURCE_CACHE"
```

Merge only the source mirror's contents into that generated cache while
preserving the CSE group/setgid policy. Spack's mirror and `source_cache` use
the same cache-relative archive layout, so the trailing slashes below are
intentional:

```bash
umask 0007
install -d -m 2770 -g "$CSE_GROUP" "$FRAN_SOURCE_CACHE"
rsync -a --no-owner --no-group --checksum \
  "$FRAN_SOURCE_BUNDLE/" "$FRAN_SOURCE_CACHE/"

chgrp -R "$CSE_GROUP" "$FRAN_SOURCE_CACHE"
find "$FRAN_SOURCE_CACHE" -type d -exec chmod g+rws,o-rwx {} +
find "$FRAN_SOURCE_CACHE" -type f -exec chmod g+rw,o-rwx {} +
```

Finally, use the original Fran workspace and its existing lockfiles to prove
that every environment can fetch its complete dependency closure from the
populated cache. This command may attempt an outbound URL only when an artifact
is still missing; on Fran that attempt fails and identifies the gap to add to
the bundle.

```bash
cd "$BUILD_WORKSPACE"
./cse-build login verify
./cse-build login fetch
```

Gate: `./cse-build login fetch` succeeds for all eight original Fran
environments.
Retain both transfer archives and their digest files until the first complete
Fran build succeeds; they are recovery evidence for the same locked release.
The source bundle is not the signed CSE binary build cache and does not change
any `spack.lock`. If the Spack runtime itself must be bootstrapped without
network access, prepare a separate Spack bootstrap mirror; do not mix bootstrap
artifacts into this source bundle.

## Current run record

- Profile release/date:
- Catalog release/path:
- Restricted build values/workspace:
- Selected CPE/module chain:
- Selected CCE and Cray MPICH flavor:
- Selected GCC and Cray MPICH flavor:
- Selected libfabric and Cray PMI:
- CSE roots and build stage:
- Work-tree review status:
- Exact next command:
