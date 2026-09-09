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
cache, view, generated package module, and installed prefix while installing
the current verifier and replacing only the generated workspace
`modulefiles/` and `presentation/` control trees:

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

## Restricted-network source transfer through Blueback

Do not move individual Spack stage directories or source archives by hand. If
Fran's login and compute nodes cannot reach every source, create one cumulative
Spack source mirror on a connected staging system and copy it into Fran's
generated `config:source_cache`. Blueback is the designated connected
acquisition system for this transfer. Its login endpoint, usable per-user work
path, and whether it can reach Fran directly are live operator inputs; keep the
placeholders below until those facts have been checked in the transfer shell.

Use the sequence below after all eight Fran environments have been concretized
and `./cse-build login verify` passes. The original locked workspace remains on
Fran.
Only a temporary copy goes to the connected system, and only the resulting
source bundle comes back. Do not copy the connected system's workspace back
over the original Fran workspace.

| Step | Run on | Result |
|---|---|---|
| A | Fran | Package a copy of Fran's locked workspace and record the eight lockfile digests |
| B | Blueback, or the approved relay | Transfer that copy from Fran to Blueback and verify it |
| C | Blueback | Fetch the source tarballs, resources and patches for all eight Fran lockfiles into one source mirror |
| D | Blueback, or the approved relay | Package and transfer the source mirror back to Fran |
| E | Fran | Verify the return, populate Fran's source cache and resume the original locked workspace |

Throughout this procedure, `CONNECTED_*` paths and `CONNECTED_SSH` refer to
Blueback. Fran is the restricted-network build system. Blueback supplies the
network access for source acquisition; no Fran package build runs on Blueback.

### Interactive-shell setup and transfer errors

Run these blocks in Bash, one block at a time. Check the printed status before
continuing: a nonzero status means stop at that step. The commands deliberately
disable `errexit` and `pipefail` in the interactive shell; `set -e` and `pipefail` belong only inside
the parenthesized step. A failed step stops its remaining commands and prints
its status while leaving the terminal open. Do not paste the whole procedure
at once or enable `set -e` in the parent shell.

If you used an earlier version of these instructions, run this now, before
retrying a transfer:

```bash
set +e
set +o pipefail
```

The earlier instructions enabled `set -e` in the interactive shell. An rsync
error could therefore exit that shell and close its terminal/session. That
explains a shell exit, but does not by itself establish the cause of an entire
remote desktop disconnect. A failing transfer still needs diagnosis from its
error output; being outside `tmux` is not an rsync authentication error.

`WORKDIR` is already the site's per-user absolute path. Do not append `$USER`.
For an in-progress transfer made with the older instructions, keep its exact
existing transfer roots, including any duplicated username component. Substitute
those paths before deriving the archive paths. The setup blocks preserve an
already-set transfer root and use the new default only when it is unset. When
starting a different release, explicitly set its intended transfer root before
running the setup block. Changing a default does not move existing files.
Record both roots for reconnects.

Use the same SSH host alias and connection options that work for `scp` on the
same route and from the same initiating host. A host alias may already set the
login user; add `user@` only if that connection requires it. The examples use
`-e ssh` to explicitly select SSH. This does not supply credentials or enable a
remote command that the account is not permitted to run.

### A. Package the locked workspace on Fran

Source Fran's saved operator session, then create a private transfer area under
the site-provided work filesystem. `FRAN_TRANSFER_ROOT` is the one path that
must be carried into the transfer commands on the other system.

```bash
set +e
set +o pipefail
source "$HOME/STACK_TESTING/operator-sessions/fran/fran-trial-001/activate.sh"
session_status=$?
printf 'session activation status: %s (continue only if 0)\n' "$session_status"
```

Continue only if activation succeeded. Then run:

