# Manual CSE package overlay workflow

For a teammate's correction in an existing trial, start with
[inspection and retry using the installed tools](templates/PACKAGE-OVERLAY-QUICKSTART.md#inspect-an-existing-correction-with-the-installed-tools).
Inspect the deployed files first; updating tools is not a prerequisite.

For the helper-assisted same-workspace correction loop, start with
[Overlay recovery](OVERLAY-RECOVERY.md). It coordinates inspection, solving and
retry while retaining the existing workspace. This document supplies the manual
diagnosis and package-authoring detail.

Start with the [offline package fix quickstart](templates/PACKAGE-OVERLAY-QUICKSTART.md)
for workspace navigation, a reusable agent handoff, a direct one-package Spack
retry, and archive/copy transfer between systems without Git. That guide is
also included in generated workspaces as `PACKAGE-OVERLAY-QUICKSTART.md`.
This document provides the detailed recipe, lock, and release background.

## Bring the guide into an existing workspace

The operational guide lives with the recipes in Stack Content so generated
workspaces can carry it offline. Stack Planning's common runbook points here
and remains the source for the overall trial/release process.

For a healthy existing workspace, copy just the guide. In a machine with an
existing Stack Content checkout, fetch the reviewed documentation ref
and extract the file without switching branches or updating workspace controls:

```bash
export CONTENT="<absolute-existing-stack-content-checkout>"
export BUILD_WORKSPACE="<absolute-existing-trial-workspace>"
export DOC_REF="codex/recovery-hardening"  # Reviewed recovery and module workflow branch.
git -C "$CONTENT" fetch origin "$DOC_REF"
git -C "$CONTENT" show FETCH_HEAD:pilots/cse-pilot/templates/PACKAGE-OVERLAY-QUICKSTART.md \
  > "$CONTENT/PACKAGE-OVERLAY-QUICKSTART.download.md"
less "$CONTENT/PACKAGE-OVERLAY-QUICKSTART.download.md"
# After a successful fetch/show, copy the reviewed documentation file:
cp "$CONTENT/PACKAGE-OVERLAY-QUICKSTART.download.md" \
  "$BUILD_WORKSPACE/PACKAGE-OVERLAY-QUICKSTART.md"
```

Set `DOC_REF` to the reviewed branch/tag/commit; the default above identifies
the current trial documentation branch. If no checkout exists, clone the
approved Stack Content origin first. Its current public GitHub publication is
available without authentication:

```bash
git clone --single-branch --branch codex/simplified-render-plan \
  https://github.com/ray12514/stack-content.git
```

Then set `CONTENT` to that checkout's absolute path and use the delivery block
above. A private origin instead requires authenticated HTTPS or SSH. On a
disconnected target, copy this Markdown file over the approved transfer route
instead. Stack Planning is optional for this package-fix loop.

Only the Markdown file is copied into the workspace. No recipe, environment,
lock, compiler setting, or installed package is changed by this delivery step.
The quickstart distinguishes manual edit/copy/retry commands from existing
optional shell and control-refresh helpers.

For a package update, copy the reviewed complete local recipe and its support
files to `<workspace>/package-repos/spack_repo/cse_trials/packages/<package-module>/`
using quickstart Steps 2–6, or receive a transfer archive using Step 7. That
copy must be followed by recipe selection, affected-lock recovery, and a local
package test. Repeat with each receiving system's own workspace and inputs.
A repository pull alone does not update any generated workspace. Neither a
guide copy nor an overlay copy requires workspace regeneration; the
control-refresh helper is for a separate generated-control update.

## Detailed workflow

Newly prepared candidates use the generic byte-inventory gate described in
the quickstart's [inventory procedure](templates/PACKAGE-OVERLAY-QUICKSTART.md#reviewed-byte-inventories-in-newly-prepared-candidates).
Existing running trials are not automatically upgraded to that gate. To
update authored expectations after reviewing an overlay change, run from the
Stack Content root:

```bash
python3 pilots/cse-pilot/templates/scripts/verify-overlay-inputs.py \
  --candidate /absolute/path/to/review/overlay-inventory.candidate.json
diff -u pilots/cse-pilot/templates/package-repos/overlay-inventory.json \
  /absolute/path/to/review/overlay-inventory.candidate.json
# After reviewing the recipe/support-file and inventory diffs:
cp /absolute/path/to/review/overlay-inventory.candidate.json \
  pilots/cse-pilot/templates/package-repos/overlay-inventory.json
python3 pilots/cse-pilot/templates/scripts/verify-overlay-inputs.py --check
```

Commit or archive the complete authored files and inventory together after
review. Rendering and verification do not regenerate expected digests from
deployed bytes. The candidate command records current bytes for review; it
does not approve them, change locks, or import Spack recipes.

New build values retain builtin release tag `v2026.06.0` as admission evidence
and render its resolved commit
`d4f7c711a6a42f1c4d551c8fd10fce9a11340a81` as the active pin. This is the
resolved tag identity recorded in the
[snapshot admission research](../../../stack-planning/docs/spack_repository_snapshot_admission_research_v1.md#immutable-identity-recommendation).
Do not change an existing trial's pin to receive an overlay or documentation
update. Current templates require `package_repo.commit` in values; a temporary
render-only values copy used to stage a presentation-only refresh must provide
this field. Use `prepare-existing-workspace-values.py --builtin-commit
<reviewed-full-commit>` alongside its normal arguments when the source values
lack it. The helper preserves an existing recorded commit and rejects a
conflicting override; it does not select a new pin silently. Keep the existing
trial's original values/configuration and active pin intact; select only the
reviewed presentation files for delivery.

This procedure explains how to obtain a corrected package recipe, review its
scope, place its files manually in an existing CSE workspace, and validate the
result. The files may be prepared by any authoring method; the installation and
review steps are the same.

The generated workspace package repository is the working location for
system-local diagnosis:

```text
<workspace>/package-repos/spack_repo/cse_trials/
```

The corresponding Stack Content tree is the canonical source for future
workspace renders:

```text
stack-content/pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/
```

Do not edit Spack's cached `builtin` repository. A change made only in the
generated workspace is temporary and must not be treated as part of an
accepted release.

## What an overlay actually does

Spack searches the configured repositories in precedence order. For an
unqualified package name, it selects one recipe from the first repository that
provides that package. It does not merge two `package.py` files or splice the
changed lines into the builtin recipe automatically.

Our usual overlay imports and subclasses the pinned builtin package class.
Python inheritance preserves its existing behavior, while the subclass adds
patch directives or narrowly overrides behavior. Packages absent from
`cse_trials` continue to resolve from `builtin`. The repository is already
registered by the workspace; adding a package does not require `spack repo add`
or editing user configuration.

The package recipe is named `package.py`, inside the package's own directory:

```text
<workspace>/package-repos/spack_repo/cse_trials/
  repo.yaml                      namespace: cse_trials; api: v2.0
  packages/
    zlib/
      package.py
      cce-lld-version-map.patch
```

A patch file alone is not an overlay: `package.py` must reference it. A new
`package.py` alone is incomplete if it references patch files that were not
supplied. If the package already has an overlay, produce an updated complete
local recipe that preserves the existing corrections. Do not overwrite it with
a new one-fix skeleton. The current zlib directory already has an overlay.

The manual sequence is: capture the failure and exact inputs; prepare a complete
candidate against the pinned builtin and current local recipe; review its scope;
back up and copy the reviewed files; confirm recipe selection; recover only the
selected affected lock and check source availability; build and validate; then
retain a transferable correction and copy it back to the canonical template
repository. A Git commit/push can follow later. The sections below
provide the commands and a reusable request for obtaining the candidate files.

## Release boundary

Coordinate with the other builder before changing a shared recipe or lock;
stop processes that use the affected workspace inputs. A CCE-only condition
does not make an edit to the shared recipe repository invisible to GCC builds.
Inspect the affected locks and their hashes rather than assuming isolation.

Develop an overlay in place only while the affected lock set is an unaccepted
release candidate. If the lock set was accepted or its binaries were pushed to
a release build cache, preserve that release and create a new one.

An unfinished trial uses this same workspace for corrections. Preserve each
previous lock and input revision in its recovery record, invalidate the affected
lock review, reconcretize only the selected environment, and repeat its build.
Review other affected locks before building them again. Installation alone does
not freeze an unfinished trial; accepted or published releases remain immutable.
Return the tested source correction to authored content before acceptance.

An overlay is complete only when all of the following are retained together:

1. The original failure evidence.
2. A repeatable command that produces the failure.
3. The overlay `package.py` and any patch files.
4. Before and after concrete hashes for every affected environment.
5. The successful rerun of the original failing command.
6. Package-specific binary or runtime validation.
7. The recovery commands used on the system.
8. The complete transfer archive, checksum, and change record; the matching
   canonical Stack Content files, and their commit when Git integration resumes.

## 1. Capture the failure

Before changing a recipe or environment, record:

1. Package name and version.
2. Compiler family and version.
3. Variants and important dependencies.
4. Environment and lane.
5. Concrete hash.
6. Complete build log.
7. Exact failing command and its standard error.
8. Exact Spack version/commit, builtin repository pin/commit, the pinned
   builtin recipe, and any existing local recipe and patch files.
9. Relevant generated files such as `link.txt`, `CMakeCache.txt`,
   `config.log`, or the generated Makefile.

Sanitization may replace private directory prefixes, but it must preserve
library names, compiler and linker options, error messages, and the order of
arguments. Removing the paths from a colon-separated RPATH can make a valid
RPATH look like a series of empty entries, so note explicitly when that
transformation was made.

Create the smallest practical command that reproduces the reported failure.
For a parallel build failure, rerun only the failing target with one build job
and verbose output. Do not begin with a package-wide workaround when the
failing command is not yet known.

## 2. Identify the correction layer

Place the correction at the narrowest layer that owns the failure:

| Evidence | Correction layer |
| --- | --- |
| Upstream source or configure defect | Source patch in the package overlay |
| Builtin Spack recipe defect | Subclass and override the smallest recipe method |
| Version, variant, provider, or dependency policy | Roster, `packages.yaml`, or environment manifest |
| Incorrect compiler metadata demonstrated by unrelated packages | Compiler package overlay |
| Shell variable used only to expose the cause | Diagnostic only, not the released fix |

For example, zlib requesting `+shared` but silently installing only `libz.a`
is a zlib package contract failure. It must not be hidden by changing Perl or
by exporting a global linker flag.

## 3. Inspect the exact recipe and repository pin

Enter the existing workspace's prepared login shell:

```bash
cd "<absolute-shared-workspace-path>"
./cse-build login shell
```

Inside that shell, select the actual affected environment and package. The
example below selects CCE Core and zlib; choose the GCC name or another lane
when that is where the recorded failure occurred:

```bash
export ENVIRONMENT="$PLATFORM_COMPILER_NAME/core"
export TARGET_ENV="$CSE_BUILD_WORKSPACE/environments/$ENVIRONMENT"
export PACKAGE_NAME="zlib"
export PACKAGE_MODULE="zlib"
export OVERLAY_REPO="$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials"
export PACKAGE_DIR="$OVERLAY_REPO/packages/$PACKAGE_MODULE"

spack --version
spack -e "$TARGET_ENV" config get repos
spack -e "$TARGET_ENV" repo list
spack -e "$TARGET_ENV" find -c -d -L -N -v "$PACKAGE_NAME"
```

The `cse_trials` repository must appear before `builtin`, resolving inside this
workspace. Current generated workspaces use Spack 1.2.2 and the builtin
`spack-packages` tag `v2026.06.0`; confirm the effective configuration rather
than assuming that a different workspace has those same pins.

Resolve the builtin repository explicitly, then inspect its recipe and commit:

```bash
BUILTIN_REPO="$(spack -e "$TARGET_ENV" location --repo builtin)"
BUILTIN_RECIPE="$BUILTIN_REPO/packages/$PACKAGE_MODULE/package.py"
printf 'Pinned builtin recipe: %s\n' "$BUILTIN_RECIPE"
git -C "$BUILTIN_REPO" rev-parse HEAD
sed -n '1,300p' "$BUILTIN_RECIPE"
```

Read the rest of the file when needed, including builder classes, callbacks,
and referenced patches. Also read the existing local `$PACKAGE_DIR/package.py`
and its patch files if that directory exists. Do not edit Spack's cached `builtin` repository.

Spack repository API v2 uses Python module names for directories and imports.
For example, `netlib-lapack` uses `netlib_lapack`, and a name beginning with a
digit requires the appropriate underscore prefix. Keep the package name,
module directory, import path, and class name consistent with the pinned recipe.

A newer upstream fix can be useful evidence. Record its exact source revision
and adapt the specific change to the pinned recipe and package source. Do not
replace the pin with a moving branch or copy a newer complete recipe without
checking its dependencies, build-system API, variants, and other assumptions.
The exact package source version and Spack recipe repository revision are
separate inputs.

## 4. Prepare and manually install the correction

First obtain a reviewable candidate containing:

1. A complete replacement **local overlay** `package.py`, including existing
   local corrections that still apply.
2. Every referenced local patch/support file and an explicit file list.
3. A diff against the current local overlay, or a clear statement that this is
   a new package in `cse_trials`.
4. The failure cause, supported version/compiler/variant scope, pinned upstream
   source references, expected affected environments, and validation commands.

The [recipe correction request](#recipe-correction-request) below is a reusable
way to request those deliverables without prescribing how they are authored.

### Source patch example

The existing zlib overlay illustrates the inheritance pattern:

```python
from spack_repo.builtin.packages.zlib.package import Zlib as BuiltinZlib

from spack.package import *


class Zlib(BuiltinZlib):
    """Zlib linker compatibility required by the CCE trial surface."""

    patch("cce-lld-version-map.patch", when="@1.2.13:1.3.2+shared %cce")
```

This selects the local Zlib class, inherits the builtin recipe, and adds the
patch only for the stated source versions, `+shared`, and CCE. It is an example
of the current correction, not a generic fix to apply to a new error.

Choose a `when` condition from evidence. Include the package version/range,
compiler/version, variants, platform, or target only where they explain the
failure. If only one compiler version was tested, do not claim a compiler-wide
range without support. A package-specific defect normally belongs in that
package's overlay; change compiler metadata only when evidence establishes a
compiler-wide cause.

For recipe behavior, override the smallest appropriate method or callback and
preserve its expected return type. For example, the current ncurses overlay
calls the inherited `flag_handler`, then adjusts flags only when its spec
matches the affected version and CCE. Some build systems implement behavior in
separate builder classes. Inspect the pinned recipe's builder class and method
before deciding where to override; adding a same-named method to the package
class is not universally sufficient. Zlib, for example, has its own builtin
`MakefileBuilder`. If overriding that builder, inherit the recipe-specific
builder rather than replacing it with the generic Makefile builder and losing
the existing zlib build logic. A reviewed full replacement such as the
external-only CCE compiler recipe is a separate case, not the usual template
for a library patch.

### Copy the reviewed files

Stage the candidate outside the live package directory first. For the zlib
example, set the candidate directory and the exact patch list below. Use an
empty list `OVERLAY_PATCH_FILES=()` for a recipe-only correction, and list any
additional reviewed support filenames explicitly when needed. All files in the
list must be supplied in the candidate directory.

```bash
export OVERLAY_CANDIDATE_DIR="<absolute-directory-containing-reviewed-files>"
export OVERLAY_RECORD="<absolute-new-change-record-directory-outside-package-repo>"
OVERLAY_PATCH_FILES=("cce-lld-version-map.patch")
```

Run this only after coordinating the affected build work and confirming the
release is eligible for a correction. The record directory must be new so a
repeat does not overwrite the original evidence. This block backs up an
existing overlay and the selected lock, then copies the explicitly listed
files with the CSE collaboration permissions:

```bash
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  : "${CSE_BUILD_WORKSPACE:?Enter through cse-build login shell first}"
  : "${PACKAGE_DIR:?Select the affected package first}"
  : "${OVERLAY_CANDIDATE_DIR:?Set the candidate directory}"
  : "${OVERLAY_RECORD:?Set a new record directory}"
  test -f "$TARGET_ENV/spack.lock"
  test -f "$OVERLAY_CANDIDATE_DIR/package.py"
  for patch_file in "${OVERLAY_PATCH_FILES[@]}"; do
    test -f "$OVERLAY_CANDIDATE_DIR/$patch_file"
  done
  test ! -e "$OVERLAY_RECORD"
  install -d -m 2770 -g "$CSE_GROUP" "$OVERLAY_RECORD"
  if test -d "$PACKAGE_DIR"; then
    cp -a "$PACKAGE_DIR" "$OVERLAY_RECORD/recipe-before"
  fi
  cp -p "$TARGET_ENV/spack.lock" "$OVERLAY_RECORD/spack.lock.before"
  spack -e "$TARGET_ENV" find -c -d -L -N -v > "$OVERLAY_RECORD/graph.before.txt"
  spack python -c 'import ast, os; ast.parse(open(os.path.join(os.environ["OVERLAY_CANDIDATE_DIR"], "package.py")).read())'

  install -d -m 2770 -g "$CSE_GROUP" "$PACKAGE_DIR"
  for patch_file in "${OVERLAY_PATCH_FILES[@]}"; do
    install -m 0660 -g "$CSE_GROUP" "$OVERLAY_CANDIDATE_DIR/$patch_file" "$PACKAGE_DIR/"
  done
  install -m 0660 -g "$CSE_GROUP" "$OVERLAY_CANDIDATE_DIR/package.py" "$PACKAGE_DIR/package.py"
)
overlay_copy_status=$?
printf 'Overlay copy status: %s (continue only if 0)\n' "$overlay_copy_status"
```

Back up every additional affected environment's lock and concrete graph before
its recovery in Step 7, using separate named files. Keep the record outside the
package repository so backup recipes are not mistaken for new packages. If a
copy fails partway through, stop; inspect the live package directory and either
finish the reviewed file set or restore the saved original while builds remain
paused. Do not start an install from a mixed or incomplete file set.

Syntax parsing does not validate Spack inheritance, patch applicability, or the
build correction. Complete the following checks before building.

## 5. Prove which recipe is selected, without solving

Use the affected environment's effective repository order and package path:

```bash
spack -e "$TARGET_ENV" repo list
spack -e "$TARGET_ENV" location --package-dir "$PACKAGE_NAME"
```

The path must be `$PACKAGE_DIR`. If it is the cached builtin recipe, fix the
repository configuration or package/module spelling before continuing. Do not
add a user-level repository as a workaround; the workspace already owns its
repository selection.

Load the selected class with the pinned Spack runtime to catch import or
inheritance errors and print its actual definition file:

```bash
spack -e "$TARGET_ENV" python -c 'import inspect, os, spack.repo; cls = spack.repo.PATH.get_pkg_class(os.environ["PACKAGE_NAME"]); print(cls.__module__, cls.__name__); print(inspect.getfile(cls))'
```

These checks do not concretize. Do not use `spack spec <abstract-spec>` as a
read-only recipe-location check; it can invoke the solver. For builtin lookup,
use Step 3's explicit `location --repo builtin`; in Spack 1.2.2,
`location --package-dir builtin.<package>` does not reliably preserve the
namespace when resolving the recipe directory.

There are two different things to inspect: the recipe that a new solve would
select, and the namespace/hash already stored in an old lock. A successful
location/class check does not rewrite that lock or prove the old package will
be rebuilt. Inspect the recorded graph with `find -c -d -L -N -v`, then follow
the affected-lock recovery below.

For a source patch, verify it against a pristine copy of the exact pinned
source, before that patch has been applied:

```bash
cd "<pristine-exact-package-source-directory>"
patch --dry-run -p1 < "$PACKAGE_DIR/cce-lld-version-map.patch"
```

Use the candidate's actual patch filename and required strip level. A patch
that applies to a convenient upstream branch but not the pinned source is not
sufficient. Run the dry check for each patch in its intended application order;
when patches depend on earlier patches, use a disposable source copy and apply
each successfully checked patch there before checking the next. Do not alter the
live build stage for this check. An already-patched or manually altered stage
can give misleading results.

## 6. Run a red and green package test

Retain the minimal reproducer failure from before the correction. For a
source-level check, apply the correction in a disposable source copy and rerun
the same reproducer. For a Spack rebuild, first recover the affected locks in
Step 7 and install in Step 8; do not rebuild a modified recipe against its old
locked identity. Keep the reproducer and acceptance checks the same so the
comparison tests the reported defect.

Examples of useful validation include:

```bash
test -f "<prefix>/lib/<required-shared-library>"
readelf -d "<library>"
readelf --version-info "<library>"
ldd "<executable-or-library>"
```

For a configure, compile, or link failure, a successful corrected build that
passes the original failing stage with the same compiler is the recovery test.
Add a numerical, MPI, or other consumer check when the reported defect concerns
runtime behavior or the normal release acceptance procedure requires it.

## 7. Recover the affected unaccepted locks

Build-affecting recipe and applied patch content contribute to package identity.
An existing concrete node retains the package identity stored in its lock.
Changing the file on disk does not update that identity. Do not present a
retry of the old lock as the accepted correction.

First identify every affected environment and dependent graph. A foundational
package may affect multiple locks; a compiler condition alone is not proof
that other locks need no review. Keep the change within the reviewed candidate
release and coordinate all affected builders. Process one environment at a
time, preserving its original lock and full concrete listing before solving.

The selected `$TARGET_ENV` is still the affected environment from Step 3. If
changing environments, update `ENVIRONMENT` and derive `TARGET_ENV` again.
Create a separate recovery record for that environment before changing its lock:

```bash
export LOCK_RECORD="$OVERLAY_RECORD/locks/${ENVIRONMENT//\//-}"
set +e
set +o pipefail
(
  set -e
  set -o pipefail
  test -d "$OVERLAY_RECORD"
  test ! -e "$LOCK_RECORD"
  install -d -m 2770 -g "$CSE_GROUP" "$LOCK_RECORD"
  cp -p "$TARGET_ENV/spack.lock" "$LOCK_RECORD/spack.lock.before"
  spack -e "$TARGET_ENV" find -c -d -L -N -v > "$LOCK_RECORD/graph.before.txt"
)
lock_record_status=$?
printf 'Lock record status: %s (continue only if 0)\n' "$lock_record_status"
```

Choose the solve based on the reviewed dependency graph:

- **Fresh roots with reusable dependencies:** the existing correction command
  below is appropriate when the changed package is a root and reusing unchanged
  dependencies is intended. It permits dependency reuse; it does not promise
  that a corrected dependency or an ancestor containing it will be replaced.

```bash
spack -e "$TARGET_ENV" concretize -f --reuse-deps -j 1
```

- **A corrected dependency could otherwise be reused:** after impact review,
  the alternative below disables installed/build-cache reuse for this one
  environment's solve. It can change other nodes too, so compare the whole
  graph and stop on unexplained changes. Do not run it automatically over all
  eight environments. Explicit reuse exclusions for the changed dependency
  and reusable ancestors are another option, but require a reviewed exclusion
  set; do not assume excluding only the leaf removes every old dependent DAG.

```bash
spack -e "$TARGET_ENV" concretize -f --fresh -j 1
```

Run only the chosen recovery command and require success before continuing.
`-f` permits replacing existing concrete entries. `--fresh` disables reuse for
the solve; it does not mean that installation must compile from source. Neither
plain `./cse-build concretize` (which keeps existing locks) nor `--fresh` without
`-f` is a replacement procedure for an existing locked graph. Accepted releases
remain outside this in-place recovery procedure.

After the selected solve succeeds, record and inspect the complete result:

```bash
spack -e "$TARGET_ENV" find -c -d -L -N -v > "$LOCK_RECORD/graph.after.txt"
spack -e "$TARGET_ENV" find -c -d -L -N -v "$PACKAGE_NAME"
```

Confirm the intended namespace, changed package/hash where build behavior
changed, and the affected dependent hashes. Recipe path selection alone is not
proof. Explain every unrelated change; if the defective package was reused,
stop and revise the recovery instead of proceeding to installation. Repeat
only for the other affected environments, then verify the complete set.
Preserve old prefixes and binaries as evidence; do not delete shared packages
to coerce the solver.

## 8. Verify and resume installation

For a focused manual retry, use
[quickstart Step 6](templates/PACKAGE-OVERLAY-QUICKSTART.md#6-retry-only-this-package-directly-with-spack):
enter the prepared compute shell, then run `spack -e ... install --only-concrete`
with the corrected concrete hash. The commands below are the alternative for
resuming installation of the full compiler surface.

In the prepared login shell, verify the updated locks:

```bash
cd "$CSE_BUILD_WORKSPACE"
./cse-build login verify
```

After that succeeds, enter the approved compute allocation and return to the
same absolute workspace path. Then run:

```bash
cd "<absolute-shared-workspace-path>"
./cse-build compute install --surface platform
```

Use `--surface shared` instead when the correction belongs to the CSE-built
GCC surface. Do not run two installers for the same surface concurrently.

A new lock can require different source versions/resources/patches. On a
restricted system, check source availability before building and arrange only
any missing acquisitions; a recipe edit does not automatically create new
source-mirror contents.

After installation, rerun the minimal reproducer and the package-specific
binary or runtime validation. Keep the old failed or incomplete prefix until
the corrected lock and validation evidence are complete. Do not remove a
prefix manually merely because its replacement installed successfully.

## 9. Return the correction to Stack Content

For offline workspace-to-workspace transfer, follow
[quickstart Step 7](templates/PACKAGE-OVERLAY-QUICKSTART.md#7-carry-the-overlay-to-another-workspace-without-git).
It packages the validated deployed recipe and its support files with a change
record and checksum, then repeats selection, lock recovery, and validation in
the destination workspace. Git/GitLab is not required. Do not transfer a source
system's lockfiles or compiler configuration as part of a portable recipe fix.

The workspace overlay is not the canonical source. Copy the validated package
directory into the matching Stack Content tree:

```text
pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/packages/<package-module>/
```

Add or update:

1. The subclassed `package.py`.
2. Every local patch referenced by the recipe.
3. A regression test that checks the affected condition and patch behavior.
4. The system runbook section containing the recovery and validation commands.

Run the pilot test suite before committing:

```bash
python3 -m unittest discover -s pilots/cse-pilot/tests
```

When ready to integrate through Git, review the staged diff, commit with the
package and cause in the message, and push the reviewed branch. Retain the
archive and change record while that step is deferred. Future workspace renders
must receive the same overlay without depending on changes retained only in an
earlier workspace.

## Recipe correction request

Use this tool-neutral request to obtain the candidate files. Supply the actual
inputs or mark what is unavailable; a package name and a final error line alone
are usually insufficient to scope a reliable correction.

```text
Prepare a narrow CSE Spack package overlay for the recorded failure.

Inputs:
- Spack version and commit; builtin spack-packages tag and resolved commit.
- Absolute generated workspace, affected environment, builtin recipe, and
  deployed overlay package-directory paths; how the prepared shell was entered.
- Workspace setup/handoff files and the local offline inputs available.
- Exact package version, concrete spec/hash, compiler/version, variants,
  dependencies, target, and failing environment.
- Original build log, exact failing command, and relevant generated build files.
- The actual pinned builtin package.py and referenced source/patch context.
- Existing cse_trials package.py and local patches, if any.

Deliverables:
1. Explain the demonstrated cause and whether it belongs in package source,
   recipe/builder behavior, environment policy, or compiler metadata.
2. Provide a complete updated local package.py, preserving existing fixes.
   Normally subclass the pinned builtin class; do not copy an unrelated newer
   complete recipe. Use the correct API v2 package module and class names.
3. Provide every referenced local patch/support file, its exact filename, and
   a diff against the current local files. For a new overlay, say so explicitly.
4. Scope the correction to the evidenced versions, compiler/versions, variants,
   and platform/target conditions. Explain any wider applicability.
5. Cite the exact upstream revision if adapting an upstream fix. Do not invent
   source checksums, versions, method names, or patch context.
6. State which environment locks and dependents need review, how to prove the
   selected recipe and resulting concrete identity, and how to detect unwanted
   reuse of the old package.
7. Give manual copy, source/patch checks, build, and package-specific validation
   steps. Include a meaningful check that unaffected cases still behave as
   intended.

The receiving operator will review and place the files under:
$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials/packages/<module>/

Do not edit the cached builtin repository, remove installed prefixes, alter an
accepted release, or assume that changing package.py updates existing locks.
If the evidence or pinned recipe is missing, identify the missing input instead
of guessing a deployable correction. Distinguish proposed checks from checks
actually run.
```

## References

- [Spack 1.2.2 repositories, precedence, API v2, and recipe inheritance](https://github.com/spack/spack/blob/v1.2.2/lib/spack/docs/repositories.rst)
- [Spack 1.2.2 environment locks and concretization](https://github.com/spack/spack/blob/v1.2.2/lib/spack/docs/environments.rst)
- [Spack 1.2.2 location command](https://github.com/spack/spack/blob/v1.2.2/lib/spack/spack/cmd/location.py)
- [Spack 1.2.2 concretizer reuse options](https://github.com/spack/spack/blob/v1.2.2/lib/spack/spack/cmd/common/arguments.py)
- [Pinned builtin package repository](https://github.com/spack/spack-packages/tree/v2026.06.0/repos/spack_repo/builtin)
