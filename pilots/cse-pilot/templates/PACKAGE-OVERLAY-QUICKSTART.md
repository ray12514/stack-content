# Offline package fixes in an existing CSE trial

**Checking a teammate's existing correction does not require a tool update.**
Start with [Inspect an existing correction with the installed tools](#inspect-an-existing-correction-with-the-installed-tools).
Use the current workspace, confirm which recipe Spack sees, then explicitly
reconcretize and retry only the failing environment.

When the recovery helpers are already available, their workflow stays in this workspace: `overlay apply` or
`overlay edit`, `concretize --environment COMPILER/LANE --reconcretize`, then
`resume --environment COMPILER/LANE`. It retains backups internally and never
creates a new operator workspace. See Stack Content's
`pilots/cse-pilot/OVERLAY-RECOVERY.md`. The manual steps below remain available
for diagnosis. `scripts/overlay-recovery.py` is an optional isolated experiment;
it is not required for the normal correction loop.

Use this guide to inspect one failure, install a reviewed recipe correction,
retry that package with Spack, and carry the correction to another workspace.
Git, GitLab, Stack Composer, and a new workspace render are not needed for
this loop. Keep this file with the workspace when working offline.
Commands target the current Spack 1.2.2 / repository API v2 workspace; verify
the version and effective configuration on the receiving system.
Steps 1–7 are the common process for every trial system and package. Set the
system's workspace, environment, package name, and package module each time.
The [Blueback netlib-lapack example](#worked-example-blueback-cce-netlib-lapack)
at the end supplies one set of those inputs and the evidence for that report.

An **overlay** is our higher-priority `cse_trials` Spack recipe repository.
Spack selects a whole recipe from it; it does not merge two `package.py` files.
Our usual recipe subclasses the pinned builtin class to retain upstream
behavior and add a narrow fix. Transfer the complete local package directory,
including every patch/support file, while preserving any existing local fixes.

This procedure is for an unfinished, unaccepted build trial. Coordinate edits
with anyone using the same package repository or locks. For an accepted
release, make a new candidate instead of changing its recorded inputs.
Keep correcting the same unfinished workspace. Preserve the previous inputs
and lock in recovery records, repeat review for the changed environment, and
return the tested correction to authored content before release acceptance.
An accepted or published release needs a separate release record.

For partially completed workspaces, record which environments and packages
are already built before applying anything. Preserve their locks, prefixes,
views and modules. Limit the retry to the failing candidate and its reviewed
dependency impact; do not reconcretize every environment or refresh completed
modules as part of overlay delivery. If the affected dependency set reaches
completed work, report that impact and retain its current lock and prefix until
that environment is explicitly selected for reconcretization. A compiler-specific
guard alone does not prove isolation.

## Inspect an existing correction with the installed tools

This is the starting point when someone says they already fixed a package in
an older running trial. No Stack Content pull, Stack Composer rebuild, Cluster
Inspector update, Spack upgrade, control refresh, or new render is needed to
inspect and retry that correction. Check the tools and paths already recorded
for this workspace; "check" does not mean advance them to newer versions.

The example below investigates GSL in `cce/core`. Substitute the actual failing
environment on your system. Keep completed GCC locks and installations intact.
Coordinate with your teammate so neither operator changes recipes or solves the
same environment during the other's inspection/retry.

**1. Enter the existing prepared shell.**

```bash
cd /absolute/path/to/existing-workspace
./cse-build login shell
```

Continue in that shell if it is already open. The existing `cse-build login
tmux` command is another entry point when supported by that launcher. Plain
`tmux` only keeps a session alive; it does not activate Spack or prepare the
workspace by itself. The prepared shell sets the runtime and paths. The `-e`
argument below selects the specific environment without a separate
`spack env activate` command.

**2. Check this workspace's runtime, repository, and store paths.**

```bash
export TARGET_ENV="$CSE_BUILD_WORKSPACE/environments/cce/core"
export PACKAGE_DIR="$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials/packages/gsl"
type -a spack
spack --version
spack location --spack-root
spack -e "$TARGET_ENV" repo list
spack -e "$TARGET_ENV" config get repos
spack -e "$TARGET_ENV" config get config
spack -e "$TARGET_ENV" config get modules
cat "$TARGET_ENV/spack.yaml"
```

Compare these with the existing workspace's `BUILDER-HANDOFF.md` and recorded
configuration. `builtin` is a **recipe repository**; the install tree is the
**package store**. Check both, plus the stage/cache paths. Require `cse_trials`
to resolve to this workspace's overlay repo ahead of builtin. Check that the
selected view and module output paths belong to the intended CCE environment.

**3. Read what was deployed and prove recipe selection.**

```bash
ls -l "$PACKAGE_DIR"
less "$PACKAGE_DIR/package.py"
spack -e "$TARGET_ENV" location --package-dir gsl
PYTHONDONTWRITEBYTECODE=1 spack -e "$TARGET_ENV" python -c \
  'import inspect, spack.repo; cls = spack.repo.PATH.get_pkg_class("gsl"); print(cls.__module__); print(inspect.getfile(cls))'
spack -e "$TARGET_ENV" find -c -d -L -N -v gsl
```

Read any referenced local patches too, and compare the deployed files with the
complete correction your teammate intended to deliver. If the file is absent
or the selected class comes from builtin/another workspace, resolve that path
or delivery problem before solving. A change in a Stack Content checkout alone
does not update this deployed directory. A complete copied builtin recipe is
valid as an overlay; subclassing is a maintenance choice, not a registration
requirement.

The recipe-path check shows current repository selection; `find` shows the
existing concrete graph. They can disagree before reconcretization. Inspect
both GSL versions if this environment contains more than one. The generated
`.spack-env/repos` tree is a concrete recipe snapshot, not a mirror of every
overlay. Do not edit it. Starting another build against the old lock does not
by itself switch `builtin.gsl` to `cse_trials.gsl`.

**4. Retain the selected inputs, then reconcretize that environment.**

If the intended correction is already deployed, leave it in place; there is
no need to reapply it or install a helper first. If it needs correction, use
Steps 2–4 below to retain and review the complete package before replacing it.
Before solving, create a new record for the current selected inputs:

```bash
REVIEW_RECORD=$(mktemp -d "$CSE_BUILD_WORKSPACE/gsl-review.XXXXXX")
(
  set -e
  test -n "$REVIEW_RECORD" && test -d "$REVIEW_RECORD"
  cp -p "$TARGET_ENV/spack.yaml" "$REVIEW_RECORD/spack.yaml.before"
  cp -p "$TARGET_ENV/spack.lock" "$REVIEW_RECORD/spack.lock.before"
  cp -a "$PACKAGE_DIR" "$REVIEW_RECORD/overlay-before"
  spack -e "$TARGET_ENV" find -c -d -L -N -v > "$REVIEW_RECORD/graph.before.txt"
)
if [ "$?" -ne 0 ]; then
  printf 'Input capture failed; do not reconcretize. Reopen the prepared shell after resolving it.\n' >&2
  exit 1
fi
printf 'Keep this review directory: %s\n' "$REVIEW_RECORD"
```

Require that capture to succeed. Keep the original failure log as well. Then:

```bash
spack -e "$TARGET_ENV" concretize -f --fresh -j 1
```

This forces a new solve of **only `cce/core`**, without reusing old concrete
specs during the solve. It does not delete installed packages; matching
installed hashes remain reusable at installation. It can change other hashes
within that environment. After a successful solve, review the resulting graph:

```bash
spack -e "$TARGET_ENV" find -c -d -L -N -v > "$REVIEW_RECORD/graph.after.txt"
diff -u "$REVIEW_RECORD/graph.before.txt" "$REVIEW_RECORD/graph.after.txt"
spack -e "$TARGET_ENV" find -c -d -L -N -v gsl
```

`diff` status 1 means differences were found. Confirm `cse_trials.gsl`, the
intended versions and CCE compiler dependencies, and explain any other changed
nodes before building. If the solve fails, retain its output and the backup;
do not build or delete the lock to work around it. These manual commands do
not provide the newer helper's automatic rollback or transaction records.

**5. Retry this environment in its normal compute allocation.**

Exit the login builder shell and enter the site's normal compute allocation.
From the same workspace, open its compute shell and reselect the environment:

```bash
cd /absolute/path/to/existing-workspace
./cse-build compute shell
export TARGET_ENV="$CSE_BUILD_WORKSPACE/environments/cce/core"
spack -e "$TARGET_ENV" install --only-concrete --no-add --fail-fast --keep-stage -j 1
```

This installs the selected lock and reuses matching installed packages. It does
not reconcretize, run other environments, or perform a broad `cse-build` module
refresh/publication. Direct Spack still follows this environment's configured
view and module settings: concretize/install can update its views, and install
hooks can write its package modules. This is not a presentation-isolated retry.

Retain the build log. The previously failing stage passing with CCE is the
build-fix check. If the corrected package is reused from a store or binary
cache, that is not a new compile test; retain matching successful CCE evidence
or use the focused source retry in Step 6 below. Do not uninstall shared
packages to force it. Review other environments for the corrected package and
its dependents, but do not reconcretize all CCE or GCC locks automatically.

If this workspace already has a recovery transaction or reports inventory
drift, use its existing recovery procedure. Direct Spack does not acknowledge
the helper's pending-impact records; do not use this route to bypass a gate.
Tool/control upgrades remain a separate task when a capability is actually
needed, not a prerequisite for inspecting the teammate's change.

## Updating an existing workspace

Copy the reviewed files into the **existing absolute workspace path** supplied
to that system's builder. Choose the destination according to the update:

| Update | Destination and next step |
| --- | --- |
| This process guide | `<workspace>/PACKAGE-OVERLAY-QUICKSTART.md`; documentation is ready to use immediately |
| One package correction | `<workspace>/package-repos/spack_repo/cse_trials/packages/<package-module>/`; follow Steps 2–6 for backup, complete file copy, recipe selection, lock recovery, and testing |
| Generated shell/verifier controls | Use the reviewed control-refresh procedure in `STACK-COMPOSER-UPDATE.md` from Stack Content; its declared control files do not include package overlays |

A source-checkout pull and a deployed-workspace update are separate operations.
After obtaining a guide or fix, explicitly copy it to each receiving workspace.
Keep each system's own workspace path, compiler/catalog configuration, and
locks. There is no automatic propagation to other systems, and this process
does not reinitialize or replace their workspace trees. Record which file
revision was delivered and which package correction was tested on each system.
Treat a generated-control refresh separately: review its allowlisted diff and
test it in a disposable copy before using it on a partially completed trial.
Do not advance Spack, the builtin pin, or the installed Composer merely to
receive a documentation or package-overlay update.

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
| `./cse-build compute install --surface platform` (or `shared`) | Optional full compiler-surface resume after the focused package retry |
| `refresh-workspace-controls.py` | Optional generated-control update, documented in Stack Content's `pilots/cse-pilot/STACK-COMPOSER-UPDATE.md`; does not copy package overlays |

The `scripts/workspace-overlay.py` and `scripts/workspace-build.py` helpers
automate the normal correction loop in this workspace with retained backups. The manual copy and
archive steps below remain available for diagnosis. Healthy existing
workspaces only need a copy of this Markdown guide; they do not need a render
or control refresh to read it or follow the manual overlay procedure.

## Reviewed byte inventories in newly prepared candidates

New candidates include `scripts/verify-overlay-inputs.py` and a reviewed
`package-repos/overlay-inventory.json`. The workspace verifier checks this
inventory before its existing compiler and concrete-graph checks. It covers
`repo.yaml`, all six shipped recipes (`cce`, `cmake`, `dakota`, `hdf5`,
`ncurses`, `zlib`), and their patch/helper files. New packages use the same
inventory; no package-specific verifier code is needed.

An older trial without an inventory can use the current standalone
`workspace-overlay.py apply` after reviewing the existing recipe tree and complete
correction. That explicit operation records the previous inventory absence,
validates the complete tree, and admits its inventory without replacing the
workspace or changing the builtin pin. The old launcher does not automatically
gain the new build gate: use the companion selected concretize/resume helpers.
A later controls refresh must satisfy its declared helper/inventory prerequisites.
A presentation-only refresh can leave the existing controls in place.

After preparing the complete correction in the **unaccepted candidate**, run
the shipped helper directly; it needs Python 3.6+ and no Spack imports:

```bash
cd /absolute/path/to/unaccepted-candidate
python3 scripts/verify-overlay-inputs.py --check
# After editing candidate recipe/patch files, choose a new review file outside
# package-repos. The helper refuses to overwrite any existing candidate file.
python3 scripts/verify-overlay-inputs.py \
  --candidate /absolute/path/to/review/overlay-inventory.candidate.json
diff -u package-repos/overlay-inventory.json \
  /absolute/path/to/review/overlay-inventory.candidate.json
```

A nonzero check after intentional edits is expected until review. Review the
actual recipe/patch diff as well as the inventory diff and retain both in the
change record. After the candidate's complete inputs are approved, explicitly
adopt the reviewed inventory and check again:

```bash
cp /absolute/path/to/review/overlay-inventory.candidate.json \
  package-repos/overlay-inventory.json
python3 scripts/verify-overlay-inputs.py --check
python3 scripts/verify-lockfiles.py --workspace-only
```

After adopting an inventory, reopen the prepared builder shell with
`./cse-build login shell` (or the selected compute context) before invoking
Spack again. In an already prepared candidate shell, sourcing
`env/setup-build-env.sh` also recomputes its cache selection. New launchers
scope `SPACK_MISC_CACHE_PATH` by builder, resolved local-repository paths and
reviewed inventory digest. Moving a candidate or admitting changed bytes gets
a separate cache, avoiding stale Spack patch indexes under a reused namespace.
`python3 scripts/verify-overlay-inputs.py --cache-key` displays the identity
used for this purpose. No old cache is deleted. Existing trials only adopt
these controls through their explicit reviewed preparation procedure.

Checking never updates expected digests. Missing, changed, unrecorded,
non-regular, or symlinked files fail; unsafe paths fail. Keep logs, backups,
candidate inventories and Python bytecode outside `package-repos`. Set
`PYTHONDONTWRITEBYTECODE=1` when importing local recipes for inspection.
The helper validates simple API-v2 `repo.yaml` identity and literal local
`patch(...)` references without executing recipes. Dynamic patch filenames
need an explicit extension of this static contract before admission. All
other support files are covered by their recorded bytes; arbitrary Python
file accesses, inherited directives, remote resource availability, effective
Spack repository order, imported classes and patch applicability still require
the real Spack selection/build checks below. A passed inventory is a byte
identity check, not package correctness or release approval.

The expected inventory is itself a reviewed release input, not a signature or
an independent trust authority. Retain the admitted source revision/archive
and review record. Return both the complete corrected files and the reviewed
inventory to authored Stack Content before preparing the releasable candidate.

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

Select the environment and package that actually failed. Use the environment
directory name from this workspace, such as `cce/common` or `gcc/serial`;
do not infer the lane from the package name. The package's Spack name and API
v2 Python module directory are separate inputs:

```bash
export ENVIRONMENT="<compiler-environment-name>/<lane>"
export PACKAGE_NAME="<spack-package-name>"
export PACKAGE_MODULE="<python-package-module>"
export TARGET_ENV="$CSE_BUILD_WORKSPACE/environments/$ENVIRONMENT"
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
| Source for future renders | `<stack-content>/pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/packages/<package-module>/` |

`cse_trials` must precede `builtin` and resolve inside this workspace. Do not
edit the cached builtin recipe or add a user-level repo. For example, Spack
API v2 uses `netlib_lapack` for the directory/import and `netlib-lapack` for the
spec name, while `zlib` uses `zlib` for both. Confirm the exact module directory
against the pinned repository; names starting with digits need a prefix too.
Read the original file with `less "$BUILTIN_RECIPE"`. Read any existing local
recipe before preparing a replacement.

## 2. Save the evidence before editing

Choose the full failed hash from the listing, including the correct version,
compiler, variants, and dependencies. Do not select the first match if several
appear. Confirm the selection from the lock and original build log.
Choose a new record directory on shared storage writable from both login and
compute nodes; a node-local record will not follow you into the allocation.
Use a separate new directory for each affected environment, for example one
directory per compiler/lane beneath a shared change directory. The filenames
below describe only the selected environment. Before changing the shared
recipe repository, repeat the capture for every affected environment and keep
the path-to-environment mapping. Never reuse one `OVERLAY_RECORD` for two locks.

```bash
export FAILED_HASH="<full-failed-hash-without-leading-slash>"
export OVERLAY_RECORD="<absolute-new-shared-record-directory-for-this-environment>"
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
`spack-build-env.txt` from that stage into the record. Retain the first failing
command and its full diagnostic, plus generated files needed to reproduce it:
for example, a CMake cache/link command for a link failure or `config.log` for
a configure failure. Use the actual paths found in the log; a recipe can have
several build directories. Choose evidence from the failure, not from a
different package's example or an earlier nonfatal warning.

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
imports and subclasses the selected package's pinned builtin class, then adds
a local `patch(...)` with an evidenced `when` condition. Take the exact class
and import path from that recipe. Inspect the pinned builder before overriding
recipe methods, and preserve any existing overlay corrections.

Review the complete candidate, parse its Python, and dry-run source patches
against a disposable pristine copy of the exact package source. Existing
builtin patches and patch order matter. Keep a short `CHANGE.md` in the record:
input revisions, file list, cause/scope, commands, before/after results, and
which systems/compiler versions were actually tested.

## 4. Copy the reviewed files and prove selection

Set the explicit list to the candidate's actual filenames. A recipe-only
correction uses just `package.py`. Do not run this block until the candidate
has been prepared and reviewed. List files relative to the candidate root,
including subdirectories such as `patches/fix.patch` when present.

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
    install -d -m 2770 -g "$CSE_GROUP" "$(dirname "$PACKAGE_DIR/$overlay_file")"
    install -m 0660 -g "$CSE_GROUP" "$OVERLAY_CANDIDATE_DIR/$overlay_file" "$PACKAGE_DIR/$overlay_file"
  done
  spack -e "$TARGET_ENV" location --package-dir "$PACKAGE_NAME"
  spack -e "$TARGET_ENV" python -c 'import inspect, os, spack.repo; cls = spack.repo.PATH.get_pkg_class(os.environ["PACKAGE_NAME"]); print(inspect.getfile(cls))'
)
```

Require successful copying and both paths to identify
`$PACKAGE_DIR/package.py` (or its enclosing directory for `location`). If a
copy fails, restore or finish the complete file set before building. Review
the block's nonzero exit status; selection commands run only after all files
copy successfully. This is not an atomic replacement: other builders must
remain stopped until the entire file set and selection checks pass. Review
any superseded files explicitly; backups belong outside `packages/`.
The block uses ordinary-file mode `0660` for recipes and patches. If a reviewed
support file must be executable, install that specific file with mode `0770`
and record that requirement for the receiving system.

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
Review every environment containing the corrected package and its affected
dependents. Do not automatically run either command over all eight environments.
For each additional environment, select its own `TARGET_ENV` and the matching
`OVERLAY_RECORD` captured in Step 2 before writing the after-listing below.
Preserve the original before-listing; do not rerun the capture over it.

```bash
spack -e "$TARGET_ENV" find -c -d -L -N -v > "$OVERLAY_RECORD/graph.after.txt"
diff -u "$OVERLAY_RECORD/graph.before.txt" "$OVERLAY_RECORD/graph.after.txt"
spack -e "$TARGET_ENV" find -c -d -L -N -v "$PACKAGE_NAME"
```

`diff` status 1 means differences were found. Confirm `cse_trials`, the intended
recipe/patch identity, and affected dependent hashes. Record the new hash.
Once all affected locks have been recovered, run the existing workspace lock
check (`./cse-build login verify`) before resuming the trial. This guide does
not expand the full release validation procedures.

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

For a configure, compile, or link failure, the corrected build passing the
original failing stage with the same compiler is the recovery test. A CCE
failure needs a CCE retry. For a runtime defect, rerun the failing operation
against the corrected prefix with the relevant flags and result check. Add
consumer checks when the defect or release acceptance requires them; they are
not a mandatory extra step for every build correction. Record results in
`CHANGE.md`, naming the system and compiler tested; do not mark unrun checks
as passed.

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
    mkdir -p "$(dirname "$OVERLAY_RECORD/outgoing/$PACKAGE_MODULE/$overlay_file")"
    cp -p "$PACKAGE_DIR/$overlay_file" "$OVERLAY_RECORD/outgoing/$PACKAGE_MODULE/$overlay_file"
  done
  cp -p "$OVERLAY_RECORD/CHANGE.md" "$OVERLAY_RECORD/outgoing/CHANGE.md"
  tar -czf "$OVERLAY_RECORD/$PACKAGE_MODULE-overlay.tar.gz" \
    -C "$OVERLAY_RECORD/outgoing" CHANGE.md "$PACKAGE_MODULE"
  ( cd "$OVERLAY_RECORD"; sha256sum "$PACKAGE_MODULE-overlay.tar.gz" > "$PACKAGE_MODULE-overlay.tar.gz.sha256" )
)
```

Copy the archive and checksum with the site's approved file-transfer method,
removable media, or `scp` when a connection is available. On the receiving
system, place them outside its package repo. Set the module from the reviewed
transfer record and extract into a new staging directory:

```bash
cd "<directory-containing-received-archive-and-checksum>"
export PACKAGE_MODULE="<python-package-module>"
export RECEIVED_DIR="<absolute-new-extraction-directory>"
sha256sum -c "$PACKAGE_MODULE-overlay.tar.gz.sha256"
tar -tzf "$PACKAGE_MODULE-overlay.tar.gz"
# After checksum success and checking the listed CHANGE.md/package files:
mkdir "$RECEIVED_DIR"
tar -xzf "$PACKAGE_MODULE-overlay.tar.gz" -C "$RECEIVED_DIR"
```

Use a new extraction directory and require each command to succeed. Review
`CHANGE.md`, the file list, and differences from its
existing overlay. Compare that workspace's Spack/builtin revisions and affected
compiler/version before applying. A different builtin pin requires adaptation
and review, not an assumption that the subclass is compatible.

Repeat Steps 1–6 using the **receiving** workspace's paths and a new record;
in Step 4 set `OVERLAY_CANDIDATE_DIR="$RECEIVED_DIR/$PACKAGE_MODULE"` (restore
the recorded absolute `RECEIVED_DIR` path after changing shells) and set
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

## Worked example: Blueback CCE netlib-lapack

This is one application of Steps 1–7. After entering Blueback's prepared
workspace shell, use these three selections in Step 1:

```bash
export ENVIRONMENT="$PLATFORM_COMPILER_NAME/common"
export PACKAGE_NAME="netlib-lapack"
export PACKAGE_MODULE="netlib_lapack"
```

The current roster places standalone LAPACK roots in Common and uses LAPACK
under MPI dependents, including Dakota. Confirm the actual failed environment;
review Common and affected MPI locks when a LAPACK recipe changes. Derive all
remaining paths with Step 1's generic commands. The deployed destination is
`<Blueback-workspace>/package-repos/spack_repo/cse_trials/packages/netlib_lapack/`.

The 2026-09-14 photo appears to identify `netlib-lapack@3.12.1`. It shows CMake
configuration/generation finishing, followed by a `multiple definition`
diagnostic while linking the BLAS shared library in a CCE/Fortran build. The
exact duplicate symbol and cause are not established from the photo. Capture
the full build log, both object names, the complete failing link command,
`CMakeCache.txt`, and the failing build directory's
`BLAS/SRC/CMakeFiles/blas.dir/link.txt`. The recipe may have separate static and
shared build directories; use the actual failed one. The GNU `-sinteger64`
workaround in Blueback's other notes addresses a different symptom.

For an eventual source fix, the overlay structure would import `NetlibLapack`
from `spack_repo.builtin.packages.netlib_lapack.package` and subclass it as
`NetlibLapack`. The actual change and `when` condition still require diagnosis.
No deployable fix or successful Blueback CCE retry is claimed here. The recovery test is the formerly failing BLAS link completing in the
CCE build. A numerical consumer remains part of any separately required
runtime acceptance.

After that correction is validated, Step 7 creates
`netlib_lapack-overlay.tar.gz`; the receiving system sets
`PACKAGE_MODULE=netlib_lapack` and applies the same general import/retest steps.
Other packages use their own names, recipes, evidence, and acceptance checks.

## Command references

- [Spack 1.2.2 install command and concrete-spec selection](https://github.com/spack/spack/blob/v1.2.2/lib/spack/spack/cmd/install.py)
- [Spack 1.2.2 location command](https://github.com/spack/spack/blob/v1.2.2/lib/spack/spack/cmd/location.py)
- [Spack 1.2.2 repository precedence and recipe inheritance](https://github.com/spack/spack/blob/v1.2.2/lib/spack/docs/repositories.rst)
- [Spack 1.2.2 environment locks and concretization](https://github.com/spack/spack/blob/v1.2.2/lib/spack/docs/environments.rst)
