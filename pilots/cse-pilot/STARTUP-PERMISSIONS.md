# Fast startup and permission maintenance

Interactive `./cse-build login`, `compute`, and `shell` check declared roots
without recursively repairing generated content. Finite Spack actions retain full
Spack checkout/input/scope validation and repair owned output on exit. `status`,
`concretize`, `verify`, and the explicit `permissions` command verify foreign-owned
entries too. After manual commands inside a shell, run `permissions` before a
builder handoff. Umask/setgid cannot fix files explicitly created as 0600/0700.

```bash
./cse-build login permissions                     # default: 4 workers
./cse-build login permissions --permission-jobs 16 # tune against Lustre results
./cse-build login status
```

Workers traverse disjoint subtrees once, change only differing owned entries,
preserve executable modes, skip symlinks and filesystem boundaries, and leave
installed prefixes under Spack's policy. The install root is checked without
descending into its database, locks or prefixes, including when it is nested
inside the workspace. Permissions are Unix group/mode maintenance, not a
recursive POSIX ACL migration. The operation reports visited/changed counts and
failures. A bad foreign-owned entry fails handoff with its path and owner UID.

`--permission-jobs` accepts 1–32; `CSE_PERMISSION_JOBS` sets the inherited default.
This budget is independent of `BUILD_JOBS`. More workers are not necessarily
faster on Lustre. Four is a starting point, not a promised optimum.

## Copy and paste on each system

Let active builds finish and exit the old CSE shells, including their tmux
shells, before applying the update. Detaching tmux does not exit its shell.
From a fresh login prompt, enter Bash:

```bash
bash
```

Paste this complete block. It selects an existing saved session (asks which
one when several exist), checks out and fast-forwards `codex/cse-fast-login`,
previews the startup refresh, applies it only if the preview succeeds, repairs
owned output, checks the handoff and opens the updated session. All commands
run in a subshell so an error stops the update without closing your login shell.
Use it once per workspace/system with writers stopped. The preparation tools
and original values must already be present from this trial's setup.

If a previous attempt stopped with `missing-value at values.package_repo.commit`,
rerun this complete block. It fetches the fix before retrying. Startup refresh
now renders only the five startup controls and does not require a package-repo
commit. Keep your recorded values and repository pin as they are; do not insert
the example commit or change your install tree. That failed validation occurred
in temporary staging, before any workspace controls were replaced.

```bash
(
  set -e
  set -o pipefail

  if [ -n "${SPACK_ENV:-}" ]; then
    printf 'Start from a fresh login shell with no active Spack environment.\n' >&2
    exit 1
  fi

  shopt -s nullglob
  cse_session_root="${WORK_ROOT:-$HOME/STACK_TESTING}/operator-sessions"
  cse_sessions=("$cse_session_root"/*/*/activate.sh)
  case ${#cse_sessions[@]} in
    0)
      read -r -p 'Full path to your existing activate.sh: ' cse_session
      ;;
    1)
      cse_session="${cse_sessions[0]}"
      ;;
    *)
      PS3='Select the system/trial to update: '
      select cse_session in "${cse_sessions[@]}"; do
        [ -n "$cse_session" ] && break
      done
      ;;
  esac
  test -r "$cse_session"
  source "$cse_session"

  printf '\nUpdating workspace: %s\nUsing values: %s\n' "$BUILD_WORKSPACE" "$BUILD_VALUES"
  test -r "$BUILD_WORKSPACE/workspace-manifest.yaml"
  test -r "$BUILD_VALUES"
  test -x "$CSE_PYTHON"
  test -r "$STACK_COMPOSER"
  "$CSE_PYTHON" -c 'import yaml'

  if ! git -C "$CONTENT" diff --quiet || ! git -C "$CONTENT" diff --cached --quiet; then
    git -C "$CONTENT" status --short
    printf 'Stopped: stack-content has tracked local edits; no refresh was applied.\n' >&2
    exit 1
  fi

  git -C "$CONTENT" fetch origin \
    refs/heads/codex/cse-fast-login:refs/remotes/origin/codex/cse-fast-login
  if git -C "$CONTENT" show-ref --verify --quiet refs/heads/codex/cse-fast-login; then
    git -C "$CONTENT" checkout codex/cse-fast-login
  else
    git -C "$CONTENT" checkout -b codex/cse-fast-login --track origin/codex/cse-fast-login
  fi
  git -C "$CONTENT" merge --ff-only origin/codex/cse-fast-login

  cse_refresh=(
    "$CSE_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py"
    --composer "$STACK_COMPOSER"
    --blueprint "$CONTENT/pilots/cse-pilot"
    --values "$BUILD_VALUES"
    --workspace "$BUILD_WORKSPACE"
    --scope startup
  )
  "${cse_refresh[@]}" --dry-run
  "${cse_refresh[@]}"

  cd "$BUILD_WORKSPACE"
  export CSE_PERMISSION_JOBS=4
  ./cse-build login permissions
  ./cse-build login status
  printf '\nStartup update complete. Opening the updated CSE session.\n'
  exec ./cse-build login
)
```

A failed preview stops before replacing controls, including when an older
workspace lacks required recovery/overlay helpers. A successful refresh
preserves configuration, padding, environment YAML, locks and installed
packages. Existing Composer and Inspector binaries need no update for this fix.

