#!/usr/bin/env bash
# Restore derived paths and helpers for one saved CSE trial operator session.
# This file is sourced by the generated activate.sh; it is not a standalone CLI.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "operator-session.sh must be sourced through a generated activate.sh" >&2
  exit 2
fi

_cse_session_error() {
  printf 'CSE operator session: %s\n' "$*" >&2
}

_cse_session_require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    _cse_session_error "required saved value $name is empty"
    return 2
  fi
}

for _cse_name in \
  WORK_ROOT SYSTEM_NAME STACK_BRANCH CATALOG_RELEASE TRIAL_RELEASE CSE_GROUP \
  CSE_TRIAL_ROOT SPACK_RUNTIME_MODE CSE_TOOLS_ROOT SPACK_SOURCE \
  SPACK_VERSION SPACK_TAG SPACK_COMMIT CSE_BOOTSTRAP_PYTHON \
  CSE_OPERATOR_SESSION_FILE; do
  _cse_session_require "$_cse_name" || return 2
done
unset _cse_name

case "$SPACK_RUNTIME_MODE" in
  shared|local) ;;
  *)
    _cse_session_error "SPACK_RUNTIME_MODE must be shared or local"
    return 2
    ;;
esac

for _cse_path_name in WORK_ROOT CSE_TRIAL_ROOT CSE_TOOLS_ROOT \
  CSE_BOOTSTRAP_PYTHON CSE_OPERATOR_SESSION_FILE; do
  _cse_path_value="${!_cse_path_name}"
  case "$_cse_path_value" in
    /*) ;;
    *)
      _cse_session_error "$_cse_path_name must be absolute: $_cse_path_value"
      return 2
      ;;
  esac
done
unset _cse_path_name _cse_path_value

case "$CSE_TRIAL_ROOT" in
  */initial-conversion-trials) ;;
  *)
    _cse_session_error \
      "CSE_TRIAL_ROOT must end in /initial-conversion-trials: $CSE_TRIAL_ROOT"
    return 2
    ;;
esac

if [[ -n "${SPACK_ENV:-}" ]]; then
  _cse_session_error "start from a shell with no active Spack environment: $SPACK_ENV"
  return 2
fi

if [[ -z "${WORKDIR:-}" ]]; then
  _cse_session_error "WORKDIR must be set by the site environment"
  return 2
fi
if [[ -z "${USER:-}" ]]; then
  _cse_session_error "USER must be set"
  return 2