```bash
set +e
set +o pipefail
export FRAN_TRANSFER_ROOT="${FRAN_TRANSFER_ROOT:-$WORKDIR/cse-fran-transfer/$TRIAL_RELEASE}"
export FRAN_WORKSPACE_ARCHIVE="$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz"
export FRAN_WORKSPACE_DIGEST="$FRAN_WORKSPACE_ARCHIVE.sha256"
export FRAN_LOCK_DIGESTS="$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256"

(
  set -e
  set -o pipefail
  : "${WORKDIR:?WORKDIR must be set on Fran}"
  cd "$BUILD_WORKSPACE"
  ./cse-build login verify

  umask 0077
  install -d -m 0700 "$FRAN_TRANSFER_ROOT"
  (
    cd "$BUILD_WORKSPACE"
    find environments -mindepth 3 -maxdepth 3 -type f -name spack.lock -print0 |
      sort -z |
      xargs -0 sha256sum > "$FRAN_LOCK_DIGESTS"
  )
  test "$(wc -l < "$FRAN_LOCK_DIGESTS" | tr -d '[:space:]')" -eq 8
  tar -C "$(dirname "$BUILD_WORKSPACE")" -czf "$FRAN_WORKSPACE_ARCHIVE" \
    "$(basename "$BUILD_WORKSPACE")"
  (
    cd "$FRAN_TRANSFER_ROOT"
    sha256sum \
      "$(basename "$FRAN_WORKSPACE_ARCHIVE")" \
      "$(basename "$FRAN_LOCK_DIGESTS")" \
      > "$(basename "$FRAN_WORKSPACE_DIGEST")"
    sha256sum -c "$(basename "$FRAN_WORKSPACE_DIGEST")"
  )

  printf 'FRAN_TRANSFER_ROOT=%s\n' "$FRAN_TRANSFER_ROOT"
  printf 'FRAN_WORKSPACE_ARCHIVE=%s\n' "$FRAN_WORKSPACE_ARCHIVE"
  printf 'FRAN_WORKSPACE_DIGEST=%s\n' "$FRAN_WORKSPACE_DIGEST"
  printf 'FRAN_LOCK_DIGESTS=%s\n' "$FRAN_LOCK_DIGESTS"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

The archive contains the complete workspace so relative `include::` paths from
each environment to `configs/` and the catalog snapshot remain valid. It also
contains the workspace `package-repos/` tree and hidden environment state. The
ordinary `spack -e` commands below use the repositories declared by the copied
configuration; they do not opt into the hidden environment recipe repository.
The current generated Fran workspace uses only workspace-relative include and
local-repository paths, with the pinned builtin recipe repository declared in
`configs/common/repos.yaml`. Confirm that shape before packaging an older or
hand-edited workspace. If any manifest or `repos.yaml` names an absolute path
outside `$BUILD_WORKSPACE`, stop and add the referenced content to the transfer
set, then remap that path only in the temporary connected copy. Never edit the
original Fran manifests or locks for transport. The archive does not contain
the restricted Spack install tree, views, modules, build stages, or build cache.

### B. Copy and unpack the Fran workspace on Blueback

This step has three separate operations: **B1 sets the receiving paths, B2
copies the three files, and B3 verifies and untars the workspace on Blueback.**
Neither rsync nor scp untars anything. After a successful actual transfer,
continue to [B3](#b3-verify-and-untar-on-blueback); the diagnostics and alternative
routes in B2 are only needed for the selected route or a transfer failure.
The diagnostic `rsync -avn` is a dry run and does not copy the archive.

| Variable | Meaning while running B on Blueback |
|---|---|
| `FRAN_TRANSFER_ROOT` | The exact existing archive directory on **Fran**, copied from A's output. Keep the older duplicated-username path if that is where A wrote the files. Do not derive this remote path from Blueback's `WORKDIR`. |
| `CONNECTED_TRANSFER_ROOT` | The receiving directory on **Blueback**. If files were already transferred, keep the directory used for that transfer. It need not match Fran's path. |
| `FRAN_WORKSPACE` | The temporary copied Fran workspace **on Blueback**, created by B3 under `CONNECTED_TRANSFER_ROOT`. It is not Fran's original `BUILD_WORKSPACE`. |

A's tar command stores the workspace under its relative directory name, and
the archive checksum file names the transferred files by basename. B3 selects
the receiving parent directory with `tar -C`. A different Blueback receiving
root therefore does not require repackaging the archive on Fran. The copied
workspace's configuration requirements still apply as described at the end of
A and in C, including the overrides for absolute Fran cache paths.

#### B1. Set Blueback's receiving paths

First create the receiving directory on Blueback. Its path
is temporary per-user work space; it is not a CSE tools root, package install
tree, or build cache.

```bash
set +e
set +o pipefail
export TRIAL_RELEASE="fran-trial-001"
export CONNECTED_TRANSFER_ROOT="${CONNECTED_TRANSFER_ROOT:-$WORKDIR/cse-fran-transfer/$TRIAL_RELEASE}"
export CONNECTED_WORKSPACE_ARCHIVE="$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz"
export CONNECTED_WORKSPACE_DIGEST="$CONNECTED_WORKSPACE_ARCHIVE.sha256"
export CONNECTED_LOCK_DIGESTS="$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256"
export FRAN_WORKSPACE="$CONNECTED_TRANSFER_ROOT/$TRIAL_RELEASE"

