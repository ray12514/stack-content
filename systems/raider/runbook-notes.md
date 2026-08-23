# Raider system notes

Use `stack-planning/docs/runbook.md` for every command and common promotion
gate. This file records only Raider-specific facts, choices, and findings.

## System identity

- Platform: generic Rocky/RHEL-family Linux.
- Scheduler: Slurm.
- Fabric: InfiniBand.
- Accelerator facts: NVIDIA A100 with `sm_80` is expected in the profile, but
  GPU builds are outside the Initial Conversion Trials.
- Provider shape: each compiler and OpenMPI pairing must be explicit rather
  than inferred from names.

## Current trial posture

- Build the shared GCC 12.5.0 producer, Foundation, Core, and build tools with
  GCC.
- Keep the exact external platform compiler decision in the reviewed build
  values.
- Build OpenMPI 4.1.8 once with GCC 12.5.0 and once with the selected platform
  compiler. Express both with `mpi.source: build`; do not teach
  `render-static` that all non-Cray systems build OpenMPI.
- Keep Foundation/Core/Common/Serial/MPI package intent in the CSE trial roster
  rather than the static platform catalog.

## Provisional module snapshot (2026-08-12)

This snapshot guides the first profile review; the live Cluster Inspector
profile remains authoritative.

- `amd/aocc/4.1.0`
- `amd/aocl/aocl/4.1.0`
- existing site module `penguin/openmpi/4.1.6/aocc-4.0.0`
- existing helper module `penguin/mpi-vars/aocc`

The existing OpenMPI module names AOCC 4.0.0 and therefore is not the selected
AOCC 4.1.0 pairing. Build OpenMPI 4.1.8 with AOCC 4.1.0 for the platform MPI
surface, and separately with the CSE GCC 12.5.0 surface.

Use this reviewed Step 7 selection after the current catalog confirms the AOCC
scope:

```bash
export CSE_SHARED_COMPILER_REF="gcc@12.5.0"
export CSE_SHARED_COMPILER_PUBLIC_NAME="init-GCC"
export CSE_SHARED_MPI_REF="openmpi@4.1.8"
export CSE_SHARED_MPI_SOURCE="build"
export CSE_PLATFORM_COMPILER_REF="aocc@4.1.0"
export CSE_PLATFORM_COMPILER_PUBLIC_NAME="init-AOCC"
export CSE_PLATFORM_MPI_REF="openmpi@4.1.8"
export CSE_PLATFORM_MPI_SOURCE="build"
export CSE_LOGIN_NODE_TYPE="login"
export CSE_COMPUTE_NODE_TYPE="cpu_compute"
export BUILD_JOBS="<approved-job-count>"
```

The values above assume the standard context keys `login` and `cpu_compute`.
Replace either value when Raider's catalog uses a different exact key.

## Profile and catalog review additions

In addition to the common runbook checks:

- reject false `/usr` GCC discoveries attached to unrelated library modules;
- confirm compiler versions from driver output, not module names alone;
- confirm the selected platform compiler prefix and full module chain.

## Refresh `cse-build` without replacing the workspace

Use this shortcut when Raider already has a valid initialized workspace and
lockfiles, but Stack Content changed `cse-build` or one of its generated helper
files. It does not rerender the static catalog, replace environment YAML,
reconcretize, clear caches, or touch installed packages.

Stop active `cse-build` processes first. From the existing operator session,
synchronize only the two inputs used by this refresh and rebuild Stack Composer
when its checkout changed:

```bash
source "$CSE_OPERATOR_SESSION_FILE"

for repo in stack-composer stack-content; do
  git -C "$WORK_ROOT/$repo" status --short --branch
done
# Stop here if either checkout contains unreviewed work.

for repo in stack-composer stack-content; do
  git -C "$WORK_ROOT/$repo" pull --ff-only
done

cd "$COMPOSER"
PYTHON="$CSE_PYTHON" bash scripts/build-pyz.sh
"$CSE_PYTHON" "$STACK_COMPOSER" --help >/dev/null
git -C "$COMPOSER" rev-parse HEAD \
  > "$CSE_TOOL_STATE_ROOT/stack-composer.commit"
```

