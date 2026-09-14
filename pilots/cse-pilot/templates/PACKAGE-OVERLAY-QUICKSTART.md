# Offline package fixes in an existing CSE trial

Use this guide to inspect one failure, install a reviewed recipe correction,
retry that package with Spack, and carry the correction to another workspace.
Git, GitLab, Stack Composer, and a new workspace render are not needed for
this loop. Keep this file with the workspace when working offline.
Commands target the current Spack 1.2.2 / repository API v2 workspace; verify
the version and effective configuration on the receiving system.

An **overlay** is our higher-priority `cse_trials` Spack recipe repository.
Spack selects a whole recipe from it; it does not merge two `package.py` files.
Our usual recipe subclasses the pinned builtin class to retain upstream
behavior and add a narrow fix. Transfer the complete local package directory,
including every patch/support file, while preserving any existing local fixes.

This procedure is for an unfinished, unaccepted build trial. Coordinate edits
with anyone using the same package repository or locks. For an accepted
release, make a new candidate instead of changing its recorded inputs.

## Manual steps and optional helpers

The fix itself is manual: inspect the original files, edit a candidate in a
text editor, copy its reviewed files, run the Spack commands, and record the
result. An on-site agent can perform exactly the same steps. The Bash blocks
below are commands to run step by step, not a new updater to install.

| Tool or action | Role in this guide |
| --- | --- |
| Text editor, `install`/`cp`, `spack`, `tar`, `sha256sum` | Manual edit, apply, test, and transfer steps below |
| `./cse-build login shell` / `./cse-build compute shell` | Existing generated shell setup; selects this workspace's runtime and node context |
| `./cse-build login verify` | Existing lock check after recovering affected locks; does not prove a new package fix works |
| `./cse-build compute install --surface platform` | Optional full CCE-surface resume after the focused package retry |
| `refresh-workspace-controls.py` | Optional generated-control update, documented in Stack Content's `pilots/cse-pilot/STACK-COMPOSER-UPDATE.md`; does not copy package overlays |

There is no separate package-overlay apply/export helper attached to this
guide. The copy and archive steps are shown explicitly. Healthy existing
workspaces only need a copy of this Markdown guide; they do not need a render
or control refresh to read it or follow the manual overlay procedure.

## 1. Open the existing workspace and find the paths

Use the absolute workspace path given to the builder. It contains
`workspace-manifest.yaml`, `cse-build`, `env/`, `configs/`, `environments/`, and
`package-repos/`. This is different from the Stack Content checkout or the
Spack checkout. Its `BUILDER-HANDOFF.md` describes initial setup and resuming
the workspace; do not initialize another workspace to investigate a failure.
If resuming the operator's existing session, `printf '%s\n' "$BUILD_WORKSPACE"`
prints its recorded workspace path. The session derives it as
`$CSE_RESTRICTED_ROOT/workspaces/$SYSTEM_NAME/initial-conversion-trials/$TRIAL_RELEASE`.
Inside a prepared builder shell, the same location is `$CSE_BUILD_WORKSPACE`.

From a fresh login shell:

```bash
cd "<absolute-existing-trial-workspace>"
./cse-build login shell
```

This opens the generated Bash setup; it does not start an install. If already
in that prepared shell, continue there. All remaining command blocks use Bash.
The standalone `env/setup-build-env.sh` only exports workspace values; sourcing
it alone does not activate Spack, select node-local staging, or prepare modules
and caches. Use the prepared shell, then run direct Spack commands below.

Offline prerequisite: the recorded Spack checkout, builtin repository pin,
solver/bootstrap state, sources, resources, and URL patches must already be
available locally. Shell entry can otherwise try to provision Spack, and a
solve/build can try to acquire missing inputs. `--no-cache` below disables
binary reuse for installation; it is not an offline/network switch.

The example is netlib-lapack on the CCE surface. The roster places LAPACK roots
in **Common**; it also appears under MPI dependents. Select the environment
that actually failed, rather than assuming every failure is in Core.