fi
case "$WORKDIR" in
  /*) ;;
  *)
    _cse_session_error "WORKDIR must be absolute: $WORKDIR"
    return 2
    ;;
esac

# Keep every later file created in the restricted CSE workspace writable by
# both its owner and the explicit collaboration group.  Private per-builder
# directories below use an explicit 0700 mode and are not widened by this.
umask 0007

export INSPECTOR="$WORK_ROOT/cluster-inspector"
export COMPOSER="$WORK_ROOT/stack-composer"
export CONTENT="$WORK_ROOT/stack-content"
export PLANNING="$WORK_ROOT/stack-planning"
case "$SPACK_RUNTIME_MODE" in
  shared) export SPACK_ROOT="$CSE_TOOLS_ROOT/spack/$SPACK_VERSION" ;;
  local) export SPACK_ROOT="$WORK_ROOT/spack/$SPACK_VERSION" ;;
esac
export SPACK_DISABLE_LOCAL_CONFIG=true
export PYTHONDONTWRITEBYTECODE=1
export SYSTEM_DIR="$CONTENT/systems/$SYSTEM_NAME"
export PROBE_DIR="$WORK_ROOT/probe-work/$SYSTEM_NAME/$CATALOG_RELEASE"
export STACK_COMPOSER="$COMPOSER/dist/stack-composer.pyz"
export CSE_PYTHON="$COMPOSER/.venv/bin/python"

export CSE_RESTRICTED_ROOT="$CSE_TRIAL_ROOT/restricted"
export CSE_PUBLISHED_ROOT="$CSE_TRIAL_ROOT/published"
export STATIC_ROOT="$CSE_RESTRICTED_ROOT/catalogs"
export CATALOG="$STATIC_ROOT/$SYSTEM_NAME/static/$CATALOG_RELEASE"
export BUILD_WORKSPACE="$CSE_RESTRICTED_ROOT/workspaces/$SYSTEM_NAME/initial-conversion-trials/$TRIAL_RELEASE"
export PUBLISH_WORKSPACE="$CSE_PUBLISHED_ROOT/workspaces/$SYSTEM_NAME/initial-conversion-trials/$TRIAL_RELEASE"
export BUILD_RELEASE_ROOT="$CSE_RESTRICTED_ROOT/releases/$SYSTEM_NAME/$TRIAL_RELEASE"
export PUBLISH_RELEASE_ROOT="$CSE_PUBLISHED_ROOT/releases/$SYSTEM_NAME/$TRIAL_RELEASE"
export BUILDCACHE_ROOT="$CSE_RESTRICTED_ROOT/buildcache/$SYSTEM_NAME/$TRIAL_RELEASE"
export BUILDCACHE_URL="file://$BUILDCACHE_ROOT"
export BUILD_EVIDENCE="$CSE_RESTRICTED_ROOT/evidence/$SYSTEM_NAME/$TRIAL_RELEASE"
export PUBLISH_EVIDENCE="$PUBLISH_RELEASE_ROOT/evidence"
export BUILD_VALUES="$SYSTEM_DIR/cse-trials-build-values.yaml"
export PUBLISH_VALUES="$SYSTEM_DIR/cse-trials-publish-values.yaml"

export SPACK_USER_STATE_ROOT="$WORKDIR/$USER/cse-spack/$SYSTEM_NAME/$SPACK_VERSION"
export SPACK_USER_CACHE_PATH="$SPACK_USER_STATE_ROOT/cache"
export SPACK_GNUPGHOME="$SPACK_USER_STATE_ROOT/gpg"

for _cse_forbidden_root in \
  "$SPACK_ROOT" \
  "$BUILD_RELEASE_ROOT/spack/opt" \
  "$PUBLISH_RELEASE_ROOT/spack/opt"; do
  case "$SPACK_USER_STATE_ROOT" in
    "$_cse_forbidden_root"|"$_cse_forbidden_root"/*)
      _cse_session_error \
        "per-user Spack state is inside a forbidden root: $_cse_forbidden_root"
      return 2
      ;;
  esac
done
unset _cse_forbidden_root

CSE_OPERATOR_SESSION_ROOT="$(dirname "$CSE_OPERATOR_SESSION_FILE")" || return 2
export CSE_OPERATOR_SESSION_ROOT
export CSE_PROVIDER_SELECTIONS="$CSE_OPERATOR_SESSION_ROOT/provider-selections.sh"
export CSE_TOOL_STATE_ROOT="$CSE_OPERATOR_SESSION_ROOT/tool-state"
if [[ -f "$CSE_PROVIDER_SELECTIONS" ]]; then
  # Operator-owned reviewed selections for this exact catalog/trial pair.
  # shellcheck disable=SC1090
  source "$CSE_PROVIDER_SELECTIONS" || return 2
fi

verify_shared_spack_root_read_only() {
  local path setgid_path
  while IFS= read -r -d '' path; do
    if [[ -w "$path" ]]; then
      _cse_session_error "shared Spack tool root is writable: $path"
      return 1
    fi
  done < <(find "$SPACK_ROOT" -xdev -print0)
  setgid_path="$(find "$SPACK_ROOT" -xdev -type d \
    -perm -2000 -print -quit)"
  if [[ -n "$setgid_path" ]]; then
    _cse_session_error \
      "shared Spack tool root contains an unexpected setgid directory: $setgid_path"
    return 1
  fi
}

verify_spack_tool_root() {
  [[ -d "$SPACK_ROOT/.git" ]] || return 1
  [[ "$(git -C "$SPACK_ROOT" remote get-url origin)" == \
    "$SPACK_SOURCE" ]] || return 1
  [[ "$(git -C "$SPACK_ROOT" rev-parse HEAD)" == "$SPACK_COMMIT" ]] || return 1
  [[ "$(git -C "$SPACK_ROOT" rev-parse "${SPACK_TAG}^{commit}")" == \
    "$SPACK_COMMIT" ]] || return 1
  [[ -z "$(GIT_OPTIONAL_LOCKS=0 git -C "$SPACK_ROOT" \
    status --porcelain --untracked-files=all)" ]] || return 1
  [[ -z "$(git -C "$SPACK_ROOT" \
    ls-files --others --ignored --exclude-standard)" ]] || return 1
  if [[ "$SPACK_RUNTIME_MODE" == shared ]]; then
    verify_shared_spack_root_read_only
  fi
}

verify_workspace_scopes() {
  local workspace="$1"
  local evidence_root="$2"
  local environment_dir label evidence scope_output scope_path
  local generated_scope_count environment_count=0

  mkdir -p "$evidence_root"
  scope_output="$(COLUMNS=512 spack config scopes -vp)" || return 1
  printf '%s\n' "$scope_output" | tee "$evidence_root/global.txt"
  if grep -Eq \
    '^(user|system)[[:space:]]+[^[:space:]]+[[:space:]]+active([[:space:]]|$)' \
    "$evidence_root/global.txt"; then
    _cse_session_error "unexpected active user/system Spack configuration scope"
    return 1
  fi

  for environment_dir in "$workspace"/environments/*/*; do
    [[ -f "$environment_dir/spack.yaml" ]] || continue
    environment_count=$((environment_count + 1))
    label="${environment_dir#"$workspace/environments/"}"
    label="${label//\//-}"
    evidence="$evidence_root/$label.txt"

    scope_output="$(COLUMNS=512 spack -e "$environment_dir" \
      config scopes -vp)" || return 1
    printf '%s\n' "$scope_output" | tee "$evidence"

    if grep -Eq \
      '^(user|system|site)[[:space:]]+[^[:space:]]+[[:space:]]+active([[:space:]]|$)' \
      "$evidence"; then
      _cse_session_error "unexpected active ambient scope in $environment_dir"
      return 1
    fi

    generated_scope_count="$(awk -v root="$workspace/" \
      '$2 ~ /include/ && $3 == "active" && index($4, root) == 1 {count++} \
       END {print count + 0}' "$evidence")"
    if [[ "$generated_scope_count" -le 0 ]]; then
      _cse_session_error "no active workspace include scope in $environment_dir"
      return 1
    fi

    while IFS= read -r scope_path; do
      case "$scope_path" in
        "$workspace"/*|"$SPACK_ROOT"/etc/spack/defaults/*) ;;
        *)
          _cse_session_error \
            "unexpected active include path in $environment_dir: $scope_path"
          return 1
          ;;
      esac
    done < <(awk '$2 ~ /include/ && $3 == "active" {print $4}' "$evidence")
  done

  if [[ "$environment_count" -le 0 ]]; then
    _cse_session_error "no Spack environments found under $workspace"
    return 1
  fi
}

cse_session_use_spack() {
  verify_spack_tool_root || {
    _cse_session_error "Spack tool root failed identity/read-only verification: $SPACK_ROOT"
    return 1
  }
  # The pinned root is selected at session creation and verified immediately.
  # shellcheck disable=SC1091
  source "$SPACK_ROOT/share/spack/setup-env.sh" || return 1
  local version_output
  version_output="$(spack --version)" || return 1
  [[ "${version_output%% *}" == "$SPACK_VERSION" ]] || {
    _cse_session_error \
      "expected Spack $SPACK_VERSION but activated $version_output"
    return 1
  }
  verify_spack_tool_root
}

_cse_tool_head() {
  local repo="$1" label="$2" head dirty
  if [[ ! -d "$repo/.git" ]]; then
    _cse_session_error "$label checkout is missing: $repo"
    return 1
  fi
  head="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || {
    _cse_session_error "could not read $label checkout commit: $repo"
    return 1
  }
  dirty="$(git -C "$repo" status --porcelain \
    --untracked-files=normal 2>/dev/null)" || {
    _cse_session_error "could not inspect $label checkout: $repo"
    return 1
  }
  if [[ -n "$dirty" ]]; then
    _cse_session_error "$label checkout contains unreviewed changes"
    return 1
  fi
  printf '%s\n' "$head"
}

_cse_record_tool_commit() {
  local stamp="$1" commit="$2" temporary
  temporary="${stamp}.pending.$$"
  if ! printf '%s\n' "$commit" > "$temporary"; then
    rm -f -- "$temporary"
    return 1
  fi
  if ! mv -f -- "$temporary" "$stamp"; then
    rm -f -- "$temporary"
    return 1
  fi
}

cse_rebuild_cluster_inspector() {
  local head
  head="$(_cse_tool_head "$INSPECTOR" "Cluster Inspector")" || return 1
  if ! command -v go >/dev/null 2>&1; then
    _cse_session_error \
      "Go 1.22 or newer is required to rebuild Cluster Inspector; commit state was not changed"
    return 1
  fi
  if ! (
    cd "$INSPECTOR" &&
      make build &&
      ./cluster-inspector --help >/dev/null
  ); then
    _cse_session_error \
      "Cluster Inspector build or smoke test failed; commit state was not changed"
    return 1
  fi
  _cse_record_tool_commit \
    "$CSE_TOOL_STATE_ROOT/cluster-inspector.commit" "$head" || {
    _cse_session_error "could not record the Cluster Inspector build commit"
    return 1
  }
  printf 'CSE operator session: Cluster Inspector rebuilt at %s\n' \
    "${head:0:12}"
}

# Keep the recorded .pyz/Python paths intact. A native candidate is a separate,
# explicit operator selection; it must be executed directly, never by Python.
cse_stack_composer() {
  if [[ -n "${CSE_STACK_COMPOSER_NATIVE:-}" ]]; then
    if [[ ! -x "$CSE_STACK_COMPOSER_NATIVE" ]]; then
      _cse_session_error "native Composer candidate is not executable: $CSE_STACK_COMPOSER_NATIVE"
      return 2
    fi
    "$CSE_STACK_COMPOSER_NATIVE" "$@"
  else
    "$CSE_PYTHON" "$STACK_COMPOSER" "$@"
  fi
}

cse_rebuild_stack_composer() {
  local head
  head="$(_cse_tool_head "$COMPOSER" "Stack Composer")" || return 1
  if [[ ! -x "$CSE_BOOTSTRAP_PYTHON" ]]; then
    _cse_session_error \
      "the reviewed bootstrap Python is unavailable: $CSE_BOOTSTRAP_PYTHON"
    return 1
  fi
  if ! (
    cd "$COMPOSER" &&
      "$CSE_BOOTSTRAP_PYTHON" -c \
        'import sys; assert sys.version_info >= (3, 9), sys.version' &&
      "$CSE_BOOTSTRAP_PYTHON" -m venv .venv &&
      "$CSE_PYTHON" -m pip install --upgrade \
        pip "setuptools>=77" "wheel>=0.44,<1" "build>=1.2,<2" &&
      "$CSE_PYTHON" -m pip install -e '.[dev]' &&
      PYTHON="$CSE_PYTHON" bash scripts/build-pyz.sh &&
      "$CSE_PYTHON" "$STACK_COMPOSER" --help >/dev/null
  ); then
    _cse_session_error \
      "Stack Composer build or smoke test failed; commit state was not changed"
    return 1
  fi
  _cse_record_tool_commit \
    "$CSE_TOOL_STATE_ROOT/stack-composer.commit" "$head" || {
    _cse_session_error "could not record the Stack Composer build commit"
    return 1
  }
  printf 'CSE operator session: Stack Composer rebuilt at %s\n' \
    "${head:0:12}"
}

cse_rebuild_tools() {
  local selection="${1:-all}" status=0
  case "$selection" in
    inspector)
      cse_rebuild_cluster_inspector || status=1
      ;;
    composer)
      cse_rebuild_stack_composer || status=1
      ;;
    all)
      cse_rebuild_cluster_inspector || status=1
      cse_rebuild_stack_composer || status=1
      ;;
    *)
      _cse_session_error \
        "cse_rebuild_tools accepts inspector, composer, or all"
      return 2
      ;;
  esac
  cse_session_status
  return "$status"
}

cse_session_status() {
  local head recorded dirty
  printf 'CSE operator session\n'
  printf '  session:   %s\n' "$CSE_OPERATOR_SESSION_FILE"
  printf '  system:    %s\n' "$SYSTEM_NAME"
  printf '  catalog:   %s\n' "$CATALOG"
  printf '  workspace: %s\n' "$BUILD_WORKSPACE"
  printf '  Spack:     %s (%s)\n' "$SPACK_ROOT" "$SPACK_RUNTIME_MODE"
  head=""
  recorded=""
  dirty=""
  if [[ -d "$INSPECTOR/.git" ]]; then
    head="$(git -C "$INSPECTOR" rev-parse HEAD 2>/dev/null || true)"
    dirty="$(git -C "$INSPECTOR" status --porcelain \
      --untracked-files=normal 2>/dev/null || true)"
  fi
  if [[ -r "$CSE_TOOL_STATE_ROOT/cluster-inspector.commit" ]]; then
    recorded="$(<"$CSE_TOOL_STATE_ROOT/cluster-inspector.commit")"
  fi
  if [[ -n "$dirty" ]]; then
    printf '  inspector: review checkout changes before use\n'
  elif [[ -x "$INSPECTOR/cluster-inspector" && -n "$head" && \
    "$head" == "$recorded" ]]; then
    printf '  inspector: ready at %s\n' "${head:0:12}"
  else
    printf '  inspector: build/rebuild required\n'
  fi

  head=""
  recorded=""
  dirty=""
  if [[ -d "$COMPOSER/.git" ]]; then
    head="$(git -C "$COMPOSER" rev-parse HEAD 2>/dev/null || true)"
    dirty="$(git -C "$COMPOSER" status --porcelain \
      --untracked-files=normal 2>/dev/null || true)"
  fi
  if [[ -r "$CSE_TOOL_STATE_ROOT/stack-composer.commit" ]]; then
    recorded="$(<"$CSE_TOOL_STATE_ROOT/stack-composer.commit")"
  fi
  if [[ -n "$dirty" ]]; then
    printf '  composer:  review checkout changes before use\n'
  elif [[ -x "$CSE_PYTHON" && -f "$STACK_COMPOSER" && -n "$head" && \
    "$head" == "$recorded" ]]; then
    printf '  composer:  ready at %s\n' "${head:0:12}"
  else
    printf '  composer:  build/rebuild required\n'
  fi
  if [[ -f "$BUILD_WORKSPACE/workspace-manifest.yaml" ]]; then
    printf '  handoff:   use %s/cse-build\n' "$BUILD_WORKSPACE"
  else
    printf '  handoff:   workspace not initialized\n'
  fi
}

install -d -m 0700 \
  "$SPACK_USER_CACHE_PATH" \
  "$SPACK_GNUPGHOME" \
  "$CSE_TOOL_STATE_ROOT" || return 2
mkdir -p "$WORK_ROOT" "$PROBE_DIR" || return 2

cse_session_status
