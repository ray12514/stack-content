# Updating an existing trial without rebuilding its packages

Updating the source checkout or preparation tool does not update a generated
workspace. Use this procedure for a deliberate, scoped adoption on a real
cluster. Local lab workspaces are disposable test fixtures. Preserve the real
cluster's recorded inputs, locks, Spack database, installed prefixes and runtime
dependencies until the replacement is accepted.

## Choose the change

| Change | Operation | Concrete graph |
| --- | --- | --- |
| Preparation tool code only | Update/rebuild the tool, render to a separate comparison directory | Retain existing locks |
| Compiler entrance and lane selectors | `--scope presentation` below, validate, then publish modules | Retain existing locks and installed packages |
| Build helper or operational config | Review `--scope controls` or `all`; satisfy declared dependencies first | Retain locks; this does not accept new recipe inputs |
| Package module generation | Use the prepared workspace's Spack and its recorded module settings; see `BUILDER-HANDOFF.md` | Generate from installed locked specs; no concretization |
| Package version, variant, recipe, compiler or MPI policy | Separate candidate inputs, reviewed overlay inventory if needed, explicit solve and affected-consumer tests | Preserve original locks; inspect new candidate locks |

`presentation` replaces only the blueprint's `modulefiles/` and `presentation/`
trees. These are the workspace's entrance/lane files, not the package module
root referenced by `values.paths.modules_root`. Publishing entrance files and
refreshing package modules are separate operations. Back up the destination
module tree before an intentional package-module refresh; the control refresh
does not back up an external module root.

## Render values and preview

Keep recorded values unchanged. If they predate required fields, use
`scripts/prepare-existing-workspace-values.py --help` to create a temporary
render-only copy from the recorded values and the recorded Spack identity.
When the old values have no builtin commit, supply the explicitly reviewed
`--builtin-commit`; the June 2026 builtin used by this candidate is
`d4f7c711a6a42f1c4d551c8fd10fce9a11340a81`. This only satisfies rendering. It does
not change the active workspace's repository configuration or lockfiles.
Do not regenerate existing values from current discovery and assume the result
is equivalent to the recorded trial.

Use the Python environment supplied for the preparation tools (with PyYAML),
the portable Composer entry point, and absolute paths:

```bash
python3 "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --composer "$STACK_COMPOSER" \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --values "$REFRESH_VALUES" \
  --workspace "$BUILD_WORKSPACE" \
  --scope presentation --dry-run
```

The preview renders into a separate temporary directory, validates identity and
paths, and lists the selected replacements. It makes no workspace changes.
Review generated content separately using the comparison procedure in
`STACK-COMPOSER-UPDATE.md` when the template change is new to this system.

Quiesce builders and consumers of the selected controls, then repeat the command
without `--dry-run`. Ordinary replacement failures roll the complete selected
set back, including file modes and removal of newly introduced files. Successful
refreshes retain previous controls and fingerprints under
`$BUILD_WORKSPACE/.cse-control-refresh/<id>/record.json`. The script serializes
its own refresh/restore operations. It does not lock an already running builder
or make a multi-file switch atomic for concurrent readers or power loss.

For completed trials, start with `presentation`. A current launcher/verifier
expects the admitted overlay inventory, its helper and other declared
prerequisites; a controls refresh refuses to install those controls when their
prerequisites are absent. Prepare and qualify that adoption in a candidate.
Copying a new verifier alone is not a supported upgrade.

## Restore or recover without re-solving

For an applied refresh, use its exact printed/history record:

```bash
python3 "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --workspace "$BUILD_WORKSPACE" --restore-from "$REFRESH_RECORD" --dry-run
# After checking the selected paths, repeat without --dry-run.
```

Restore refuses subsequent edits or mismatched backup contents. It has its own
retained undo record. An interrupted operation or incomplete rollback blocks
another ordinary update and reports the unfinished record. After addressing the
underlying disk/permission failure, use:

```bash
python3 "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --workspace "$BUILD_WORKSPACE" --recover-from "$REFRESH_RECORD" --dry-run
# Repeat without --dry-run to recover the recorded prior controls.
```

Recover the newest unfinished transaction first if a recovery itself failed.
Recovery accepts only the recorded old/new state or a missing selected path;
it refuses unrelated edits. Do not delete the history to silence the check.
If the process was killed and `.cse-refresh.lock` remains, check `owner.json` and
verify the owner is no longer running before removing only that stale lock.
All snapshots remain available for a manual comparison if inputs were edited
outside the procedure. No recovery command changes a protected lock, recipe,
catalog, install, view or cache path.

## Resume and acceptance

Use the existing prepared workspace to finish only the unfinished environments.
Installed hashes are reusable when the database, prefixes and external runtime
remain valid; retaining `spack.lock` alone is insufficient. Do not use full
render or initialization with overwrite against an active workspace.

After module refresh, test a clean module session and representative installed
consumers before publishing the changed module presentation. Package artifacts
can be copied to a candidate buildcache independently of that acceptance. Keep
the cache candidate distinct from the accepted release; complete CSE's signing,
cache-only destination install and target consumer checks before promotion.
The two unfinished CCE systems still need their native compiler, Fortran/MPI,
and launch-path checks. Small local fixtures validate the process, not those
system-specific results.