Refresh the declared control set in place, then run the read-only status and
lock verification checks:

```bash
"$CSE_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --composer "$STACK_COMPOSER" \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --values "$BUILD_VALUES" \
  --workspace "$BUILD_WORKSPACE"

cd "$BUILD_WORKSPACE"
./cse-build login status
./cse-build login verify
```

The refresh renders a disposable workspace, confirms the blueprint, Raider
system, and catalog release match, and atomically replaces only `cse-build`,
its environment helpers, the lock verifier, and the builder handoff note. A
mismatch stops without changing the existing controls. If environment inputs
or package overlays changed, use the common runbook's appropriate workspace or
release recovery instead of this shortcut.

## Missing operator-session recovery

The generated operator activation script is stored in the operator's home
tree, not in the shared build workspace. If
`$WORK_ROOT/operator-sessions/raider/` is missing while the correctly rooted
Raider workspace still exists, recreate only the operator session. Do not
rerender the catalog, reinitialize the workspace, or reconcretize its existing
lockfiles for this recovery.

A path ending in `operator-sessions/raider//activate.sh` means the shell's
release variable is empty. Recover the release identities from the durable
workspace manifest rather than guessing them:

```bash
export WORK_ROOT="$HOME/STACK_TESTING"
export CONTENT="$WORK_ROOT/stack-content"
export RAIDER_TRIAL_ROOT="/p/app/CSE/initial-conversion-trials"
export RAIDER_WORKSPACE_PARENT="$RAIDER_TRIAL_ROOT/restricted/workspaces/raider/initial-conversion-trials"

find "$RAIDER_WORKSPACE_PARENT" \
  -mindepth 2 -maxdepth 2 \
  -name workspace-manifest.yaml -print
```

Select the current correctly rooted release printed above. Substitute that
exact directory name below when it is not `raider-trial-001`:

```bash
export RAIDER_TRIAL_RELEASE="raider-trial-001"
export RAIDER_MANIFEST="$RAIDER_WORKSPACE_PARENT/$RAIDER_TRIAL_RELEASE/workspace-manifest.yaml"

test -r "$RAIDER_MANIFEST"

export RAIDER_CATALOG_RELEASE="$(
  awk '$1 == "release:" {print $2; exit}' "$RAIDER_MANIFEST"
)"

test -n "$RAIDER_CATALOG_RELEASE"
printf 'trial=%s\ncatalog=%s\n' \
  "$RAIDER_TRIAL_RELEASE" "$RAIDER_CATALOG_RELEASE"
```

Recreate the local activation descriptor with the current checked-out Stack
Content script and the reviewed shared tool root. Do not pass `--overwrite`;
an existing session must be reviewed instead of silently replaced:

```bash
export STACK_BRANCH="codex/simplified-render-plan"
export RAIDER_TOOLS_ROOT="/p/app/CSE/tools"
export RAIDER_BOOTSTRAP_PYTHON="$WORK_ROOT/stack-composer/.venv/bin/python"

test -x "$RAIDER_BOOTSTRAP_PYTHON"
test -d "$RAIDER_TOOLS_ROOT/spack/1.2.2/.git"

"$RAIDER_BOOTSTRAP_PYTHON" \
  "$CONTENT/pilots/cse-pilot/scripts/create-operator-session.py" \
  --system raider \
  --work-root "$WORK_ROOT" \
  --trial-root "$RAIDER_TRIAL_ROOT" \
  --tools-root "$RAIDER_TOOLS_ROOT" \
  --bootstrap-python "$RAIDER_BOOTSTRAP_PYTHON" \
  --spack-mode shared \
  --catalog-release "$RAIDER_CATALOG_RELEASE" \
  --trial-release "$RAIDER_TRIAL_RELEASE" \
  --branch "$STACK_BRANCH" \
  --group cse
```

Source and verify the recovered session before entering the existing build
workspace:

```bash
source "$WORK_ROOT/operator-sessions/raider/$RAIDER_TRIAL_RELEASE/activate.sh"

test "$SYSTEM_NAME" = "raider"
test "$TRIAL_RELEASE" = "$RAIDER_TRIAL_RELEASE"
test "$CATALOG_RELEASE" = "$RAIDER_CATALOG_RELEASE"
test -r "$BUILD_WORKSPACE/workspace-manifest.yaml"
test -x "$BUILD_WORKSPACE/cse-build"
cse_session_status

cd "$BUILD_WORKSPACE"
./cse-build compute
```

The session generator also creates a blank `provider-selections.sh` scaffold.
That scaffold does not change or block the existing workspace's `cse-build`
entry point. Restore the reviewed Raider selections before regenerating build
values or initializing a replacement workspace; do not copy selections from
an obsolete or wrongly rooted release.

## Wrong-root recovery

The trial root must be the directory that directly contains `restricted/` and
`published/`, ending in `/initial-conversion-trials`. An earlier Raider session
that used the parent CSE directory must not be resumed. The old and correct
roots are:

```bash
export RAIDER_OLD_RESTRICTED_ROOT="/p/app/CSE/restricted"
export RAIDER_TRIAL_ROOT="/p/app/CSE/initial-conversion-trials"
export RAIDER_CORRECT_RESTRICTED_ROOT="$RAIDER_TRIAL_ROOT/restricted"

test "$RAIDER_OLD_RESTRICTED_ROOT" != "$RAIDER_CORRECT_RESTRICTED_ROOT"
test "${RAIDER_TRIAL_ROOT%/initial-conversion-trials}" = "/p/app/CSE"
```

The current Raider incident has one populated tree and one empty destination:

- `$RAIDER_OLD_RESTRICTED_ROOT` contains the existing catalog, workspace,
  lockfiles, install tree, views, modules, caches, and any completed packages;
- `$RAIDER_CORRECT_RESTRICTED_ROOT` contains no trial artifacts that need to be
  inspected, merged, or preserved before the correction.

Every old-artifact inventory or optional binary-salvage command below reads
from `$RAIDER_OLD_RESTRICTED_ROOT`. Every new catalog, workspace, release, and
build-cache path is created under `$RAIDER_CORRECT_RESTRICTED_ROOT`. Do not look
under the empty correct root for the old workspace, and do not copy or move the
old tree into it.

Installed prefixes, the Spack database, views, modules, and lockfiles contain
or derive from absolute paths. Preserve the old populated tree as
failed-release evidence while creating a new correctly rooted catalog, trial
release, operator session, and workspace. Reuse is allowed only by exact
concrete hash through the optional build-cache salvage step after the new
workspace is concretized.

### Raider correction sequence after installation has started

Use this sequence instead of the runbook's pre-installation `--overwrite`
recovery. The examples assume the incorrectly rooted release was
`raider-trial-001`; confirm that value from its workspace manifest before
continuing.

1. Stop every Raider `cse-build`, Spack install, fetch, and concretize process.
   Do not remove a stage or prefix while another process may hold a store lock.
   Record the old workspace and release paths:

   ```bash
   export RAIDER_OLD_TRIAL_RELEASE="raider-trial-001"
   export RAIDER_OLD_WORKSPACE="$RAIDER_OLD_RESTRICTED_ROOT/workspaces/raider/initial-conversion-trials/$RAIDER_OLD_TRIAL_RELEASE"
   export RAIDER_OLD_RELEASE_ROOT="$RAIDER_OLD_RESTRICTED_ROOT/releases/raider/$RAIDER_OLD_TRIAL_RELEASE"

   test -r "$RAIDER_OLD_WORKSPACE/workspace-manifest.yaml"
   test -d "$RAIDER_OLD_RELEASE_ROOT/spack/opt"
   ```