```bash
export ENVIRONMENT="$PLATFORM_COMPILER_NAME/common"
export TARGET_ENV="$CSE_BUILD_WORKSPACE/environments/$ENVIRONMENT"
export PACKAGE_NAME="netlib-lapack"
export PACKAGE_MODULE="netlib_lapack"
export OVERLAY_REPO="$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials"
export PACKAGE_DIR="$OVERLAY_REPO/packages/$PACKAGE_MODULE"

spack --version
spack -e "$TARGET_ENV" repo list
spack -e "$TARGET_ENV" config get repos
spack -e "$TARGET_ENV" find -c -d -L -N -v "$PACKAGE_NAME"
export BUILTIN_REPO="$(spack -e "$TARGET_ENV" location --repo builtin)"
export BUILTIN_RECIPE="$BUILTIN_REPO/packages/$PACKAGE_MODULE/package.py"
printf 'Workspace: %s\nEnvironment: %s\nBuiltin recipe: %s\nOverlay recipe: %s\n' \
  "$CSE_BUILD_WORKSPACE" "$TARGET_ENV" "$BUILTIN_RECIPE" "$PACKAGE_DIR/package.py"
```

| What you need | Where to inspect it |
| --- | --- |
| Workspace setup and recorded paths | `BUILDER-HANDOFF.md`, `workspace-manifest.yaml`, `env/setup-build-env.sh` |
| Original recipe actually pinned here | `$BUILTIN_RECIPE` and its neighboring patch files |
| Current local corrections | `$PACKAGE_DIR/package.py` and neighboring patch/support files, if present |
| Repository selection | `$CSE_BUILD_WORKSPACE/configs/common/repos.yaml` and effective `repo list` |
| Requested inputs and resolved build | `$TARGET_ENV/spack.yaml` and `$TARGET_ENV/spack.lock` |
| Source for future renders | `<stack-content>/pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/packages/netlib_lapack/` |

`cse_trials` must precede `builtin` and resolve inside this workspace. Do not
edit the cached builtin recipe or add a user-level repo. Spack API v2 uses
`netlib_lapack` for the directory/import and `netlib-lapack` for the spec name.
Read the original file with `less "$BUILTIN_RECIPE"`. Read any existing local
recipe before preparing a replacement.

## 2. Save the evidence before editing

Choose the full failed hash from the listing, including the correct version
and CCE dependency. Do not select the first match if several appear. The photo
suggests 3.12.1; confirm that from the lock/log.
Choose a new record directory on shared storage writable from both login and
compute nodes; a node-local record will not follow you into the allocation.

```bash
export FAILED_HASH="<full-failed-hash-without-leading-slash>"
export OVERLAY_RECORD="<absolute-new-shared-change-record-directory-outside-package-repo>"
(
  set -e
  test ! -e "$OVERLAY_RECORD"
  install -d -m 2770 -g "$CSE_GROUP" "$OVERLAY_RECORD"
  cp -p "$TARGET_ENV/spack.yaml" "$OVERLAY_RECORD/spack.yaml.before"
  cp -p "$TARGET_ENV/spack.lock" "$OVERLAY_RECORD/spack.lock.before"
  cp -a "$BUILTIN_REPO/packages/$PACKAGE_MODULE" "$OVERLAY_RECORD/builtin-before"
  if test -d "$PACKAGE_DIR"; then
    cp -a "$PACKAGE_DIR" "$OVERLAY_RECORD/overlay-before"
  fi
  spack -e "$TARGET_ENV" find -c -d -L -N -v > "$OVERLAY_RECORD/graph.before.txt"
  spack -e "$TARGET_ENV" find -c -d -L -N -v "/$FAILED_HASH" > "$OVERLAY_RECORD/failed-spec.before.txt"
  spack -e "$TARGET_ENV" config get repos > "$OVERLAY_RECORD/repos.before.yaml"
  spack --version > "$OVERLAY_RECORD/spack-version.txt"
  printf 'Workspace: %s\nEnvironment: %s\nSpack root: %s\nBuiltin recipe: %s\nOverlay: %s\nFailed hash: %s\nNode context: %s\n' \
    "$CSE_BUILD_WORKSPACE" "$TARGET_ENV" "$SPACK_ROOT" "$BUILTIN_RECIPE" \
    "$PACKAGE_DIR" "$FAILED_HASH" "$CSE_NODE_CONTEXT" > "$OVERLAY_RECORD/paths.txt"
  git -C "$SPACK_ROOT" rev-parse HEAD > "$OVERLAY_RECORD/spack-commit.txt"
  git -C "$BUILTIN_REPO" rev-parse HEAD > "$OVERLAY_RECORD/builtin-commit.txt"
)
```

