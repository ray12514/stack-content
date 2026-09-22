# Correct a package and continue in the same workspace

The normal loop is **edit/apply the complete package correction → explicitly
reconcretize the selected environment → resume that same environment**. Keep the
workspace, its recorded configuration and its existing installed prefixes. A new
workspace, full render, new static catalog, Composer upgrade or additional test
application is not required just to fix a package build. The corrected package
building successfully in its original compiler environment verifies this recovery;
later release module, MPI and publication acceptance remain separate.

Applying an overlay changes only that package directory and the reviewed overlay
inventory. It never concretizes, installs, deletes an installed prefix, refreshes
modules/views or publishes anything. Other environments keep their lockfiles.
The helper reports their possible exposure to the recipe change and blocks a
future build with an affected stale lock until that environment is explicitly
reconcretized. Their existing installed prefixes and modules remain usable.

## 1. Edit on the system or apply complete reviewed files

Use the existing workspace and its normal login context. Stop or coordinate any
already running older launcher or manual Spack command before changing recipes.
Current finite launcher actions share a workspace maintenance lock; an older
command does not participate automatically.

```bash
cd /absolute/path/to/existing-workspace
export EDITOR=vi
./cse-build login overlay edit --package netlib-lapack --environment cce/common
```

`edit` copies the existing local overlay package, including patches, into the
workspace's recovery journal and opens its `package.py` with `$EDITOR` (or
`$VISUAL` if `EDITOR` is unset). When no local overlay exists, it locates the
package with the selected environment's recorded Spack 1.2.2 and verifies the
builtin repository's source and commit/tag before copying it. Neither the pinned
builtin checkout nor the live overlay is edited in the editor. After a successful
editor exit, the complete corrected directory is validated and applied back into
**this workspace**. An unchanged edit is cancelled without changing the recipe.
No LLM is required.

To use a correction already prepared manually or with assistance, provide the
complete package directory, including every referenced local patch:

```bash
./cse-build login overlay apply \
  --environment cce/common --package netlib-lapack \
  --from /absolute/path/to/corrections/netlib_lapack --dry-run

./cse-build login overlay apply \
  --environment cce/common --package netlib-lapack \
  --from /absolute/path/to/corrections/netlib_lapack
```

`--dry-run` validates the proposed repository and prints lock impact without
changing recipes or creating an overlay transaction. `apply` is the explicit
admission of those reviewed files; it does not add another approval prompt.
`--package` can be omitted when it is unambiguous from the API v2 directory name
(`netlib_lapack` maps to `netlib-lapack`). `--environment` selects the recommended
next step, not the set of locks inspected. The namespace defaults to `cse_trials`;
`--repository NAME` selects another already registered local API v2 repository.

Do not edit a live package first and then ask the helper to accept unexplained
inventory drift. Use `edit` or a separate complete package directory so the helper
can retain and verify the previous recipe before changing it. Existing local fixes
and support files must be carried into the correction. An existing inventory must
match all current recipe bytes. For an older workspace without an inventory,
explicit apply validates the complete existing tree and admits the corrected
inventory, retaining the original absence for restoration.

## 2. Reconcretize only the environment being repaired

Read the reported `affected`, `unchanged`, and not-yet-concretized environments.
The helper scans **all** recorded locks. Old and new local recipe imports, dynamic
lookups, or changed provider directives conservatively broaden the affected list.
This report does not start solves in other environments.

```bash
./cse-build login concretize --environment cce/common --reconcretize
```

Without `--reconcretize`, an existing lock is kept. A recipe change therefore
requires the explicit flag before its affected environment can build again.
The selected solve uses the existing workspace configuration and records the old
lock, the graph change and the new lock. A failed/interrupted solve retains its
recovery record and restores the selected manifest/lock before a safe retry.
Review unexpected version, variant, compiler, provider or dependency changes
before proceeding. The force solve may change more nodes than the corrected
package; it does not rebuild them by itself.

Use the same explicit solve after changing a version or variant. `resume` checks
current root specifications against the lock, including grouped roots in older
workspaces. New solve records also detect selected manifest changes while
allowing module/view and operational settings to change independently. Edits
to included package/provider/concretizer policy files still require an explicit
solve: a historical lock cannot establish their previous contents.

A successful explicit solve clears pending recipe impact **only for this
environment**. Unselected affected locks remain marked stale for future builds.
A lock still having the same bytes does not automatically clear that state.
The internal `resolved --environment` acknowledgment is used by the successful
forced-solve operation; do not run it merely to bypass the build gate.

## 3. Resume the same selected environment

Enter the system's normal compute allocation/context, return to the same workspace,
and continue:

```bash
cd /absolute/path/to/existing-workspace
./cse-build compute resume --environment cce/common
```

`resume` installs from that selected reviewed lock. Already installed matching
hashes are reused; corrected hashes build as needed. It does not reconcretize,
advance the rest of the trial stack, regenerate views/modules or publish them.
If another package fails, retain the log, correct its complete package directory,
then repeat the same edit/apply → selected reconcretize → selected resume loop.
Do not delete lockfiles or the install tree to restart this process.

No additional test program is needed merely to prove that the previously failing
package now builds. Reuse any applicable existing package checks and keep their
results. Consumer/module/MPI tests still belong to the later release acceptance
steps and to any change that specifically requires them.