(
  set -e
  set -o pipefail
  : "${WORKDIR:?WORKDIR must be set on Blueback}"
  umask 0077
  install -d -m 0700 "$CONNECTED_TRANSFER_ROOT"
  printf 'CONNECTED_TRANSFER_ROOT=%s\n' "$CONNECTED_TRANSFER_ROOT"
  printf 'CONNECTED_WORKSPACE_ARCHIVE=%s\n' "$CONNECTED_WORKSPACE_ARCHIVE"
  printf 'FRAN_WORKSPACE (created by B3)=%s\n' "$FRAN_WORKSPACE"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

#### B2. Transfer the archive and checksum files

Use one transfer route, not both.

For a direct connection, stay on the connected system, fill in the Fran login
endpoint, paste the exact `FRAN_TRANSFER_ROOT` printed on Fran, and pull the
workspace archive, its checksum file, and the lock-digest manifest:

```bash
set +e
set +o pipefail
export FRAN_SSH="<fran-host-or-SSH-alias>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"

(
  set -e
  set -o pipefail
  rsync -av --partial --progress -e ssh \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
    "$CONNECTED_WORKSPACE_ARCHIVE"
  rsync -av --partial --progress -e ssh \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz.sha256" \
    "$CONNECTED_WORKSPACE_DIGEST"
  rsync -av --partial --progress -e ssh \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256" \
    "$CONNECTED_LOCK_DIGESTS"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

If rsync fails, stay on Blueback and diagnose that same pull before retrying.
Run each diagnostic separately and read its status. These checks use the
`FRAN_SSH`, `FRAN_TRANSFER_ROOT`, and receiving paths just set above:

```bash
set +e
set +o pipefail
command -v rsync
printf 'local rsync lookup status: %s\n' "$?"
ssh -v -T "$FRAN_SSH" 'command -v rsync && rsync --version'
printf 'remote rsync check status: %s\n' "$?"
```

```bash
set +e
set +o pipefail
rsync -avn --progress -e 'ssh -v' \
  "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
  "$CONNECTED_WORKSPACE_ARCHIVE"
transfer_status=$?
printf 'rsync dry-run status: %s\n' "$transfer_status"
```

The dry run transfers no file data. Interpret the error before changing options:

| Result | Next action |
|---|---|
| Authentication, hostname, or connection error | Check the same host alias, identity, port, and any jump host used by the working scp command. A successful transfer in the opposite direction does not verify this route. |
| Remote `rsync` is not found | Confirm its installed location on Fran. If available outside the remote command's PATH, use `--rsync-path=/confirmed/absolute/path/to/rsync`; otherwise use scp. |
| Remote commands are refused while scp works | Use the permitted scp/SFTP route; rsync needs permission to execute its remote process. |
| Protocol error or unexpected remote output | Inspect the first error and remote shell startup output; do not assume it is an authentication problem. |
| File not found or permission denied on an archive/directory | Check the exact printed transfer root, archive filename, and access on that endpoint. |
| Dry run succeeds | Retry the actual transfer block above and require status 0 before verification. |

Rsync requires its executable at both ends of a remote-shell transfer. Modern
OpenSSH scp uses SFTP by default, so a working scp connection does not prove
that the remote rsync command is installed or allowed. The `-e` option selects
the remote shell; `-e ssh` alone does not fix either issue. See the
[rsync manual](https://download.samba.org/pub/rsync/rsync.1),
[OpenSSH scp manual](https://man.openbsd.org/scp.1), and
[OpenSSH ssh manual](https://man.openbsd.org/ssh.1).

For the direct route, this scp alternative runs on Blueback and pulls the same
three files from Fran. Use it instead of the rsync pull, then continue to the
same checksum and unpack step below. A failed scp copy must be recopied; do not
use an incomplete archive.

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  scp -p \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
    "$CONNECTED_WORKSPACE_ARCHIVE"
  scp -p \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz.sha256" \
    "$CONNECTED_WORKSPACE_DIGEST"
  scp -p \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256" \
    "$CONNECTED_LOCK_DIGESTS"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

When the connected system cannot reach Fran directly, run the following on an
approved relay workstation. Fill in both SSH endpoints, paste the exact Fran
and connected transfer roots printed by the earlier blocks, and keep the relay
directory private:

```bash
set +e
set +o pipefail
export TRIAL_RELEASE="fran-trial-001"
export FRAN_SSH="<fran-host-or-SSH-alias>"
export CONNECTED_SSH="<blueback-host-or-SSH-alias>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"
export CONNECTED_TRANSFER_ROOT="<exact-CONNECTED_TRANSFER_ROOT-printed-on-connected-system>"
export RELAY_TRANSFER_ROOT="$HOME/cse-fran-relay/$TRIAL_RELEASE"

(
  set -e
  set -o pipefail
  umask 0077
  install -d -m 0700 "$RELAY_TRANSFER_ROOT"
  rsync -av --partial --progress -e ssh \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
    "$RELAY_TRANSFER_ROOT/"
  rsync -av --partial --progress -e ssh \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz.sha256" \
    "$RELAY_TRANSFER_ROOT/"
  rsync -av --partial --progress -e ssh \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256" \
    "$RELAY_TRANSFER_ROOT/"

  (
    cd "$RELAY_TRANSFER_ROOT"
    sha256sum -c "${TRIAL_RELEASE}-workspace.tar.gz.sha256"
  )

  ssh "$CONNECTED_SSH" \
    "umask 0077 && install -d -m 0700 '$CONNECTED_TRANSFER_ROOT'"
  rsync -av --partial --progress -e ssh \
    "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz" \
    "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/"
  rsync -av --partial --progress -e ssh \
    "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-workspace.tar.gz.sha256" \
    "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/"
  rsync -av --partial --progress -e ssh \
    "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256" \
    "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

#### B3. Verify and untar on Blueback

Run this block on Blueback after B2's actual transfer succeeds. This is where
the workspace is untarred. If this is a new shell, restore B1's variables using
the exact Blueback directory that received the files. Keep Fran's original
archive where it is; there is no need to rerun A solely because the two hosts
use different transfer roots.

The block verifies the archive and lock-digest manifest before extracting, then
checks the extracted workspace and all eight lockfiles. On success it prints
`Workspace verified and unpacked` with the resulting Blueback path. If that
directory already exists, the block stops before tar; follow
[F's extraction recovery](#f-resume-after-a-disconnect-or-interrupted-command)
instead of overwriting it or assuming a partial extraction is complete.

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  test -f "$CONNECTED_WORKSPACE_ARCHIVE"
  test -f "$CONNECTED_WORKSPACE_DIGEST"
  test -f "$CONNECTED_LOCK_DIGESTS"

  (
    cd "$CONNECTED_TRANSFER_ROOT"
    sha256sum -c "$(basename "$CONNECTED_WORKSPACE_DIGEST")"
  )
  test ! -e "$FRAN_WORKSPACE"
  tar -C "$CONNECTED_TRANSFER_ROOT" -xzf "$CONNECTED_WORKSPACE_ARCHIVE"
  test -f "$FRAN_WORKSPACE/workspace-manifest.yaml"
  test -x "$FRAN_WORKSPACE/cse-build"
  (
    cd "$FRAN_WORKSPACE"
    sha256sum -c "$CONNECTED_LOCK_DIGESTS"
  )

  FRAN_LOCK_COUNT="$(
    find "$FRAN_WORKSPACE/environments" \
      -mindepth 3 -maxdepth 3 -type f -name spack.lock -print |
      tee /dev/stderr |
      wc -l |
      tr -d '[:space:]'
  )"
  test "$FRAN_LOCK_COUNT" -eq 8
  printf 'Workspace verified and unpacked on Blueback: %s\n' "$FRAN_WORKSPACE"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

### C. Fetch the Fran sources on Blueback

Activate the same pinned Spack version, tag, commit, and package-recipe state
used for the trial. A matching CPU is not required because this operation reads
the locks and fetches source artifacts; it does not concretize or build them.

```bash
set +e
set +o pipefail
export FRAN_SOURCE_BUNDLE="$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror"
export CONNECTED_FETCH_STAGE="$CONNECTED_TRANSFER_ROOT/fetch-stage"
export CONNECTED_FETCH_CACHE="$CONNECTED_TRANSFER_ROOT/download-cache"
export CONNECTED_FETCH_MISC="$CONNECTED_TRANSFER_ROOT/misc-cache"
export SPACK_VERSION="1.2.2"
export SPACK_TAG="v$SPACK_VERSION"
export SPACK_COMMIT="3e19345b6e12f5ff1b874f4059622fc6a1fd804a"
export CONNECTED_SPACK_ROOT="<absolute-Blueback-path-to-matching-pinned-spack-checkout>"

(
  set -e
  set -o pipefail
  mkdir -p \
    "$FRAN_SOURCE_BUNDLE" \
    "$CONNECTED_FETCH_STAGE" \
    "$CONNECTED_FETCH_CACHE" \
    "$CONNECTED_FETCH_MISC" \
    "$CONNECTED_TRANSFER_ROOT/spack-user-cache"

  export SPACK_ROOT="$CONNECTED_SPACK_ROOT"
  export SPACK_USER_CACHE_PATH="$CONNECTED_TRANSFER_ROOT/spack-user-cache"
  export SPACK_DISABLE_LOCAL_CONFIG=true

  source "$SPACK_ROOT/share/spack/setup-env.sh"
  SPACK_VERSION_OUTPUT="$(spack --version)"
  test "${SPACK_VERSION_OUTPUT%% *}" = "$SPACK_VERSION"
  test "$(git -C "$SPACK_ROOT" rev-parse HEAD)" = "$SPACK_COMMIT"
  test "$(git -C "$SPACK_ROOT" rev-parse "${SPACK_TAG}^{commit}")" = \
    "$SPACK_COMMIT"
  test -z "$(git -C "$SPACK_ROOT" status --porcelain --untracked-files=all)"

  FRAN_ENVIRONMENT_COUNT=0
  for environment_dir in "$FRAN_WORKSPACE"/environments/*/*; do
    test -f "$environment_dir/spack.lock" || {
      echo "missing lockfile: $environment_dir/spack.lock" >&2
      exit 1
    }
    spack \
      -c "config:build_stage:[$CONNECTED_FETCH_STAGE]" \
      -c "config:source_cache:$CONNECTED_FETCH_CACHE" \
      -c "config:misc_cache:$CONNECTED_FETCH_MISC" \
      -e "$environment_dir" config get repos
    spack \
      -c "config:build_stage:[$CONNECTED_FETCH_STAGE]" \
      -c "config:source_cache:$CONNECTED_FETCH_CACHE" \
      -c "config:misc_cache:$CONNECTED_FETCH_MISC" \
      -e "$environment_dir" repo list
    FRAN_ENVIRONMENT_COUNT=$((FRAN_ENVIRONMENT_COUNT + 1))
  done
  test "$FRAN_ENVIRONMENT_COUNT" -eq 8
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

The subshell keeps the connected host's previous Spack activation, user cache,
local-configuration policy, and misc cache unchanged. The command-line cache
overrides are required because the copied Fran configuration contains absolute
Fran cache paths. For every environment, `config get repos` must show the
workspace-owned `cse_trials` repository followed by the trial's pinned builtin
Git tag, and `repo list` must resolve that order with `cse_trials` inside the
temporary copied workspace. The builtin checkout and other user-cache state
remain below the private connected transfer root. Stop before downloading if
the effective repository order, pin, or local path differs.

After reviewing those repository results, remain on Blueback and fetch the
sources for every copied Fran lockfile. This block does not concretize or
install packages:

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  export SPACK_ROOT="$CONNECTED_SPACK_ROOT"
  export SPACK_USER_CACHE_PATH="$CONNECTED_TRANSFER_ROOT/spack-user-cache"
  export SPACK_DISABLE_LOCAL_CONFIG=true
  source "$SPACK_ROOT/share/spack/setup-env.sh"

  cd "$FRAN_WORKSPACE"
  sha256sum -c "$CONNECTED_LOCK_DIGESTS"
  FRAN_ENVIRONMENT_COUNT=0
  for environment_dir in "$FRAN_WORKSPACE"/environments/*/*; do
    test -f "$environment_dir/spack.lock"
    spack \
      -c "config:build_stage:[$CONNECTED_FETCH_STAGE]" \
      -c "config:source_cache:$CONNECTED_FETCH_CACHE" \
      -c "config:misc_cache:$CONNECTED_FETCH_MISC" \
      -e "$environment_dir" \
      mirror create -a -d "$FRAN_SOURCE_BUNDLE"
    FRAN_ENVIRONMENT_COUNT=$((FRAN_ENVIRONMENT_COUNT + 1))
  done
  test "$FRAN_ENVIRONMENT_COUNT" -eq 8
  sha256sum -c "$CONNECTED_LOCK_DIGESTS"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

The command may be rerun against the same bundle; Spack retains existing
archives and adds missing ones. Review any skipped or failed fetch, especially
license-restricted sources. Do not use `--private` unless storage and transfer
of those sources has been explicitly approved.

### D. Package and return the sources from Blueback to Fran

On Blueback, package the completed source bundle and record its digest:

```bash
set +e
set +o pipefail
export FRAN_BUNDLE_ARCHIVE="$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar"
export FRAN_BUNDLE_DIGEST="$FRAN_BUNDLE_ARCHIVE.sha256"

(
  set -e
  set -o pipefail
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
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

Source archives are normally already compressed, so the returned bundle uses
an uncompressed tar container. Use one return route, not both.

For a direct connection, stay on the connected system, restore the Fran
endpoint and exact Fran transfer root if necessary, and push both files:

```bash
set +e
set +o pipefail
export FRAN_SSH="<fran-host-or-SSH-alias>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"

(
  set -e
  set -o pipefail
  rsync -av --partial --progress -e ssh \
    "$FRAN_BUNDLE_ARCHIVE" \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
  rsync -av --partial --progress -e ssh \
    "$FRAN_BUNDLE_DIGEST" \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

For the same direct return using scp, run this on Blueback instead of the
rsync push, then verify the returned digest on Fran in step E:

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  scp -p "$FRAN_BUNDLE_ARCHIVE" "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
  scp -p "$FRAN_BUNDLE_DIGEST" "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

When a relay is required, run the following on the approved relay workstation.
It pulls the finished bundle from the connected system, verifies it, and then
pushes the same two files to Fran:

```bash
set +e
set +o pipefail
export TRIAL_RELEASE="fran-trial-001"
export CONNECTED_SSH="<blueback-host-or-SSH-alias>"
export FRAN_SSH="<fran-host-or-SSH-alias>"
export CONNECTED_TRANSFER_ROOT="<exact-CONNECTED_TRANSFER_ROOT-printed-on-connected-system>"
export FRAN_TRANSFER_ROOT="<exact-FRAN_TRANSFER_ROOT-printed-on-fran>"
export RELAY_TRANSFER_ROOT="$HOME/cse-fran-relay/$TRIAL_RELEASE"

(
  set -e
  set -o pipefail
  umask 0077
  install -d -m 0700 "$RELAY_TRANSFER_ROOT"
  rsync -av --partial --progress -e ssh \
    "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar" \
    "$RELAY_TRANSFER_ROOT/"
  rsync -av --partial --progress -e ssh \
    "$CONNECTED_SSH:$CONNECTED_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar.sha256" \
    "$RELAY_TRANSFER_ROOT/"

  (
    cd "$RELAY_TRANSFER_ROOT"
    sha256sum -c "${TRIAL_RELEASE}-source-mirror.tar.sha256"
  )

  rsync -av --partial --progress -e ssh \
    "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar" \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
  rsync -av --partial --progress -e ssh \
    "$RELAY_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar.sha256" \
    "$FRAN_SSH:$FRAN_TRANSFER_ROOT/"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

If `rsync` is unavailable on one approved transfer leg, use `scp -p` for that
same source file and destination directory, then run the same SHA-256 check at
the receiving endpoint. Do not return the copied workspace archive as a
replacement for Fran's original workspace.

### E. Install the source bundle into Fran's generated source cache

Back on Fran, source the saved operator session again and verify the returned
bundle before extracting it:

```bash
set +e
set +o pipefail
source "$HOME/STACK_TESTING/operator-sessions/fran/fran-trial-001/activate.sh"
session_status=$?
printf 'session activation status: %s (continue only if 0)\n' "$session_status"
```

Continue only if activation succeeded. Then run:

```bash
set +e
set +o pipefail
export FRAN_TRANSFER_ROOT="${FRAN_TRANSFER_ROOT:-$WORKDIR/cse-fran-transfer/$TRIAL_RELEASE}"
export FRAN_BUNDLE_ARCHIVE="$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror.tar"
export FRAN_BUNDLE_DIGEST="$FRAN_BUNDLE_ARCHIVE.sha256"
export FRAN_SOURCE_BUNDLE="$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-source-mirror"

(
  set -e
  set -o pipefail
  (
    cd "$FRAN_TRANSFER_ROOT"
    sha256sum -c "$(basename "$FRAN_BUNDLE_DIGEST")"
  )
  test ! -e "$FRAN_SOURCE_BUNDLE"
  tar -C "$FRAN_TRANSFER_ROOT" -xf "$FRAN_BUNDLE_ARCHIVE"
  test -d "$FRAN_SOURCE_BUNDLE"
  (
    cd "$BUILD_WORKSPACE"
    sha256sum -c "$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256"
  )
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

Read the source-cache destination through an actual generated environment and
confirm that it is the restricted cache selected for this operator session.
Do not type or infer the destination path independently. Cache discovery and
the merge run together so a failed check stops before any copy.

Merge only the source mirror's contents into that generated cache while
preserving the CSE group/setgid policy. Spack's mirror and `source_cache` use
the same cache-relative archive layout, so the trailing slashes below are
intentional. This is an additive merge without `--delete`: existing cache
entries remain in place, and the generated `source_cache` setting is never
edited or temporarily replaced. This rsync is local to Fran; it does not use SSH.

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  verify_spack_tool_root
  source "$SPACK_ROOT/share/spack/setup-env.sh"
  source "$BUILD_WORKSPACE/env/select-build-context.sh"
  cse_select_build_context login
  source "$BUILD_WORKSPACE/env/setup-build-env.sh"

  export FRAN_REFERENCE_ENV="$BUILD_WORKSPACE/environments/$SHARED_COMPILER_NAME/core"
  FRAN_SOURCE_CACHE="$(
    spack -e "$FRAN_REFERENCE_ENV" python -c \
      'import spack.config; print(spack.config.get("config:source_cache"))'
  )"

  test -n "$FRAN_SOURCE_CACHE"
  test "$FRAN_SOURCE_CACHE" = "$CSE_RESTRICTED_ROOT/cache/source"
  printf 'FRAN_SOURCE_CACHE=%s\n' "$FRAN_SOURCE_CACHE"

  umask 0007
  install -d -m 2770 -g "$CSE_GROUP" "$FRAN_SOURCE_CACHE"
  rsync -a --no-owner --no-group --checksum \
    "$FRAN_SOURCE_BUNDLE/" "$FRAN_SOURCE_CACHE/"

  chgrp -R "$CSE_GROUP" "$FRAN_SOURCE_CACHE"
  find "$FRAN_SOURCE_CACHE" -type d -exec chmod g+rws,o-rwx {} +
  find "$FRAN_SOURCE_CACHE" -type f -exec chmod g+rw,o-rwx {} +
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

Finally, use the original Fran workspace and its existing lockfiles to fetch
every environment's complete dependency closure through the populated cache.
The lock-digest check above proves that the eight destination lockfile bytes
were not replaced or changed. A missing artifact can still fall through to a
configured upstream URL. On a partially connected Fran login node, an upstream
success is therefore not proof that the cache is complete; retain the connected
`mirror create` success for all eight locked environments as the completeness
gate and review the destination fetch transcript for unexpected upstream use.

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  cd "$BUILD_WORKSPACE"
  ./cse-build login verify
  ./cse-build login fetch
  sha256sum -c "$FRAN_TRANSFER_ROOT/${TRIAL_RELEASE}-locks.sha256"
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

Gate: `./cse-build login fetch` succeeds for all eight original Fran
environments.
Retain both transfer archives and their digest files until the first complete
Fran build succeeds; they are recovery evidence for the same locked release.
The source bundle is not the signed CSE binary build cache and does not change
any `spack.lock`. If the Spack runtime itself must be bootstrapped without
network access, prepare a separate Spack bootstrap mirror; do not mix bootstrap
artifacts into this source bundle.

### F. Resume after a disconnect or interrupted command

A new shell loses exports, shell functions, the current directory, and Spack
activation. It does not require regenerating files that remain on disk. Restore
the same release and paths first. A lost connection also does not prove that
the old command stopped: check for an existing transfer/fetch process or
reattach to its session before starting another writer on the same bundle.

| Resume on | Restore in the new Bash shell |
|---|---|
| Fran | Run `set +e` and `set +o pipefail`, then source the existing `activate.sh` from step A/E and require activation status 0. Restore the exports for the needed step, using the exact existing `FRAN_TRANSFER_ROOT`. The saved session restores `BUILD_WORKSPACE` and the Fran build settings. |
| Blueback | Rerun the first setup block in B with the existing `CONNECTED_TRANSFER_ROOT`; it restores the release, receiving paths, and copied-workspace path. Restore `FRAN_SSH` and the exact Fran transfer root for a direct transfer. |
| Blueback, before resuming source acquisition | After B's setup, rerun C's first block with the same `CONNECTED_SPACK_ROOT`. It restores the mirror/cache paths and checks the pinned runtime and effective repositories. Review those checks, then rerun C's fetch block. |
| Blueback, only returning a completed mirror archive | After B's setup, restore the two `FRAN_BUNDLE_ARCHIVE`/`FRAN_BUNDLE_DIGEST` exports at the start of D and the transfer endpoint exports. Skip D's tar creation when the existing archive and digest are complete and valid. |
| Approved relay | Restore the exports in the selected B or D relay block, including both exact remote transfer roots and the existing local relay directory. Retry only the needed transfer leg, retaining the receiving checksum check. |

On Blueback, source acquisition uses C's isolated Spack activation. Do not
source Fran's operator session there or substitute Blueback build settings for
the copied Fran locks. Temporary `SPACK_ROOT`, cache overrides, and
`SPACK_DISABLE_LOCAL_CONFIG` settings are reapplied inside C's subshell each
run. Step E similarly restores its Fran cache-selection settings inside the
merge block, so they do not need to persist between shells.

Resume from the last completed, verified step:

| Interrupted operation | Repeat | Keep; do not regenerate for a disconnect |
|---|---|---|
| Workspace packaging on Fran (A) | If tar/checksum generation did not finish, repeat A only after confirming the original workspace is unchanged and no writer is active. | Original manifests, recipes, and eight lockfiles. A completed archive and matching digests can be reused. |
| Any rsync transfer (B/D) | Repeat that same command against the same unchanged archive. `--partial` retains interrupted data for reuse; require completion and the receiving SHA-256 check. | The source archive and digest. Do not re-tar solely to retry a transfer. |
| Any scp transfer (B/D) | Recopy the affected file, then run the receiving SHA-256 check. | The completed source archive and digest. |
| Workspace extraction on Blueback (B) | If extraction finished, rerun the checks below and skip tar. If interrupted or uncertain, set aside the temporary extracted directory and repeat B's checksum/unpack block. | Original Fran workspace and verified workspace archive/digests. |
| Source fetch on Blueback (C) | Rerun C's setup/repository checks, then its eight-environment fetch loop against the same mirror. Review every failed/skipped fetch. | Copied workspace, locks, existing source mirror, download cache, and Spack user cache. Do not concretize again. |
| Source-mirror packaging on Blueback (D) | Recreate the return tar and its digest only if packaging was interrupted or the mirror changed after packaging. Stop transfers first. | An unchanged, completed return archive/digest pair can be verified and retransferred directly. |
| Source-mirror extraction on Fran (E) | If extraction was interrupted or its completion is uncertain, set aside only the extracted source-mirror directory, then repeat E's checksum/extraction block. | The verified return archive and original Fran workspace. |
| Merge into Fran's source cache (E) | Rerun the complete cache-discovery/merge block, including group/permission normalization. | Existing shared cache entries; the merge is additive. |
| Final Fran fetch (E) | Rerun the final verify/fetch/lock-digest block. | The original locks and populated source cache. |

To recheck a previously completed Blueback extraction after restoring B's
exports, run:

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  cd "$CONNECTED_TRANSFER_ROOT"
  sha256sum -c "$(basename "$CONNECTED_WORKSPACE_DIGEST")"
  test -f "$FRAN_WORKSPACE/workspace-manifest.yaml"
  test -x "$FRAN_WORKSPACE/cse-build"
  cd "$FRAN_WORKSPACE"
  sha256sum -c "$CONNECTED_LOCK_DIGESTS"
  test "$(find environments -mindepth 3 -maxdepth 3 -type f -name spack.lock |
    wc -l | tr -d '[:space:]')" -eq 8
)
transfer_status=$?
printf 'step status: %s (continue only if 0)\n' "$transfer_status"
```

These checks validate the archive and lockfiles; they do not prove an
interrupted extraction wrote every other file. If extraction completion is
uncertain, preserve that temporary directory under a new name before repeating
the corresponding B/E unpack block. Run only the command for the current host,
and require status 0. Never apply these moves to `BUILD_WORKSPACE` or the shared
source cache:

```bash
# Blueback only: set aside an incomplete temporary workspace extraction.
set +e
set +o pipefail
mv -T -- "$FRAN_WORKSPACE" "$FRAN_WORKSPACE.incomplete.$(date +%Y%m%dT%H%M%S)"
printf 'set-aside status: %s (continue only if 0)\n' "$?"
```

```bash
# Fran only: set aside an incomplete source-mirror extraction.
set +e
set +o pipefail
mv -T -- "$FRAN_SOURCE_BUNDLE" "$FRAN_SOURCE_BUNDLE.incomplete.$(date +%Y%m%dT%H%M%S)"
printf 'set-aside status: %s (continue only if 0)\n' "$?"
```

There is no need to regenerate the operator session, probes, profile, static
catalog, build values, rendered workspace, or `spack.lock` files solely because
a shell or connection was lost. Those belong to changes in build inputs, not
transfer recovery. An optional site-supported `tmux` session can retain a
long-running fetch across a client disconnect, but it does not fix SSH access,
a missing rsync executable, or a host/session being terminated.

## Phase Zero restricted module review after both surfaces finish

The consumer gate is a presentation step over the eight existing environments;
it is not another package or Spack root. After the GCC and CCE surfaces have
both installed and their package modules have refreshed, synchronize Stack
Content, run the control-only workspace refresh above, and then run:

```bash
cd "$BUILD_WORKSPACE"
./cse-build login verify
./cse-build login publish-modules
```

This copies only `cse/init-GCC`, `cse/init-CCE`, and ready short lane selectors
into the module root recorded by the restricted build values. Despite the
command name, this is not public stack promotion. It does not write under the
published root, publish the static catalog, create the cache-only publication
workspace, or grant access to users outside CSE. This is the CSE team-review
checkpoint for the restricted module presentation.

The command leaves the CSE-GCC/Cray-MPICH MPI selector withheld from the
restricted release module root while its catalog-derived simple-wrapper
interface is
`multi-node-validation-required`. The completed locked MPI package builds are
the build-plane compiler, link, and runtime evidence. Load the generated
selector from the workspace `modulefiles/` tree and record the exact wrapper
identity and compiler bindings, then run it across multiple nodes through
Fran's approved native launcher. Use
`presentation/mpi-consumer-candidates.yaml` as the candidate-fact input.
Publish the selector only after that native launch succeeds. The presentation
command has no bypass flag and preserves the package roster, environment YAML,
lockfiles, views, generated package modules, caches, and installed prefixes.

Validate the candidate from a clean module state:

```bash
module --force purge
module load cse/init-GCC
module use "$BUILD_WORKSPACE/modulefiles/gcc/lanes"
module load MPI
module list
command -v "$CSE_MPICC" "$CSE_MPICXX" "$CSE_MPIFC"
printf '%s\n' "$MPICH_CC" "$MPICH_CXX" "$MPICH_FC"
"$CSE_MPICC" -show
srun --mpi=list

# Inside the approved allocation, substitute Fran's reviewed plugin.
CSE_SLURM_MPI_PLUGIN="REPLACE_WITH_REVIEWED_PLUGIN"
srun --mpi="$CSE_SLURM_MPI_PLUGIN" -N 2 -n 2 ./cse-mpi-smoke
```

If Fran uses a Cray native launcher rather than a Slurm MPI plugin for this
lane, record and run that site command instead. Do not infer a launcher from the
Cray MPICH compiler-wrapper prefix.

Stop at this checkpoint for team review. If the restricted module presentation
and runtime evidence are accepted, record the lanes as `runtime-passed`, push
their exact hashes to the
private build cache, and continue with the common runbook's public static
catalog and cache-only publication steps. If only module presentation changes,
refresh the workspace controls and repeat this checkpoint without rebuilding or
reconcretizing. A package, provider, compiler, MPI, or dependency change follows
the common runbook's DAG-changing recovery rules.

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