Continue only if the block succeeded and `failed-spec.before.txt` identifies
the intended version/compiler. The two `git rev-parse` commands only read
local commit IDs; they need no network. For a supplied non-Git recipe snapshot,
replace its `git` command before running the block with a record of the supplied
revision and checksum.

Find the stage in the **same node context** used for the failure, or use the
exact stage path printed in the original log. Login and compute staging may
be different, and a new login may not retain node-local files.
For a compute failure, prefer the original absolute stage path from the log.
If discovering it with Spack, first return to the original compute allocation,
enter `./cse-build compute shell`, and re-enter Step 1's variables plus
`FAILED_HASH` and the shared `OVERLAY_RECORD` path before running this command.
Do not treat a login-context stage location as the failed compute stage.

```bash
spack -e "$TARGET_ENV" location --stage-dir "/$FAILED_HASH"
```

Copy the complete `spack-build-out.txt` and, when present,
`spack-build-env.txt` from that stage into the record. For this LAPACK link
failure also retain the failing build directory's `CMakeCache.txt` and
`BLAS/SRC/CMakeFiles/blas.dir/link.txt`. Use the actual paths found in the log;
the recipe can have separate static and shared build directories.

The Blueback photo shows configuration finishing, followed by a BLAS shared
library link failure with a `multiple definition` diagnostic. It does not
establish the cause or exact duplicate symbol. Retain the first diagnostic,
both object names, and the complete link command. Do not apply the separate
GNU `-sinteger64` workaround to this CCE failure based on the photo.

## 3. Prepare one reviewable candidate

Give the author/agent the following, with missing items explicitly marked:

```text
System and node context; absolute workspace and TARGET_ENV paths:
Spack version/commit and builtin tag/resolved commit:
Package/version, compiler/version, variants, full failed hash:
BUILTIN_RECIPE path and complete original package directory:
PACKAGE_DIR path and complete existing overlay directory, or "absent":
Original build command, full log, first error and generated link command:
Source/build stage paths and relevant generated files:
Offline inputs already available and any missing inputs:

Return a complete corrected local package directory, retaining existing fixes;
every referenced patch/support file; a diff; the demonstrated cause and narrow
version/compiler scope; and one repeatable failure/retry command with a small
package validation. Distinguish checks actually run from proposed checks.
```

Stage those files in `$OVERLAY_RECORD/candidate/`. A typical source correction
imports `NetlibLapack` from
`spack_repo.builtin.packages.netlib_lapack.package`, subclasses it as
`NetlibLapack`, and adds a local `patch(...)` with an evidenced `when` condition.
That is the overlay structure, **not a proposed fix for the photographed error**.
Inspect the pinned builder before overriding recipe methods.

Review the complete candidate, parse its Python, and dry-run source patches
against a disposable pristine copy of the exact package source. Existing
builtin patches and patch order matter. Keep a short `CHANGE.md` in the record:
input revisions, file list, cause/scope, commands, before/after results, and
which systems/compiler versions were actually tested.

## 4. Copy the reviewed files and prove selection

Set the explicit list to the candidate's actual filenames. A recipe-only
correction uses just `package.py`. Do not run this block until the candidate
has been prepared and reviewed.