## Records, interruption and restoration

```bash
./cse-build login overlay status
./cse-build login overlay status --record RECORD_ID_PRINTED_BY_APPLY
./cse-build login overlay restore --record RECORD_ID_PRINTED_BY_APPLY
```

Records live under `.cse-overlay/<id>/record.json` in this workspace. They retain
prior complete recipes and inventory, package file hashes, the affected old-lock
hashes, selected solve acknowledgments, and failed/replaced bytes. The package and
inventory are staged and promoted under the shared maintenance lock. A write
failure rolls them back; an unfinished transaction blocks further participating
build/overlay operations until recovered.

`restore` is a guarded recipe/inventory rollback. It refuses later recipe,
inventory, configuration, lock or presentation edits. Use it to cancel an overlay
before changing the solve. **After successful reconcretization, do not restore
the old recipe against the new lock.** Instead, apply the retained previous
complete package as a new correction, then reconcretize and resume the selected
environment again. When the record contains an older local overlay:

```bash
OLD_RECORD=RECORD_ID_WITH_THE_PREVIOUS_RECIPE
./cse-build login overlay apply --package netlib-lapack --environment cce/common \
  --from "$BUILD_WORKSPACE/.cse-overlay/$OLD_RECORD/original/package"
./cse-build login concretize --environment cce/common --reconcretize
./cse-build compute resume --environment cce/common
```

Supply `--package` explicitly for a retained backup directory. When the first
overlay was created from builtin, use the retained `edit-original/<package_dir>`
copy or another reviewed complete copy of that pinned recipe instead. The helper
never silently rolls back other environments' locks. Keep incomplete or failed
records for diagnosis.

If the editor or recipe validation fails, the editable copy remains under the
printed journal path. Correct those files, use `restore --record` to cancel the
unfinished edit, then `apply --from` that retained complete directory. This keeps
all work in the same operator workspace.

If an interrupted recipe/inventory promotion prevents `cse-build` from passing
its startup inventory gate, use the direct helper recovery path below. This
restores recorded bytes without going through that failing startup gate.

## Older launchers and direct recovery

An older launcher need not be replaced merely to apply a recipe. Use its prepared
shell and the helper from a reviewed current content checkout:

```bash
cd /absolute/path/to/existing-workspace
./cse-build login shell
OVERLAY_HELPER=/absolute/path/to/stack-content/pilots/cse-pilot/templates/scripts/workspace-overlay.py
spack python "$OVERLAY_HELPER" apply --environment cce/common \
  --from /absolute/path/to/corrections/netlib_lapack
```

The workspace defaults to `CSE_BUILD_WORKSPACE`; `--workspace` is also accepted.
Keep `workspace-build.py`, `overlay-recovery.py` and `verify-overlay-inputs.py`
adjacent to the helper. They are present together in the reviewed content tree.
The helpers retain the generated Python 3.6 floor. The previously sealed
`recovery.2` delivery predates these helpers; use a reviewed current checkout or
later delivery. Pulling source never updates an already generated workspace.

If the launcher lacks the selected solve/resume actions, use the companion helper
in the same prepared shell:

```bash
BUILD_HELPER=/absolute/path/to/stack-content/pilots/cse-pilot/templates/scripts/workspace-build.py
spack python "$BUILD_HELPER" concretize --workspace "$CSE_BUILD_WORKSPACE" \
  --environment cce/common --reconcretize
# In the existing prepared compute shell:
spack python "$BUILD_HELPER" resume --workspace "$CSE_BUILD_WORKSPACE" \
  --environment cce/common
```

For an interrupted overlay that blocks launcher startup, start from the saved
operator activation (which identifies `SPACK_ROOT` and `BUILD_WORKSPACE`) and use
the recorded runtime directly. Restore the helper's absolute path in this shell:

```bash
OVERLAY_HELPER=/absolute/path/to/stack-content/pilots/cse-pilot/templates/scripts/workspace-overlay.py
SPACK_DISABLE_LOCAL_CONFIG=true "$SPACK_ROOT/bin/spack" \
  -e "$BUILD_WORKSPACE/environments/cce/common" python "$OVERLAY_HELPER" restore \
  --workspace "$BUILD_WORKSPACE" --record RECORD_ID
```

This is recovery of recorded input bytes, not a build. If a selected build/solve
journal also reports live workers or incomplete restoration, resolve that journal
before changing recipes. Do not run an old broad `install` action while its lock
is reported stale, even if that old launcher lacks the new gate.

## Optional isolated candidate workflow

Use a separate candidate only when you deliberately want an isolated comparison
or expert test. `templates/scripts/overlay-recovery.py` retains the existing
`prepare → solve → retry → resume/export` interface. Its `--help` describes the
candidate path and explicit plan digest; invoke that helper directly rather than
the normal `cse-build overlay` front door. Candidate views and automatic module
generation remain disabled, and its focused retry tests the corrected hash.

Return accepted corrections to authored Stack Content and carry the complete
package directory plus evidence to another system. Apply it in that system's
own existing workspace, reconcretize its selected affected environment and resume
there. A correction bundle does not authorize copying another system's lockfile
or replacing its accepted publication. Public production activation remains a
separate decision.
