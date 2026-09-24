# Updating an existing trial without rebuilding its packages


For slow interactive startup at **any build stage**, use the narrow
[`--scope startup` procedure](STARTUP-PERMISSIONS.md). It preserves all Spack
configuration, padding, environments, locks, views, modules and packages.

Updating the source checkout or preparation tool does not update a generated
workspace. Use this procedure for a deliberate, scoped adoption on a real
cluster. Local lab workspaces are disposable test fixtures. Preserve the real
cluster's recorded inputs, locks, Spack database, installed prefixes and runtime
dependencies until the replacement is accepted.

## Do the tools need updating first?

**Generating modules from already installed packages does not require a new
Stack Composer version or a rebuild.** Composer is needed only when rendering
reviewed replacement controls/policy that the existing workspace lacks. The
workspace's `cse-build` (or its documented native Spack commands) performs module
generation. The separate generic `spack-build` driver is not needed for this CSE
maintenance operation.

For lane presentation, first check the existing workspace. If its named views,
module policies and front doors are already complete, use its current `modules`
action and the consumer check below. If any are absent, adopt only the required
`module-policy`, `controls` or `presentation` refresh described here; retain the
original build values and locks. An updated source checkout does not itself
change those deployed files.

For naming/layout iterations, use [Module presentation previews](MODULE-PRESENTATION.md).
That helper checks prerequisites and generates into a new preview directory
using existing installed hashes. Start with the lane layout, try alternate
Spack projections in reviewed policy files, and compare using `module use` before
changing the published presentation. It requires no solve, install or Composer
update. Its prerequisite report identifies missing views/policy rather than
silently updating a completed workspace.

## Start here after the packages are built

The sequence is **restore the operator session → check the existing build →
review/change module policy or presentation → generate package modules if
needed → test with `module use` → expose the accepted presentation**. A source
checkout update alone does not perform any of those workspace operations.