```bash
export OVERLAY_CANDIDATE_DIR="$OVERLAY_RECORD/candidate"
OVERLAY_FILES=(package.py)  # Add each reviewed local patch/support filename.
(
  set -e
  test -f "$OVERLAY_RECORD/spack.lock.before"
  for overlay_file in "${OVERLAY_FILES[@]}"; do
    test -f "$OVERLAY_CANDIDATE_DIR/$overlay_file"
  done
  spack python -c 'import ast, os; ast.parse(open(os.path.join(os.environ["OVERLAY_CANDIDATE_DIR"], "package.py")).read())'
  install -d -m 2770 -g "$CSE_GROUP" "$PACKAGE_DIR"
  for overlay_file in "${OVERLAY_FILES[@]}"; do
    install -m 0660 -g "$CSE_GROUP" "$OVERLAY_CANDIDATE_DIR/$overlay_file" "$PACKAGE_DIR/$overlay_file"
  done
)
spack -e "$TARGET_ENV" location --package-dir "$PACKAGE_NAME"
spack -e "$TARGET_ENV" python -c 'import inspect, os, spack.repo; cls = spack.repo.PATH.get_pkg_class(os.environ["PACKAGE_NAME"]); print(inspect.getfile(cls))'
```

Require successful copying and both paths to identify
`$PACKAGE_DIR/package.py` (or its enclosing directory for `location`). If a
copy fails, restore or finish the complete file set before building. Review
any superseded files explicitly; backups belong outside `packages/`.

## 5. Update the affected candidate lock

A file edit does not update the namespace or package identity in an existing
lock. Back up each affected environment separately and inspect dependents.
Choose **one** solve for the selected unaccepted environment:

```bash
# Changed package is a root; reuse of unchanged dependencies is intended:
spack -e "$TARGET_ENV" concretize -f --reuse-deps -j 1

# Alternative when an affected dependency/ancestor could otherwise be reused:
# spack -e "$TARGET_ENV" concretize -f --fresh -j 1
```

The alternative can change other nodes; neither command promises only one
hash will change. Inspect the entire graph and explain unrelated changes.
For LAPACK, review Common and MPI locks containing it and any dependent Dakota
nodes. Do not automatically run either command over all eight environments.

```bash
spack -e "$TARGET_ENV" find -c -d -L -N -v > "$OVERLAY_RECORD/graph.after.txt"
diff -u "$OVERLAY_RECORD/graph.before.txt" "$OVERLAY_RECORD/graph.after.txt"
spack -e "$TARGET_ENV" find -c -d -L -N -v "$PACKAGE_NAME"
```

`diff` status 1 means differences were found. Confirm `cse_trials`, the intended
recipe/patch identity, and affected dependent hashes. Record the new hash.
Once all affected locks have been recovered, run the existing workspace lock
check (`./cse-build login verify`) before resuming the trial. This guide does
not expand the full release or CMake validation procedures.

## 6. Retry only this package, directly with Spack

Enter the site's approved compute allocation, return to the same shared
workspace, and run `./cse-build compute shell`. Re-enter the selection variables
from Step 1 and set `OVERLAY_RECORD` to the saved record path. Use the new hash
from the updated lock, not the old failed hash:

```bash
export NEW_HASH="<full-corrected-hash-without-leading-slash>"
spack -e "$TARGET_ENV" find -c -d -L -N -v "/$NEW_HASH"
set -o pipefail
spack -e "$TARGET_ENV" install --only-concrete --no-cache --keep-stage -v -j 1 "/$NEW_HASH" \
  2>&1 | tee "$OVERLAY_RECORD/install.after.log"
overlay_install_status=${PIPESTATUS[0]}
printf 'Package install status: %s\n' "$overlay_install_status"
```

This selects the package and needed dependencies, not the whole surface.
One job makes the first failure easier to read. Existing installed hashes are
still skipped: `--no-cache` is not a forced reinstall. Require status 0 and
confirm the log actually compiled the corrected package. If it was already
installed, retain its original successful build evidence or arrange a separate
test store; do not delete shared prefixes to force a retry.
The install may update the selected environment's view. Preserve the old stage
evidence first: `--keep-stage` retains the stage after a successful build; it
does not guarantee that a retry keeps previous partial build artifacts.