2. Inventory only the populated wrong-root release before changing
   repositories or creating the new workspace. Store the inventory in the
   operator's home tree; the empty correct root is not an input to this step:

   ```bash
   export RAIDER_RECOVERY_RECORD="$WORK_ROOT/recovery/raider/$RAIDER_OLD_TRIAL_RELEASE"
   install -d -m 0700 "$RAIDER_RECOVERY_RECORD"

   cp "$RAIDER_OLD_WORKSPACE/workspace-manifest.yaml" \
     "$RAIDER_RECOVERY_RECORD/old-workspace-manifest.yaml"
   find "$RAIDER_OLD_WORKSPACE/environments" -name spack.lock -type f \
     -exec sha256sum {} + \
     > "$RAIDER_RECOVERY_RECORD/old-lockfiles.sha256"
   find "$RAIDER_OLD_RELEASE_ROOT" -maxdepth 3 -type d -print \
     > "$RAIDER_RECOVERY_RECORD/old-release-directories.txt"
   du -sh "$RAIDER_OLD_WORKSPACE" "$RAIDER_OLD_RELEASE_ROOT" \
     > "$RAIDER_RECOVERY_RECORD/old-space.txt"
   ```

3. Synchronize all four repositories with runbook Step 2. Preserve any local
   profile or other reviewed system input; stop instead of pulling over
   unreviewed work. Capture the current tool-root selections from the old
   operator session, but do not resume that session for new release work:

   ```bash
   export RAIDER_OLD_SESSION="$WORK_ROOT/operator-sessions/raider/$RAIDER_OLD_TRIAL_RELEASE/activate.sh"
   source "$RAIDER_OLD_SESSION"
   export RAIDER_TOOLS_ROOT="$CSE_TOOLS_ROOT"
   export RAIDER_BOOTSTRAP_PYTHON="$CSE_BOOTSTRAP_PYTHON"
   export RAIDER_SPACK_MODE="$SPACK_RUNTIME_MODE"

   for repo in cluster-inspector stack-composer stack-content stack-planning; do
     git -C "$WORK_ROOT/$repo" status --short --branch
   done
   # Stop here if any checkout contains unreviewed work.
   for repo in cluster-inspector stack-composer stack-content stack-planning; do
     git -C "$WORK_ROOT/$repo" fetch origin
     git -C "$WORK_ROOT/$repo" switch "$STACK_BRANCH"
     git -C "$WORK_ROOT/$repo" pull --ff-only
   done
   ```

4. Create a new release identity under the correct root. Do not use
   `--overwrite` and do not reuse the old provider-selection file:

   ```bash
   export RAIDER_NEW_CATALOG_RELEASE="raider-catalog-002"
   export RAIDER_NEW_TRIAL_RELEASE="raider-trial-002"

   "$RAIDER_BOOTSTRAP_PYTHON" \
     "$CONTENT/pilots/cse-pilot/scripts/create-operator-session.py" \
     --system raider \
     --trial-root "$RAIDER_TRIAL_ROOT" \
     --tools-root "$RAIDER_TOOLS_ROOT" \
     --bootstrap-python "$RAIDER_BOOTSTRAP_PYTHON" \
     --spack-mode "$RAIDER_SPACK_MODE" \
     --catalog-release "$RAIDER_NEW_CATALOG_RELEASE" \
     --trial-release "$RAIDER_NEW_TRIAL_RELEASE" \
     --branch "$STACK_BRANCH" \
     --group cse

   source "$WORK_ROOT/operator-sessions/raider/$RAIDER_NEW_TRIAL_RELEASE/activate.sh"
   test "$CSE_TRIAL_ROOT" = "$RAIDER_TRIAL_ROOT"
   test "$CSE_RESTRICTED_ROOT" = "$RAIDER_CORRECT_RESTRICTED_ROOT"
   ```

5. Run common runbook Steps 5 and 6 to populate the previously empty correct
   CSE paths and render the new static catalog. Use the existing reviewed Raider
   profile when its machine facts have not changed; the profile is an
   operator-owned input and does not need to be recovered from the wrong-root
   tree. Rerun Cluster Inspector first only if those facts have changed. Confirm
   that `CATALOG`, `STATIC_ROOT`,
   `BUILD_RELEASE_ROOT`, `BUILD_WORKSPACE`, and `BUILDCACHE_ROOT` all begin with
   `$RAIDER_CORRECT_RESTRICTED_ROOT/` before continuing.