If both builders own private-mode output, each owner must run `permissions`
after writers stop; it reports any remaining foreign-owned paths instead of
changing another owner's files. The receiving builder then runs `status`.

## Update an existing workspace

The same update applies before concretization, with partial locks/installations,
or after all packages are installed. Perform it **between commands**: stop
writers and exit old prepared shells/tmux build shells first. Detaching tmux is
not enough. Old shells retain their original exit hook until they exit. Stop
writers in other workspaces that share these caches during permission handoff.
The finite-operation lock blocks concurrent guarded builds and refreshes; it
cannot detect direct Spack commands inside a shell or older unguarded launchers.

Use the saved operator session to restore `CONTENT`, `STACK_COMPOSER`,
`CSE_PYTHON`, `BUILD_VALUES`, and `BUILD_WORKSPACE`, following
[Control refresh](CONTROL-REFRESH.md#1-restore-this-systems-operator-session).
Select a clean `stack-content` checkout at `codex/cse-fast-login` (built on the
committed recovery controls). Existing Composer/Inspector binaries need no
change for this fix. Use the original values for this exact workspace, including
its existing paths, runtime and group; do not create a new trial or re-render
over the workspace.

In Bash, preview first:

```bash
"$CSE_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --composer "$STACK_COMPOSER" \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --values "$BUILD_VALUES" --workspace "$BUILD_WORKSPACE" \
  --scope startup --dry-run
```

This selects exactly `cse-build`, `env/share-generated-permissions.sh`,
`env/workspace-shell.rc`, `scripts/workspace-permissions.py`, and
`BUILDER-HANDOFF.md`. Only those templates and their startup input requirements
are passed to Composer in temporary staging. The full workspace blueprint still
requires `package_repo.commit` when rendering repository configuration; startup
refresh neither renders that configuration nor resolves an existing tag. It
checks the existing helper dependencies and refuses a
change to recorded launcher roots or runtime identity. It leaves **all config
files, install-tree padding, environment YAML, locks, catalog, package overlays,
views, modules, caches and installed packages unchanged**. It retains a rollback
record in `.cse-control-refresh/` when applied.

An older workspace may lack the recovery/overlay controls required by the new
launcher. The preview identifies missing dependencies and stops before promotion.
Use the existing [control and overlay admission procedure](CONTROL-REFRESH.md)
first, retaining that workspace's values/locks; do not copy only the new launcher
or use a broad refresh just to bypass a prerequisite failure.

After a successful preview, apply the same command without `--dry-run`:

```bash
"$CSE_PYTHON" "$CONTENT/pilots/cse-pilot/scripts/refresh-workspace-controls.py" \
  --composer "$STACK_COMPOSER" \
  --blueprint "$CONTENT/pilots/cse-pilot" \
  --values "$BUILD_VALUES" --workspace "$BUILD_WORKSPACE" \
  --scope startup
cd "$BUILD_WORKSPACE"
./cse-build login permissions
./cse-build login status
./cse-build login
```

Run the one-time repair as each builder who owns outstanding private-mode output,
then have the receiving builder run `status`. No solve or package rebuild is
required. Repeat per system with that system's saved session and workspace.
A source checkout update alone does not update already-rendered workspaces.

## Validation

The regression tests exercise real prepared-shell entry/exit, single-pass repair
with 1/4/16/32 workers, executable preservation, symlink isolation, nested-root
handling, protected install prefixes, and unchanged-entry repeats. Refresh tests
cover empty, partially built and completed workspaces, preserving the bytes,
modes and timestamps of config, environment YAML, locks and installed files.
They also check mutual exclusion between refresh and guarded finite operations.
Runtime helper syntax remains Python 3.6-compatible and uses only the standard
library. Local macOS results do not predict Lustre latency; measure on an
isolated scratch fixture before selecting 16 or 32 workers for site maintenance.

The production helper's local 500-package run used 50,000 files and 2,501
directories, plus an outside-target symlink. Times include process startup;
fixture creation, reset and independent verification are outside the timer.
Each row is one run on local macOS storage; other local tests ran concurrently.

| Workers | Repair required | Already correct |
|---:|---:|---:|
| 1 | 4.141 s | 1.101 s |
| 4 | 2.842 s | 0.603 s |
| 16 | 1.784 s | 0.646 s |
| 32 | 1.979 s | 0.746 s |

Every already-correct run made zero permission updates. Root-only checks
visited one directory in 0.197–0.307 seconds including Python startup. This is
a helper measurement, not an end-to-end login timing. See the
[raw results](benchmarks/permissions-500-local.json).

To repeat safely on Lustre (creates and removes its own temporary fixture):

```bash
python3 "$CONTENT/pilots/cse-pilot/scripts/benchmark-workspace-permissions.py" \
  --temporary-parent "$WORKDIR" --packages 500 --files-per-package 100 \
  --jobs 1 4 16 32 > "$BUILD_EVIDENCE/permission-benchmark.json"
```

The benchmark accepts a helper path via `--helper`, never an existing tree to
repair. Runtime validation here covered macOS Python 3.9 and 3.14, plus Python
3.6 syntax checks. Linux/Lustre timing and the site's ACL behavior remain site
acceptance checks.