Rerun the same minimal failing operation against the corrected stage/new
prefix, preserving the relevant flags and failure check; do not replay paths
that still point at the old hash. Run the small validation supplied with
the fix. For LAPACK, require the BLAS link to succeed and a small BLAS/LAPACK
compile, link, and numerical execution check with the same compiler. Installation
success alone does not establish numerical correctness. Record results in
`CHANGE.md`; do not mark an unrun Blueback/CCE check as passed.

## 7. Carry the overlay to another workspace without Git

After validation, stage **only this package's reviewed files** plus its change
record. Keep logs, builtin snapshots, old recipes, and lock backups out of the
package payload. Re-enter the reviewed `OVERLAY_FILES` list from Step 4 in the
compute shell (Bash arrays are not exported into the new shell):

```bash
OVERLAY_FILES=(package.py)  # Add the same reviewed patch/support filenames.
(
  set -e
  test ! -e "$OVERLAY_RECORD/outgoing"
  mkdir -p "$OVERLAY_RECORD/outgoing/$PACKAGE_MODULE"
  for overlay_file in "${OVERLAY_FILES[@]}"; do
    cp -p "$PACKAGE_DIR/$overlay_file" "$OVERLAY_RECORD/outgoing/$PACKAGE_MODULE/"
  done
  cp -p "$OVERLAY_RECORD/CHANGE.md" "$OVERLAY_RECORD/outgoing/CHANGE.md"
  tar -czf "$OVERLAY_RECORD/$PACKAGE_MODULE-overlay.tar.gz" \
    -C "$OVERLAY_RECORD/outgoing" CHANGE.md "$PACKAGE_MODULE"
  ( cd "$OVERLAY_RECORD"; sha256sum "$PACKAGE_MODULE-overlay.tar.gz" > "$PACKAGE_MODULE-overlay.tar.gz.sha256" )
)
```

Copy the archive and checksum with the site's approved file-transfer method,
removable media, or `scp` when a connection is available. On the receiving
system, place them outside its package repo. For this LAPACK example:

```bash
cd "<directory-containing-received-archive-and-checksum>"
sha256sum -c netlib_lapack-overlay.tar.gz.sha256
tar -tzf netlib_lapack-overlay.tar.gz
# After checksum success and checking the listed CHANGE.md/netlib_lapack files:
mkdir received-netlib-lapack
tar -xzf netlib_lapack-overlay.tar.gz -C received-netlib-lapack
```

Use a new extraction directory and require each command to succeed. Review
`CHANGE.md`, the file list, and differences from its
existing overlay. Compare that workspace's Spack/builtin revisions and affected
compiler/version before applying. A different builtin pin requires adaptation
and review, not an assumption that the subclass is compatible.

Repeat Steps 1–6 using the **receiving** workspace's paths and a new record;
in Step 4 set `OVERLAY_CANDIDATE_DIR` to the absolute path
`<received-archive-directory>/received-netlib-lapack/netlib_lapack` and set
`OVERLAY_FILES` from its reviewed file list. Preserve
any destination-only corrections. Transfer recipes/patches, then solve and
test locally; do not transplant another system's locks, compiler configuration,
paths, or installed libraries. Success on one system is evidence for that
system only.

Copy the same validated files back to the matching Stack Content template
package directory so future renders retain the correction. Review any existing
template changes first. A commit/push can be done later; retain the archive,
checksum, and change record until then. The existing
`refresh-workspace-controls.py` helper updates generated controls, not package
overlays: a control refresh alone does not deliver this fix.

## Command references

- [Spack 1.2.2 install command and concrete-spec selection](https://github.com/spack/spack/blob/v1.2.2/lib/spack/spack/cmd/install.py)
- [Spack 1.2.2 location command](https://github.com/spack/spack/blob/v1.2.2/lib/spack/spack/cmd/location.py)
- [Spack 1.2.2 repository precedence and recipe inheritance](https://github.com/spack/spack/blob/v1.2.2/lib/spack/docs/repositories.rst)
- [Spack 1.2.2 environment locks and concretization](https://github.com/spack/spack/blob/v1.2.2/lib/spack/docs/environments.rst)