6. Re-enter the reviewed Raider provider selections shown above in the new
   `$CSE_PROVIDER_SELECTIONS`, reload the new session, and run common runbook
   Steps 7 and 8. The current workspace must be generated from the current
   Stack Content input, including GCC 12.5.0 `+binutils`. Do not copy old values,
   manifests, or lockfiles into the new release.

   ```bash
   vi "$CSE_PROVIDER_SELECTIONS"
   source "$CSE_OPERATOR_SESSION_FILE"

   "$CSE_PYTHON" \
     "$CONTENT/pilots/cse-pilot/scripts/create-build-values.py"
   "$CSE_PYTHON" "$STACK_COMPOSER" init-workspace \
     --blueprint "$CONTENT/pilots/cse-pilot" \
     --catalog "$CATALOG" \
     --values "$BUILD_VALUES" \
     --output "$BUILD_WORKSPACE"

   cd "$BUILD_WORKSPACE"
   ./cse-build login concretize
   ./cse-build login verify
   ```

7. Treat the new verified lockfiles as authoritative. The old binaries are not
   reusable merely because their package names and versions match. GCC
   `+binutils` changes the GCC hash and normally changes every dependent hash.
   Do not push the old environment wholesale to the new build cache.

   Build-cache salvage is optional and occurs only after the new
   concretization. Inventory old installed hashes and new concrete hashes with
   the pinned Spack command, then compare them:

   ```bash
   cse_session_use_spack
   install -d -m 2770 -g cse "$BUILD_EVIDENCE/root-correction"
   export RAIDER_HASH_EVIDENCE="$BUILD_EVIDENCE/root-correction"

   for environment_dir in "$RAIDER_OLD_WORKSPACE"/environments/*/*; do
     spack -e "$environment_dir" find --no-groups -d -H
   done | sort -u > "$RAIDER_HASH_EVIDENCE/old-installed.txt"

   for environment_dir in "$BUILD_WORKSPACE"/environments/*/*; do
     spack -e "$environment_dir" find --show-concretized --no-groups -d -H
   done | sort -u > "$RAIDER_HASH_EVIDENCE/new-concrete.txt"

   comm -12 \
     "$RAIDER_HASH_EVIDENCE/old-installed.txt" \
     "$RAIDER_HASH_EVIDENCE/new-concrete.txt" \
     > "$RAIDER_HASH_EVIDENCE/exact-reuse-candidates.txt"
   cat "$RAIDER_HASH_EVIDENCE/exact-reuse-candidates.txt"
   ```

   An empty candidate file means rebuild from the new locks. For a nonempty
   file, remove externals and any package that has not already passed its
   applicable restricted-build validation. If signing is ready, push only each
   approved exact hash with `buildcache push --signed --only package`; never use
   the old environment's no-argument whole-environment push. Update and verify
   the new cache index afterward:

   ```bash
   cp "$RAIDER_HASH_EVIDENCE/exact-reuse-candidates.txt" \
     "$RAIDER_HASH_EVIDENCE/approved-reuse.txt"
   vi "$RAIDER_HASH_EVIDENCE/approved-reuse.txt"

   export RAIDER_OLD_QUERY_ENV="$RAIDER_OLD_WORKSPACE/environments/gcc/core"
   while IFS= read -r concrete_hash; do
     test -n "$concrete_hash" || continue
     spack -e "$RAIDER_OLD_QUERY_ENV" \
       buildcache push --signed --only package --fail-fast \
       "$BUILDCACHE_URL" "$concrete_hash" || break
   done < "$RAIDER_HASH_EVIDENCE/approved-reuse.txt"

   spack buildcache update-index --keys "$BUILDCACHE_URL"
   spack buildcache check-index --verify all "$BUILDCACHE_URL"
   ```

   The edited approval file is part of the recovery evidence; it must not
   contain an external or an unvalidated binary. If signing or validation is
   not ready, skip salvage and rebuild; do not create an unsigned recovery
   path.

8. Install and validate the new release through the normal runbook Steps 10 and
   11. `./cse-build compute install` checks the correctly rooted private build
   cache automatically and builds every missing exact hash from source. A cache
   hit cannot change the new lockfile.

