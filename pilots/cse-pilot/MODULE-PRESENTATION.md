# Iterate on modules for an existing build

Use the existing locks and installed prefixes to review the compiler entrance,
Serial/MPI selectors, package names, and dependency loading. A presentation
change does not require reconcretization, package installation, a new catalog,
or a Composer upgrade. This procedure generates a **private preview**, leaving
the workspace inputs, existing views, and published module tree unchanged.

Start with the retained workspace and its recorded Spack. The helper currently
supports the CSE Tcl module policy on Spack **1.2.2**, with Python **3.6+**.
The generated files are **Tcl modulefiles** (`#%Module1.0`). Tcl Environment
Modules (TModules) is the primary consumer implementation for these systems;
Lmod can also read those files. Test with the implementation actually used at
the site. The helper does not require Lmod or generate Lua modulefiles.

## Decide whether the existing controls suffice

The relevant pieces have separate jobs:

| Piece | Needed for this review | When it needs a change |
|---|---|---|
| Existing `spack.lock` and installed prefixes | The precise built packages | Missing installs must finish before that environment can be previewed |
| Effective `modules` configuration | Package projections, filters and dependency loading | Review alternate policy when names/filters/autoload need adjustment |
| Existing named views | Any `use_view` target in the chosen module policy | Generate missing views deliberately through the retained workspace procedure |
| Workspace `modulefiles/` | Compiler entrances and Serial/MPI selectors | Review alternate files when exposure or lane selection needs adjustment |
| `cse-build` | Prepares the recorded runtime and site environment | Older `shell` support is enough for the standalone helper |
| Composer | Not used by this helper | Needed only if you choose to render new authored controls/policy |

An old launcher without a `modules` or `module-preview` action does **not** by
itself require a controls refresh. Enter its prepared shell and invoke the
standalone helper from the reviewed content checkout. If its shell preparation
itself needs a separately qualified fix, follow [CONTROL-REFRESH.md](CONTROL-REFRESH.md).
Do not replace all controls merely to change module names.

Keep the adjacent `workspace-build.py` helper with it. Standalone previews share
the same workspace maintenance lock as current solve/build/overlay commands, so
they cannot read a selected environment while those commands temporarily change
its manifest. Coordinate older launchers and manual Spack commands separately.

After the saved operator activation and selection of reviewed content, export
the helper location before entering the existing workspace shell:

```bash
export MODULE_PREVIEW_HELPER="$CONTENT/pilots/cse-pilot/scripts/module-preview.py"
cd "$BUILD_WORKSPACE"
./cse-build compute shell
```

In that prepared shell, the helper defaults to `CSE_BUILD_WORKSPACE`,
`CSE_MODULES_ROOT` and `$SPACK_ROOT/bin/spack`. It invokes the recorded Spack in
child processes with user/system configuration disabled and private caches.
It retains the recorded environment include scopes and rejects active
user/system/site scopes or includes outside the workspace (apart from the
recorded Spack defaults). It does not add a user scope or alter the active
environment in this shell.

```bash
python3 "$MODULE_PREVIEW_HELPER" --check-only
```

The check covers all recorded environments by default. For a partly built
workspace, select only completed environments explicitly, repeating
`--environment gcc/core` as needed. Missing locks, nonexternal installed-prefix
records, required view directories, recipes or enabled Tcl policy stop the
check with a specific reason. Naming collisions and projections escaping the
preview tree also stop it. Failed preflight leaves the requested output absent
and prints a retained failure-record path.

Missing/older module policy can be supplied privately with `--policy-tree`
without adopting it into the build workspace. When ready to adopt a reviewed
policy, use the explicit `--scope module-policy` transaction in
[CONTROL-REFRESH.md](CONTROL-REFRESH.md#upgrade-package-module-policy-in-an-older-workspace).
Missing/older entrances and lanes can similarly be supplied with
`--presentation-tree`, or later adopted with `--scope presentation`. The check
does not assert that site module chains load or that a named view contains the
right files: clean-shell and runtime checks below establish those properties.

## Generate the first lane-layout preview

Choose a new directory outside the workspace, installation tree, existing
views, and recorded package-module root. Use paths without spaces or Tcl
metacharacters. Each iteration gets a new directory; the helper refuses to
overwrite a prior preview.

```bash
PREVIEW="$BUILD_EVIDENCE/module-review/lane-01"
python3 "$MODULE_PREVIEW_HELPER" --output "$PREVIEW"
```

The helper preflights every selected environment before writing any package
modules. It then writes these artifacts:

| Preview path | Contents |
|---|---|
| `entrances/` | Only the `cse/` compiler entrances; this is the initial consumer `MODULEPATH` root |
| `modulefiles/` | Private compiler, Core/Common, lane selector, and package trees, exposed by the entrance and lane modules |
| `presentation/` | Editable copy of the entrance/lane inputs, retaining the original recorded module-root spelling |
| `policies/<compiler>/<kind>/modules.yaml` | Editable effective policy, retaining the original recorded module roots |
| `preview.json` | Status, consumer module path, source hashes, selected environments, package hashes/prefixes, module filenames and required views |
| `state/` | Private caches, requests, reports and Spack logs |

No views are regenerated. Generated modules may refer to the existing views
and installed prefixes, so this is a review on the same system, not a portable
publication tree. No fetch, concretize, install, cache push, module publication
or global `MODULEPATH` update occurs. A write error records `status: failed`;
keep the evidence and use a new output directory after correction.

Review the `generated` status and the module inventory. A partial environment
selection is useful for package-name experiments, but its entrance may refer
to Core/Common/compiler/MPI modules omitted from that preview. For a full
compiler/lane test, include that surface's completed Core, Common, Serial and
MPI environments. Do not let an older published module satisfy a missing
preview dependency unnoticed.

## Test the preview in a clean consumer shell

Exit the prepared Spack shell. In a fresh login or allocation shell, use the
site's clean-module procedure and reassign the absolute preview path. Do not
source the build environment for this test. There is **one initial `module use`**.
The CSE entrance exposes its Core/Common modules and available lanes; selecting
a lane exposes that lane's packages. **Core and Common are package groups, not
user-selectable lane modules.** After loading the compiler entrance,
`module avail` shows their individual package names (for example
`cmake/<version>` and `lapack/<version>`) alongside the `Serial` and `MPI`
selectors. Those packages are available to load, not all loaded automatically.
There is no `module load Core` or `module load Common` step. Their separate
build environments are an implementation detail of building the stack.

Example for the GCC surface:

```bash
PREVIEW=/absolute/path/to/module-review/lane-01
module use "$PREVIEW/entrances"
module avail
# The preview initially shows cse/init-GCC and the platform compiler entrance
# (for example cse/init-CCE), without raw gcc/... or cce/... package trees.
module show cse/init-GCC
module load cse/init-GCC
module avail
# Individual Core/Common package modules and Serial/MPI selectors are visible.
module show Serial
module load Serial
module avail
module list
# The selected Serial packages are now visible.
```

The copied entrance points to this preview's compiler/Core/Common/lanes
directories. Do not add a lane directory manually: if loading the entrance does
not expose its lanes, that entrance has failed this test. Older entrances can
omit `CSE_COMPILER`; automatic lane exposure is still required. Keep the private
`modulefiles/` parent out of the initial `MODULEPATH`: recursive discovery can
show the backing compiler/lane/package tree before entrance selection.
Confirm the filenames printed by `module show` belong to this preview. Inspect and load
the intended package/version, check its prefix and dependency modules, and
run a representative consumer. Check unloading and Serial/MPI mutual exclusion.
Repeat with `module load MPI` in a separate clean shell, starting with the same
single `module use` and compiler entrance, then use the site's native launcher.
Repeat the entrance → lane → package sequence for the platform compiler, such
as `cse/init-CCE`, using that system's actual entrance name. A GPU lane belongs
at the same selection level when configured; this CPU trial supplies Serial/MPI.
Compiler or MPI naming changes must still load the exact accepted compiler and
provider. A successful `module avail` is not runtime acceptance.

For a deliberate single-environment package-name experiment only, use
`module use "$PREVIEW/modulefiles/gcc/serial"` after the reviewed compiler/site
prerequisites. Record that this tested package presentation only, not the full
compiler entrance and lane sequence.

## Iterate without touching the current publication

Edit only the saved candidate `presentation/` files to try a different lane
layout. Edit the saved candidate `policies/.../modules.yaml` to try Spack Tcl
`projections`, `include`/`exclude`, `conflict`, `autoload` or prerequisites. Keep
the policy's top-level `modules` section and recorded absolute roots; the
helper redirects roots for each preview. It rejects any other top-level
configuration section. `use_view` may select an existing view or be `false` for
direct prefix modules; it cannot create a new view or change the solve.

Use Spack's actual spec fields for projections and inspect the resulting
names. Compiler/MPI/dependency labels are presentation of the existing DAG;
changing a label does not change how a package was built. Autoloaded or
prerequisite modules must exist under the selected policy and visible preview
paths. The helper checks filename collisions across sets and environments;
the consumer test checks loading behavior.

For example, the pinned Spack 1.2.2 module documentation supports these
projection fields. This is a fragment to merge into the candidate's existing
`modules.default.tcl` policy, keeping its roots, filters and other settings:

```yaml
projections:
  netcdf-cxx4: '{name}/{version}-netcdf{^netcdf-c.version}-hdf5{^hdf5.version}'
  '^mpi': '{name}/{version}-{^mpi.name}-{^mpi.version}-{compiler.name}-{compiler.version}'
  all: '{name}/{version}-{compiler.name}-{compiler.version}'
```

The dependency-specific rules apply only to specs that have those
dependencies; keep specific rules ahead of broader matches. Review actual
rendered compiler/provider labels against the lock. Compiler-independent or
external specs can need separate rules, and a missing/`none` label is not an
accepted compiler identity. This example is an experiment, not a required
change to the existing naming convention.

Back in the retained prepared shell:

```bash
PREVIOUS="$BUILD_EVIDENCE/module-review/lane-01"
NEXT="$BUILD_EVIDENCE/module-review/lane-02"
python3 "$MODULE_PREVIEW_HELPER" --output "$NEXT" \
  --presentation-tree "$PREVIOUS/presentation" \
  --policy-tree "$PREVIOUS/policies"
```

Review the new inventory and repeat the clean consumer tests. To reject an
iteration, stop using its module path and retain its evidence. No rollback of
the existing workspace or publication is needed because neither was changed.

After acceptance, record the authored policy/presentation changes and follow
[CONTROL-REFRESH.md](CONTROL-REFRESH.md) for the explicit adoption, generation
and publication decision. **Do not move or copy this preview tree into the
published root**: its absolute references point to this preview and the current
build views. Preserve the existing accepted publication until the replacement
has passed its own checks. Public production activation remains a separate
decision.
