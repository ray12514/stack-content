# Stack Composer update during the current CSE trial

## Scope

This procedure updates the preparation tool, not the installed CSE stack.
It applies to Blueback and the other current trial systems. The existing
catalog, values, eight-environment layout, Spack checkout, lockfiles, installed
prefixes, build cache, and generated `cse-build` remain the trial of record.
Do not rerun initialization over that workspace to adopt a tool safety fix.

For deliberate adoption of module presentation or workspace controls, use the
[scoped refresh and recovery procedure](CONTROL-REFRESH.md). Updating this
source branch and refreshing a generated cluster workspace are separate steps.

The [2026-09-04 checkpoint receipt](checkpoints/2026-09-04-composer-stabilization.md)
records the matching implementation commits and candidate artifact checksums.

## Update and resume

After the approved Stack Composer and Stack Content changes are synchronized,
source the same saved operator session used for this trial. A saved session
loads the current `operator-session.sh`; it does not need to be recreated.

```bash
source "$CSE_OPERATOR_SESSION_FILE"
unset CSE_STACK_COMPOSER_NATIVE
cse_rebuild_tools composer
cse_stack_composer --help
cse_stack_composer --licenses
cse_session_status
```

If this is a fresh login, source the saved `activate.sh` by its recorded path
first; it supplies `CSE_OPERATOR_SESSION_FILE` and the other paths. The rebuild
helper requires a reviewed clean tool checkout and records the tool commit only
after the build and smoke check succeed. A failed build must not be marked
current. `cse_rebuild_tools composer` does not rebuild Cluster Inspector.

Python 3.9 or newer remains supported for the current `.pyz` path. No release
directory rename, package configuration edit, catalog promotion, or lockfile
refresh is required. Continue the unfinished build through the existing
workspace's `cse-build` and the system runbook at the step already in progress.
Do not replace that entry point with the generic `spack-build` companion.

## Compare a candidate without changing the active trial

Run this only from the restored preparation session with the recorded catalog
and build-values file. The command renders files; it does not invoke Spack or
write to the install/cache roots referenced by those values.

```bash
composer_check=$(mktemp -d "${WORKDIR}/${USER}-composer-check.XXXXXX")
cse_stack_composer init-workspace \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --catalog "$CATALOG" \
  --values "$BUILD_VALUES" \
  --output "$composer_check/workspace"
bash -n "$composer_check/workspace/cse-build"
bash -n "$composer_check/workspace/env/setup-build-env.sh"
diff -ru "$BUILD_WORKSPACE/environments" "$composer_check/workspace/environments"
diff -ru "$BUILD_WORKSPACE/configs" "$composer_check/workspace/configs"
```

Review any difference before taking further action. Differences can reflect
previously approved trial overlays or older content, not only the renderer.
New `workspace-manifest.yaml` files contain additional input digests; that
metadata change does not require a new concrete graph. The temporary parent is
private to this operator; it is not a group-permission or publication test.
Do not run the candidate's build commands against the active trial roots.

## Optional native executable comparison

The native candidate contains a `stack-composer` executable and an adjacent
`_internal` directory. Keep them together. Use a reviewed Linux artifact that
matches the host architecture and C library baseline. A macOS build is not a
Linux executable.

```bash
export CSE_STACK_COMPOSER_NATIVE="<absolute candidate directory>/stack-composer"
cse_stack_composer --help
cse_stack_composer --licenses
```

The helper executes this path directly. It does not pass it to Python and does
not change `STACK_COMPOSER`, `CSE_PYTHON`, the recorded tool commit, or the
current `.pyz`. Use a separate temporary output directory when repeating the
candidate comparison. Return to the existing launcher with:

```bash
unset CSE_STACK_COMPOSER_NATIVE
```

Native packaging remains a candidate until target-system, shared-filesystem,
dependency-security, and complete runtime-license checks pass. The Click update
also needs a Python-support decision; this update does not silently drop hosts
running Python 3.9.

## Offline delivery and copied-workspace checks

The [2026-09-06 offline receipt](checkpoints/2026-09-06-offline-delivery.md)
records the exact payload revisions, test results, and delivery checksum file.

Use the matching source revisions and artifacts from the delivery's
`RELEASE_INPUTS.json`. Do not mix a new `spack-build` helper with an unrelated
Composer release or substitute a different blueprint checkout without review.
Cluster Inspector is not included in this Composer delivery.

Stack Composer's `docs/offline-delivery.md` provides the connected acquisition,
offline rebuild, and two-container relocation commands. The delivery includes
the exact Composer, Content, and Planning source exports, hash-locked native
and portable Python dependency sets, and the saved builder image. Rebuilding
the tools requires no access to the original repositories or package index.

The relocation check uses new Linux and Cray-shaped model workspaces. Original
source directories and catalogs are not mounted in the receiving container.
The generated CSE helpers validate their relocated configuration with the
pinned Spack runtime. Partial and complete lock fixtures check byte
preservation only; they do not claim completed HPC builds.

Spack, the approved builtin recipe mirror, installed prefixes, cache roots,
views, modules, and compiler/MPI paths remain explicit site prerequisites.
Moving a workspace does not relocate those resources. Do not run the model's
build helper against an active trial's install or cache roots, and do not
regenerate an existing trial workspace to adopt a packaging-only change.

For a received artifact, use its supplied executable directly:

```bash
# Current portable default, with the host's supported Python.
python3 /absolute/path/to/stack-composer.pyz --help

# Optional Linux native candidate; retain the adjacent _internal directory.
/absolute/path/to/native/stack-composer --help
```

## Adding packages later

Add normal Spack specs to the reviewed roster and create a new candidate with
copied inputs. Compare all affected locks, producer hashes, externals, and
runtime behavior before promotion. Keep Foundation libraries per compiler
surface during this trial. Command-only tools may be tested for broader reuse;
C++, Fortran, OpenMP, MPI, and GPU interfaces require their own compatibility
evidence. A shared package name/version alone does not establish compatibility.

The longer-term assembler/planner relationship and package-admission matrix
are documented in Stack Composer's `docs/workspace-workflows-2026-09.md` and
Stack Planning's post-trial consumption-environment plan. Neither changes the
active trial's roster or layout.