9. Keep the old tree until every required new lane is installed, exercised,
   and recorded. Then obtain the release owner's approval to remove only the
   confirmed Raider-owned old catalog, workspace, release, build-cache, and
   evidence paths. Do not delete or move `/p/app/CSE/restricted` as a unit, and
   do not remove shared source or miscellaneous caches merely because Raider
   used them. The corrected workspace and cache must not retain an upstream,
   mirror, include, or install-tree reference to the wrong root.

## Readline 8.3 patch fetch recovery (2026-08-20)

Raider's login-node fetch reached the network and downloaded the other sources,
but the GNU mirror redirect selected
`mirror.us-midwest-1.nexcess.net`, which returned HTTP 404 for
`readline83-003`. This is a remote mirror synchronization failure, not a login
context, workspace, build-stage, or source-cache path failure. The canonical
GNU file has the checksum required by the pinned Readline recipe:

```text
72dee13601ce38f6746eb15239999a7c56f8e1ff5eb1ec8153a1f213e4acdb29
```

Seed that one verified patch into the source cache selected by the generated
GCC Core environment, then rerun the normal fetch. Do not reconcretize or
replace the existing lockfiles:

```bash
cd "$BUILD_WORKSPACE"

export RAIDER_FETCH_ENV="$BUILD_WORKSPACE/environments/gcc/core"
export RAIDER_READLINE_PATCH_SHA="72dee13601ce38f6746eb15239999a7c56f8e1ff5eb1ec8153a1f213e4acdb29"
export RAIDER_SOURCE_CACHE="$(
  spack -e "$RAIDER_FETCH_ENV" python -c \
    'import spack.config; print(spack.config.get("config:source_cache"))'
)"
export RAIDER_READLINE_CACHE_DIR="$RAIDER_SOURCE_CACHE/_source-cache/archive/${RAIDER_READLINE_PATCH_SHA:0:2}"
export RAIDER_READLINE_CACHE_FILE="$RAIDER_READLINE_CACHE_DIR/$RAIDER_READLINE_PATCH_SHA"
export RAIDER_READLINE_PART_FILE="$RAIDER_READLINE_CACHE_FILE.$$.part"

printf 'RAIDER_SOURCE_CACHE=%s\n' "$RAIDER_SOURCE_CACHE"
test -n "$RAIDER_SOURCE_CACHE"
umask 0007
mkdir -p "$RAIDER_READLINE_CACHE_DIR"
test -w "$RAIDER_READLINE_CACHE_DIR"

curl -fL --retry 5 \
  https://ftp.gnu.org/gnu/readline/readline-8.3-patches/readline83-003 \
  -o "$RAIDER_READLINE_PART_FILE"
printf '%s  %s\n' \
  "$RAIDER_READLINE_PATCH_SHA" "$RAIDER_READLINE_PART_FILE" \
  | sha256sum -c -
mv "$RAIDER_READLINE_PART_FILE" "$RAIDER_READLINE_CACHE_FILE"
chmod 0660 "$RAIDER_READLINE_CACHE_FILE"

./cse-build login fetch
```

The generated `config:source_cache` value names the cache root. Spack 1.2.2
places checksum-addressed artifacts below that root's
`_source-cache/archive/<digest-prefix>/` mirror layout. Do not omit the
`_source-cache` path component when seeding a single artifact.

The preliminary miss below the private build cache's separate `_source-cache`
namespace is expected when that mirror does not yet contain the patch. After
the command above, Spack reads the checksum-addressed file from the configured
restricted source cache. Previously downloaded archives remain cached and are
reused.

## Dakota 6.23/6.24 Boost diagnosis (2026-08-20)

Raider reached Dakota configuration with both `MPI_CXX_LIBRARIES` and
`MPIEXEC` under the CSE-built OpenMPI 4.1.8 prefix, and CMake reported Boost
1.90.0. The visible CMP0144 and CMP0167 messages are developer warnings; they
are not the fatal error. This differs from the earlier ambient-MPI failure in
which CMake selected an implementation below `/usr/lib64/mpi`.