For the usual completed-build pass, follow steps 1–3, choose only the needed
change from the table, then continue to [module generation](#generate-package-modules-from-the-existing-installations)
and [the clean consumer test](#test-the-workspaces-entrance-and-lanes-with-module-use).
Inventory admission and transaction restoration are separate reference sections;
they are not required on every login.

Run each block separately in Bash and stop on a nonzero result. Use the saved
system/release paths from this trial; the angle-bracket examples below must be
replaced with those recorded values.

### 1. Restore this system's operator session

On a fresh login, source the existing activation file by its recorded absolute
path. For the default operator-session location:

```bash
source "$HOME/STACK_TESTING/operator-sessions/<system>/<trial-release>/activate.sh"
cse_session_status
printf 'workspace=%s\nrecorded values=%s\n' "$BUILD_WORKSPACE" "$BUILD_VALUES"
```

This restores the paths used for preparation and maintenance. It does not
activate a Spack environment, recreate values, render, or rebuild packages.
The site must already supply `USER` and an absolute writable `WORKDIR`; start
with no active Spack environment. If activation reports a missing prerequisite,
resolve it before continuing rather than inventing a shared work path.
Do not create a new session for an already-built trial or source the generated
`env/setup-build-env.sh` directly. A different operator session root uses its
recorded `activate.sh` path instead of the default above.

| Variable | Supplied by the saved session | Meaning |
| --- | --- | --- |
| `BUILD_WORKSPACE` | Yes | Existing generated workspace containing `cse-build`, `catalog/`, environments and locks |
| `BUILD_VALUES` | Yes | Path to the recorded `cse-trials-build-values.yaml` used to initialize this trial; confirm that file still describes this workspace |
| `CONTENT`, `STACK_COMPOSER`, `CSE_PYTHON` | Yes | Checkout-based content, portable Composer and preparation Python paths |
| `BUILD_EVIDENCE` | Yes | Evidence directory for this system/release |
| `PREP_PYTHON` | No | The preparation Python you explicitly select below |
| `REFRESH_VALUES` | No | Path to the YAML input selected for this maintenance operation |

The receiving builder can enter an existing workspace directly through
`./cse-build`; that handoff does not require an operator session. Here you are
acting as the operator because you also need the content/tools and recorded
inputs to review changes.

### 2. Select the maintenance tools and values

For either tool choice, select the recorded input file first:

```bash
REFRESH_VALUES="$BUILD_VALUES"
test -r "$REFRESH_VALUES"
```

For the reviewed checkout-based tools restored by the session:

```bash
PREP_PYTHON="$CSE_PYTHON"
test -x "$PREP_PYTHON"
"$PREP_PYTHON" -c 'import yaml'
"$PREP_PYTHON" "$STACK_COMPOSER" --help
```

The preparation Python must be 3.9 or newer and have PyYAML. Updating Git does
not rebuild `stack-composer.pyz`; use [the tool update procedure](STACK-COMPOSER-UPDATE.md)
when selecting a changed Composer implementation. The tested recovery work is
on `codex/recovery-hardening`. The saved session may still report the original
`STACK_BRANCH`; activation does not switch branches or select the new delivery.

If using the verified offline delivery instead, first restore the session as
above, then select the delivery and its already-created helper runtime:

```bash
DELIVERY_ROOT=/absolute/path/to/the/verified/versioned/delivery
PREP_PYTHON=/absolute/path/to/its/runtime/bin/python
STACK_COMPOSER="$DELIVERY_ROOT/tools/stack-composer.pyz"
CONTENT="$DELIVERY_ROOT/sources/stack-content"
export SHIV_ROOT="$(dirname "$(dirname "$PREP_PYTHON")")/shiv-cache"
export PYTHONDONTWRITEBYTECODE=1
"$PREP_PYTHON" "$STACK_COMPOSER" --help
"$PREP_PYTHON" -c 'import yaml'
```

Follow the delivery's `UPDATE.md` once to verify it and create that offline
runtime. Keep `BUILD_VALUES`, `BUILD_WORKSPACE` and the other trial paths from
the saved session. Sourcing `activate.sh` again resets the tool/content paths
to the checkouts, so repeat the delivery selection after any reactivation.
Do not run `cse_rebuild_tools` against immutable delivery sources.

`REFRESH_VALUES` is an input filename, not another environment or an output
generated by `refresh-workspace-controls.py`. It can point directly to
`BUILD_VALUES` when the recorded file already satisfies the selected templates.
If fields are missing or presentation values need editing, create and review a
separate copy using [the values procedure below](#prepare-a-separate-values-copy).
The refresh helper reads those values with the workspace's retained `catalog/`,
renders a temporary comparison workspace, and adopts only the selected scope.

### 3. Check the existing build and inspect its module layout

Run the retained workspace's launcher; do not replace it just to obtain newer
commands:

```bash
cd "$BUILD_WORKSPACE"
./cse-build --help
./cse-build login status
./cse-build login verify
```

`cse-build` prepares its own pinned Spack process. You do not need to run
`spack env activate` or load the CSE consumer modules first. `status` reports
installed specs; `verify` checks configuration and concrete locks. Neither
proves that every locked prefix is present or that modules load correctly.
These actions also run the launcher's existing permission/preflight hooks.
If they fail, retain the error and diagnose that failure before refreshing.

Use the recorded values to print the output roots and entrance names:

```bash
"$PREP_PYTHON" - "$BUILD_VALUES" <<'PY'
import sys, yaml
v = yaml.safe_load(open(sys.argv[1]))
print("Package modules:", v["paths"]["modules_root"])
print("Views:", v["paths"]["views_root"])
for name in ("shared", "platform"):
    c = v[name]["compiler"]
    print(name, "compiler:", c["name"], "entrance: cse/" + c["public_name"])
PY
if test -d "$BUILD_WORKSPACE/modulefiles"; then
  find "$BUILD_WORKSPACE/modulefiles" -type f -print
else
  printf 'Workspace presentation is missing; prepare it before the consumer check.\n'
fi
find "$BUILD_WORKSPACE/configs/environments" -name modules.yaml -print
```

The generated `configs/environments/<compiler>/<kind>/modules.yaml` owns package
names/projections, dependencies, visibility and output roots. The corresponding
`environments/<compiler>/<kind>/spack.yaml` owns named views. The workspace's
`modulefiles/` owns the compiler entrances and Serial/MPI selectors. Review
these files against the intended CSE presentation before choosing a change.

Create a retained record for this maintenance pass and capture the lock hashes:

```bash
mkdir -p "$BUILD_EVIDENCE"
MODULE_REVIEW=$(mktemp -d "$BUILD_EVIDENCE/module-review.XXXXXX")
cd "$BUILD_WORKSPACE"
find environments -name spack.lock -print0 | sort -z | \
  xargs -0 sha256sum > "$MODULE_REVIEW/locks.sha256"
```

Record the printed module/view roots, module names and command results there.
Before changing generated outputs, stop their writers/readers and retain copies
of those exact external module/view trees using the site's backup procedure.
The control transaction backs up configuration; it does not back up these
output trees. No change is needed when the current policy and modules already
match the intended layout: proceed directly to the clean-session check.

## Choose and preview the change

| Change | Operation | Concrete graph |
| --- | --- | --- |
| Preparation tool code only | Update/rebuild the tool, render to a separate comparison directory | Retain existing locks |
| Compiler entrance and lane selectors | [Preview/apply `--scope presentation`](#preview-and-apply-compiler-entrancelane-presentation), then test | Retain existing locks and installed packages |
| Build helper or operational config | Review `--scope controls` or `all`; satisfy declared dependencies first | Retain locks; this does not accept new recipe inputs |
| Package module generation | [Run the retained workspace's module commands](#generate-package-modules-from-the-existing-installations) | Generate from installed locked specs; no concretization |
| Missing or older package-module policy | [Preview/apply `--scope module-policy`](#upgrade-package-module-policy-in-an-older-workspace) from a reviewed candidate | Merge named views and replace selected module settings; retain the existing solve |
| Older overlay gate without an inventory | [Admit an inventory/helper](#admit-an-inventory-for-existing-frozen-overlays) against existing recipe bytes | Retain existing repository pins, recipes and locks |
| Package version, variant or recipe correction in an unfinished trial | [Same-workspace correction loop](OVERLAY-RECOVERY.md), explicit selected solve and build retry | Retain prior selected lock and all unselected locks/prefixes |
| Compiler/MPI policy or accepted release correction | Separate reviewed release under the SOP | Preserve accepted inputs and reuse compatible binaries |

`presentation` replaces only the blueprint's `modulefiles/` and `presentation/`
trees. These are the workspace's entrance/lane files, not the package module
root referenced by `values.paths.modules_root`. Publishing entrance files and
refreshing package modules are separate operations. Back up the destination
module tree before an intentional package-module refresh; the control refresh
does not back up an external module root.

### Prepare a separate values copy

Keep `BUILD_VALUES` unchanged. For a presentation edit to an already-current
file, copy it to a new path under `MODULE_REVIEW`, set `REFRESH_VALUES` to that
copy, and edit only the reviewed fields there:

```bash
REFRESH_VALUES="$MODULE_REVIEW/refresh-values.yaml"
test ! -e "$REFRESH_VALUES" && test ! -L "$REFRESH_VALUES" && \
  cp -p -- "$BUILD_VALUES" "$REFRESH_VALUES"
```

After that command succeeds, edit the reviewed presentation fields in the copy
and inspect `diff -u "$BUILD_VALUES" "$REFRESH_VALUES"`.

For older values, use the following alternative instead of that copy block.
The preparation helper creates that copy and fills supported historical fields. First
compare the saved Spack identity below with the existing `BUILDER-HANDOFF.md`
and launcher; use the workspace's recorded identity if they differ:

```bash
printf 'Spack: %s %s %s %s\nmode=%s\nroot=%s\n' \
  "$SPACK_SOURCE" "$SPACK_VERSION" "$SPACK_TAG" "$SPACK_COMMIT" \
  "$SPACK_RUNTIME_MODE" "$SPACK_ROOT"
REFRESH_VALUES="$MODULE_REVIEW/refresh-values.yaml"
test ! -e "$REFRESH_VALUES" && test ! -L "$REFRESH_VALUES" && \
"$PREP_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/prepare-existing-workspace-values.py" \
  --source "$BUILD_VALUES" --output "$REFRESH_VALUES" \
  --spack-source "$SPACK_SOURCE" --spack-version "$SPACK_VERSION" \
  --spack-tag "$SPACK_TAG" --spack-commit "$SPACK_COMMIT" \
  --spack-mode "$SPACK_RUNTIME_MODE" \
  --shared-spack-root "$CSE_TOOLS_ROOT/spack/$SPACK_VERSION" \
  --initial-spack-root "$SPACK_ROOT"
```

Require successful output creation, then run
`diff -u "$BUILD_VALUES" "$REFRESH_VALUES"`. `diff` exits 1 when it shows
differences; inspect them. The helper writes the new file named by `--output`.
The current source helper also rejects an existing file or link. The sealed
`stack-tools-2026.09.19-recovery.2` delivery predates that guard; the explicit
new-output check above is required when using its helper. The helper updates
supported render fields such as stage
contexts, permissions and explicit Spack metadata; it cannot discover missing
compiler driver commands or approve changed provider facts. Missing facts stop
the operation until supplied from reviewed system evidence.

If the recorded `package_repo.commit` is absent, the helper stops. Repeat with
`--builtin-commit <reviewed-full-commit>` only after recording which builtin
snapshot the candidate should render against. The tested delivery used
`d4f7c711a6a42f1c4d551c8fd10fce9a11340a81`; this is not evidence for an older
workspace's tag resolution. Adding it to a render-only copy does not adopt that
pin in the active workspace. Do not rerun `create-build-values.py` over the
recorded file or regenerate values from current discovery for this maintenance.

### Preview and apply compiler entrance/lane presentation

Use the tool and values selections from steps 1–2:

```bash
"$PREP_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
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
`$BUILD_WORKSPACE/.cse-control-refresh/<id>/record.json`. Record the exact ID/path
for this operation; the CLI may print the history pattern rather than the
individual filename. Use the listing in the restore section below. The script serializes
its own refresh/restore operations. It does not lock an already running builder
or make a multi-file switch atomic for concurrent readers or power loss.

For completed trials, start with `presentation`. A current launcher/verifier
expects the admitted overlay inventory, its helper and other declared
prerequisites; a controls refresh refuses to install those controls when their
prerequisites are absent. Use the standalone same-workspace overlay helper to
review and admit a correction; separately rehearse any required controls upgrade
in the lab. Copying a new verifier alone is not a supported upgrade.

## Upgrade package-module policy in an older workspace

Use a separate reviewed candidate workspace with the same blueprint, system and
catalog release identity. It may be rendered from recorded values plus explicitly
reviewed additions, or authored as a comparison tree with the recorded manifest,
selected `environments/<compiler>/<kind>/spack.yaml` and corresponding
`configs/environments/<compiler>/<kind>/modules.yaml` files. Older values can lack
current required compiler command maps; do not invent those facts to make a full
render pass.

When the reviewed `REFRESH_VALUES` supports current rendering, create that
comparison candidate at a new path:

```bash
MODULE_POLICY_CANDIDATE="$MODULE_REVIEW/module-policy-candidate"
"$PREP_PYTHON" "$STACK_COMPOSER" init-workspace \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --catalog "$BUILD_WORKSPACE/catalog" --values "$REFRESH_VALUES" \
  --output "$MODULE_POLICY_CANDIDATE"
```

Inspect/edit the proposed named views and selected module policy in this
candidate. Rendering it does not install anything, but its recorded output roots
may refer to the active trial: do not run its launcher. If using a separately
authored comparison tree instead, set `MODULE_POLICY_CANDIDATE` to its reviewed
absolute path. Preview adoption only after that candidate exists:

```bash
"$PREP_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --workspace "$BUILD_WORKSPACE" --candidate "$MODULE_POLICY_CANDIDATE" \
  --scope module-policy --environment gcc/core --dry-run
```

Repeat `--environment` for other completed environments, or omit it when the
candidate and existing environment/module sets match exactly. Every selected
environment must have a lock. Quiesce users of the selected controls, review the
candidate diff, and repeat without `--dry-run` to apply it. The operator tool
requires Python 3.9 or newer with PyYAML; the generated overlay helper remains
compatible with Python 3.6.

This operation copies only each selected `modules.yaml` and merges candidate
named views into the existing environment's `spack.view`. It retains unrelated
named views and every non-view environment setting, including ordered includes,
specs, definitions, reuse and compiler/provider policy. Module files may contain
only the `modules` section. The old include list must already activate the module
configuration directory or file, and candidate views must refer to existing spec
groups. A string `use_view` must name a resulting view. Unsupported shapes stop
before any changes. Current candidate specs are never adopted by this operation.

The retained transaction records exact previous file bytes, modes and protected
input fingerprints. Apply, restore and recovery check lockfiles, non-view
environment semantics, shared configuration, catalog and frozen recipe inputs.
They refuse unrelated changes instead of undoing newer work. The restore and
recovery commands below work for these records as well as ordinary controls.

After policy adoption, regenerate views/modules using the recorded Spack from
installed locked specs and test a clean module load plus the real consumer. A
new include filter can omit an old installed package even when the lock remains
valid; check expected module names before publication. This transaction does not
back up or regenerate external view/module output roots. Keep their previous
presentation until the replacement passes validation.

If the retained launcher predates the `modules` action, use its prepared Spack
shell and the native view/module commands in the delivered
[`BUILDER-HANDOFF.md` template](templates/BUILDER-HANDOFF.md.j2), under “Commands
used by the wrapper.” Select only completed, locked environments and check their
installed prefixes first. Refresh `default` before any additional set sharing
its root; `core_independent` must not use `--delete-tree`. Compiler/MPI producer
sets have separate roots. Adding an inventory does not make older compiler
specifications satisfy a newer launcher's graph policy, so qualify a controls
refresh separately instead of changing old specs or locks to satisfy it.

## Generate package modules from the existing installations

Do this after any accepted module-policy change, or when package modules/views
are missing. Skip generation when the current outputs already match the policy.
Their locations come from the workspace's effective `modules.yaml` and named
views, not from the directory where you invoke the command. A presentation-only
refresh does not move or regenerate them.

When the retained launcher's `--help` lists `modules`, run from the appropriate
site-approved context (the example uses an allocated compute node):

```bash
cd "$BUILD_WORKSPACE"
./cse-build compute modules
```

This checks that all non-external locked specs in the selected environments are
installed and their prefixes exist before refreshing any selected view/module
tree. It regenerates the named views and all applicable module sets without
fetching, concretizing or installing. `--surface shared` or `--surface platform`
selects one compiler surface; lock verification still covers the whole workspace.
The `compute` argument selects a context; it does not request an allocation.

### If the older launcher has no `modules` action

Retain that launcher and enter its prepared shell. Inspect each completed
environment's effective policy before touching its outputs:

```bash
cd "$BUILD_WORKSPACE"
./cse-build compute shell
# The following commands run inside that prepared shell.
ENV_DIR="$CSE_BUILD_WORKSPACE/environments/gcc/core"  # choose an existing environment
test -f "$ENV_DIR/spack.lock"
spack -e "$ENV_DIR" config get modules
spack -e "$ENV_DIR" python -c '
import os, sys
import spack.environment as ev
missing = [s for s in ev.active_environment().all_specs()
           if not s.external and (not s.installed or not os.path.isdir(str(s.prefix)))]
if missing:
    sys.stderr.write("Missing installed specs: " + ", ".join(str(s) for s in missing) + "\n")
    sys.exit(1)
'
```

Require that check to pass before continuing. If the module policy or named
views are absent, return to the explicit module-policy upgrade above. After
retaining the output trees and stopping their writers/readers:

```bash
spack -e "$ENV_DIR" env view regenerate
spack -e "$ENV_DIR" module tcl refresh --delete-tree -y
```

The unqualified refresh processes only the `default` set. Then refresh each
additional set actually present in this environment's effective policy:

| Set | Command after the default refresh |
| --- | --- |
| `core_independent` in a Core environment | `spack -e "$ENV_DIR" module tcl --name core_independent refresh -y` |
| `compiler_producer` for a built compiler | `spack -e "$ENV_DIR" module tcl --name compiler_producer refresh --delete-tree -y` |
| `mpi_producer` for a built MPI provider | `spack -e "$ENV_DIR" module tcl --name mpi_producer refresh --delete-tree -y` |

`core_independent` shares the default Core output root: do not use
`--delete-tree` for it. The producer sets must own separate roots as recorded in
the reviewed policy. Repeat for each intended completed environment, then
`exit` the prepared build shell to return to the operator shell.

From the operator shell, check the retained lock record:

```bash
cd "$BUILD_WORKSPACE"
sha256sum --check "$MODULE_REVIEW/locks.sha256"
```

## Test the workspace's entrance and lanes with `module use`

Use a fresh login or allocation shell with the site's module command available,
no active Spack environment, and no previously loaded CSE/compiler/MPI surface.
Use the site's clean-module reset procedure. Do not test consumer behavior from
inside `cse-build shell`, whose build paths and compiler state can mask errors.

First generate a private preview of the workspace's presentation and existing
installed packages using [Module presentation previews](MODULE-PRESENTATION.md).
In this clean consumer shell, set its absolute path. The example uses `init-GCC`;
replace it with the entrance name from this system's recorded values. Repeat in
another clean shell for its platform entrance.

```bash
PREVIEW=/absolute/path/to/module-review/lane-01
module use "$PREVIEW/entrances"
module avail
# Only the preview's CSE compiler entrances are initially visible.
module show cse/init-GCC
module load cse/init-GCC
module avail
# Individual Core/Common package modules and Serial/MPI selectors are visible.
module list
printf 'surface=%s\nC=%s\nC++=%s\nFortran=%s\n' \
  "${CSE_COMPILER:-missing}" "${CSE_CC:-missing}" \
  "${CSE_CXX:-missing}" "${CSE_FC:-missing}"
module show Serial
module load Serial
module avail
```

Check the filenames shown by `module show`: the entrance and lane must come
from this preview. No second `module use` is needed: exposing the lane directory
is the compiler entrance's job. If Serial/MPI do not appear after loading that
entrance, correct the presentation and generate another preview. Do not bypass
the failure by adding the lane directory manually. Older entrances can omit
the diagnostic `CSE_*` exports; inspect their module bodies and verify the exact
recorded compiler commands instead of deriving paths from absent variables.
Check that Foundation is exposed through its view, individual packages from
Core and Common are available without loading a Core/Common selector, and
selecting Serial exposes the intended
Serial packages. Load a recorded package/version, inspect its dependency
autoloads and conflicts, and run its representative installed consumer. Save
the exact module list, commands and output under the maintenance evidence path.

Repeat the same entrance → lane sequence from a clean shell with `MPI` instead
of `Serial`; inspect `CSE_MPICC`, `CSE_MPICXX` and `CSE_MPIFC` and run the approved native MPI smoke
test in an allocation. Use the system runbook's launcher and node count. A
module load or compiler `--version` alone does not establish runtime acceptance.
The CSE-GCC/external-Cray-MPICH candidate requires its native multi-node check.
`module use` changes only this shell's search path; it does not expose the
workspace to all users or change a login configuration.

## Copy the accepted presentation, then handle public activation separately

Once the required views, package modules and consumer checks pass, a retained
launcher with the corrected `publish-modules` layout can copy ready
entrances/lanes into the module root recorded by its build values. The current
launcher puts entrances in `<recorded-module-root>/entrances/cse/` and keeps the
compiler/lane/package trees under `<recorded-module-root>/<compiler>/`. If the
retained launcher still writes entrances directly under `<recorded-module-root>/cse/`,
qualify the scoped controls update above before using this publication step.
Source checkout updates alone do not change the launcher.

```bash
# Back in the operator shell, outside the clean consumer test session.
cd "$BUILD_WORKSPACE"
./cse-build login publish-modules
```

For restricted build values, this is the CSE team-review root. Check that exact
root with `module use <recorded-restricted-module-root>/entrances` in another clean team
session. The command does not refresh package modules or register a login
`MODULEPATH`. It withholds the external-MPI candidate lane described above;
passing a smoke test does not automatically clear that gate. Follow the system's
review/promotion procedure rather than bypassing it. If the older launcher
lacks this action, qualify a controls update separately; the private-preview
review above remains available without replacing the launcher.

Public user activation follows the common runbook's signed cache-only
publication and published-workspace acceptance. Only then register the approved
**published entrance** directory, `<published-module-root>/entrances`, in the
site's login `MODULEPATH` (or its already registered module hierarchy). Do not
register the parent package-module root: recursive discovery would expose
compiler/lane/package trees before selection. An older parent-root registration
must be changed deliberately after the new entrance passes its checks; merely
adding `/entrances` while keeping that parent active does not correct discovery.
The publisher leaves older root-level entrance files in place and does not edit
site login settings. Keep the restricted build workspace/root out of
the general user login path. Existing absolute paths inside generated modules
must refer to the accepted published prefixes/views; adding `module use` does
not relocate them. Production preparation-path selection remains open.

## Admit an inventory for existing frozen overlays

Use the trusted helper from the tested delivery to produce a separate inventory
of the workspace's existing recipe tree. Review the inventory and complete file
diff before admission:

```bash
REVIEWED_INVENTORY="$MODULE_REVIEW/overlay-inventory.json"
"$PREP_PYTHON" "$CONTENT/pilots/cse-pilot/templates/scripts/verify-overlay-inputs.py" \
  --root "$BUILD_WORKSPACE/package-repos" --candidate "$REVIEWED_INVENTORY"
```

Review that candidate file and the frozen recipes it describes before admission:

```bash
"$PREP_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --workspace "$BUILD_WORKSPACE" \
  --admit-overlay-inventory "$REVIEWED_INVENTORY" \
  --overlay-helper "$CONTENT/pilots/cse-pilot/templates/scripts/verify-overlay-inputs.py" \
  --dry-run
```

Repeat the second command without `--dry-run` after reviewing it. Admission runs
the explicitly selected trusted helper against a temporary copy of the existing
recipe tree, then installs only `package-repos/overlay-inventory.json` and
`scripts/verify-overlay-inputs.py`. Recipe and inventory contents are treated as
data; recipes are not imported. The transaction retains the exact helper and
inventory fingerprints and all existing recipe/pin fingerprints for recovery.
Changed recipes, missing patches or a stale reviewed inventory stop admission.

An older tag-only `configs/common/repos.yaml` stays byte-identical. The current
template's builtin commit is not silently applied. Admission records existing
local overlay bytes; it does not prove which checkout an old tag resolved to or
approve a different builtin checkout. A new recipe or pin is a separate candidate
change. After admission, a reviewed controls refresh can adopt the new gate;
remaining graph checks still apply to that workspace's recorded concrete inputs.

## Restore or recover without re-solving

For an applied refresh, use its exact printed/history record:

```bash
find "$BUILD_WORKSPACE/.cse-control-refresh" -name record.json -print
```

Select the record for the operation you intend to undo, inspect its recorded
paths/state, and assign its exact absolute path. Do not pass a wildcard or
automatically choose another operator's latest record:

```bash
REFRESH_RECORD="/absolute/workspace/.cse-control-refresh/<id>/record.json"
"$PREP_PYTHON" -m json.tool "$REFRESH_RECORD"
```

Then preview restoration:

```bash
"$PREP_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --workspace "$BUILD_WORKSPACE" --restore-from "$REFRESH_RECORD" --dry-run
# After checking the selected paths, repeat without --dry-run.
```

Restore refuses subsequent edits or mismatched backup contents. It has its own
retained undo record. An interrupted operation or incomplete rollback blocks
another ordinary update and reports the unfinished record. After addressing the
underlying disk/permission failure, use:

```bash
"$PREP_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
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