The CSE trial overlay applies `boost-system-header-only.patch` to Dakota
6.23.0 and 6.24.0. Before changing the spec or reconcretizing again, verify the
actual staged source and capture the fatal end of the build log:

```bash
cd "$BUILD_WORKSPACE"
./cse-build compute

export RAIDER_DAKOTA_STAGE="$(
  find "$CSE_BUILD_STAGE" -maxdepth 1 -type d \
    -name 'spack-stage-dakota-6.2[34].0-*' \
    -exec ls -td {} + 2>/dev/null \
    | head -1
)"
export RAIDER_DAKOTA_LOG="$(
  find "$CSE_BUILD_STAGE" -maxdepth 1 -type f \
    -name 'spack-stage-dakota-6.2[34].0-*.log' \
    -exec ls -t {} + 2>/dev/null \
    | head -1
)"

printf 'RAIDER_DAKOTA_STAGE=%s\nRAIDER_DAKOTA_LOG=%s\n' \
  "$RAIDER_DAKOTA_STAGE" "$RAIDER_DAKOTA_LOG"

if test -n "$RAIDER_DAKOTA_STAGE" \
  && test -d "$RAIDER_DAKOTA_STAGE/spack-src"; then
  grep -RFn 'Boost::system' \
    "$RAIDER_DAKOTA_STAGE/spack-src/cmake/DakotaFindSystemTPLs.cmake" \
    "$RAIDER_DAKOTA_STAGE/spack-src/src/plugins/CMakeLists.txt" \
    "$RAIDER_DAKOTA_STAGE/spack-src/src/surrogates/unit/CMakeLists.txt" \
    || true
else
  printf 'No retained Dakota 6.23/6.24 stage directory was found.\n' >&2
fi

if test -n "$RAIDER_DAKOTA_STAGE" \
  && test -f "$RAIDER_DAKOTA_STAGE/spack-build-out.txt"; then
  tail -n 150 "$RAIDER_DAKOTA_STAGE/spack-build-out.txt"
elif test -n "$RAIDER_DAKOTA_LOG" && test -f "$RAIDER_DAKOTA_LOG"; then
  tail -n 150 "$RAIDER_DAKOTA_LOG"
else
  printf 'No Dakota 6.24 failure log was found.\n' >&2
fi
```

Interpret the result as follows:

- A retained stage directory with no `Boost::system` matches means all three
  known Dakota call sites were patched. Diagnose the final error in the build
  output; do not treat the policy warnings as the failure.
- Any `Boost::system` match means the staged source is unpatched or only
  partially patched. Stop the install and verify that the `cse_trials` package
  repository precedes the builtin repository before creating a fresh Dakota
  concrete hash.
- If Spack removed the stage directory but retained its sibling `.log` file,
  source-level patch verification is unavailable. Use the log to identify the
  actual failure; do not infer from the missing stage that the patch was absent.
- If neither the stage nor its sibling log exists, preserve the failed install
  output and use the exact path Spack reported. Do not guess at another stage.

Record the grep output, the final 150 log lines, the Dakota concrete hash, and
the active `cse_trials` repository path in the Raider trial evidence before
selecting the next recovery action.

### Recover an already-rendered Raider workspace

A fatal `Boost::system` target error from
`src/surrogates/unit/CMakeLists.txt:26` means the concrete Dakota root predates
the complete CSE overlay, or the generated workspace copy of that overlay is
not active. It is not an MPI failure when `MPI_CXX_LIBRARIES` and `MPIEXEC`
already resolve below the CSE OpenMPI prefix.

Update the generated workspace overlay, prove that it is byte-for-byte current,
force only the affected Dakota roots to receive new hashes, and retry Dakota:

```bash
git -C "$CONTENT" pull --ff-only

RAIDER_DAKOTA_SOURCE="$CONTENT/pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/packages/dakota"
RAIDER_DAKOTA_DESTINATION="$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials/packages/dakota"

install -d -m 2770 -g "$CSE_GROUP" "$RAIDER_DAKOTA_DESTINATION"
install -m 0660 -g "$CSE_GROUP" \
  "$RAIDER_DAKOTA_SOURCE/package.py" \
  "$RAIDER_DAKOTA_SOURCE/boost-system-header-only.patch" \
  "$RAIDER_DAKOTA_DESTINATION/"

cmp "$RAIDER_DAKOTA_SOURCE/package.py" \
  "$RAIDER_DAKOTA_DESTINATION/package.py"
cmp "$RAIDER_DAKOTA_SOURCE/boost-system-header-only.patch" \
  "$RAIDER_DAKOTA_DESTINATION/boost-system-header-only.patch"

for environment in \
  "$SHARED_COMPILER_NAME/mpi-$SHARED_MPI_NAME" \
  "$PLATFORM_COMPILER_NAME/mpi-$PLATFORM_MPI_NAME"; do
  MPI_ENV="$CSE_BUILD_WORKSPACE/environments/$environment"
  test -f "$MPI_ENV/spack.yaml"

  spack -e "$MPI_ENV" repo list

  printf 'Dakota hashes before forced reconcretization (%s):\n' \
    "$environment"
  spack -e "$MPI_ENV" find -cl dakota

  spack -e "$MPI_ENV" concretize -f --reuse-deps -j 1

  printf 'Dakota hashes after forced reconcretization (%s):\n' \
    "$environment"
  spack -e "$MPI_ENV" find -cl dakota
done

cd "$CSE_BUILD_WORKSPACE"
./cse-build compute verify

RAIDER_SHARED_MPI_ENV="$CSE_BUILD_WORKSPACE/environments/$SHARED_COMPILER_NAME/mpi-$SHARED_MPI_NAME"
spack -e "$RAIDER_SHARED_MPI_ENV" install --only-concrete \
  -j "$BUILD_JOBS" --fail-fast \
  dakota@6.23.0 dakota@6.24.0
```

Both `cmp` commands must exit zero. For both MPI environments, `spack repo
list` must show the generated workspace `cse_trials` repository ahead of the
builtin repository, and both Dakota hashes must change. If a Dakota hash does
not change, stop; do not spend another build attempt on the old concrete root.
Correct the repository order or workspace overlay first.

This recovery preserves the workspace, OpenMPI, Boost, and all other installed
dependencies. Do not delete the workspace or reconcretize unrelated roots.

## Restricted build and cache gates

- Both compiler surfaces and both CSE-built OpenMPI toolchains must be explicit
  in the generated environments.
- Both Serial environments contain no MPI implementation.
- Each MPI environment uses the OpenMPI 4.1.8 producer built with its compiler.
- Every lane is exercised on Raider before its concrete specs enter the private
  CSE build cache.
- The cache contains both built OpenMPI producers and the CSE-owned packages
  required by the approved locks.

## Publication gates

- Copy the approved restricted lockfiles; do not reconcretize the publication
  workspace.
- Install with `--only-concrete --use-buildcache=only` into the published
  prefix. A missing OpenMPI or package binary holds publication.
- Load the same external platform compiler modules used during restricted
  validation. The GCC and OpenMPI producer modules come from the CSE release.
- Verify all published hashes match the restricted hashes.
- Regenerate package modules and test the compiler front door followed by one
  lane selector from clean login and compute sessions.

## Runtime acceptance

Apply `stack-planning/docs/generic_linux_acceptance_checklist_v1.md`. At minimum
verify:

- compiler and MPI wrappers resolve from the selected surface;
- multi-node MPI launch through Slurm;
- a representative package through the published module hierarchy.

## Current run record

- Current release state:
- Last successful checkpoint (1-8):
- Held checkpoint/lane, if any:
- Exact failed command, exit status, and evidence path:
- Durable input or concrete hash changed (`yes` or `no`):
- Recovery decision (`resume same release` or `new release`):
- Earliest checkpoint to rerun and exact next command:
- Profile release/date:
- Catalog release/path:
- Restricted build values/workspace:
- Publication values/workspace:
- Selected compiler:
- Selected MPI:
- CSE group and approved roots:
- Private build-cache URL/signing policy:
- Concretization status:
- Per-lane build/runtime/cache status:
- Cache-only publication and hash comparison:
- Published runtime/module findings:
- Release-owner approval:
