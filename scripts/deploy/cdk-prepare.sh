#!/usr/bin/env bash
# Prepare a CDK diff or deploy. lx-software keeps its parameter loader.
set -euo pipefail
mode="${1:-}"
case "$mode" in
  region)
    echo "region=${INPUT_AWS_REGION:-}" >> "${GITHUB_OUTPUT:?}"
    exit 0
    ;;
  diff|deploy) ;;
  *) echo "::error::cdk-prepare.sh requires diff or deploy" >&2; exit 1 ;;
esac

if [ -n "${P_GOOGLE_CLIENT_SECRET:-}" ]; then echo "::add-mask::${P_GOOGLE_CLIENT_SECRET}"; fi
if [ -n "${P_EMAIL_ALLOWLIST:-}" ]; then echo "::add-mask::${P_EMAIL_ALLOWLIST}"; fi

if [ ! -f backend/infrastructure/package.json ]; then
  echo "::warning::Missing backend/infrastructure/package.json"
  echo "run=false" >> "${GITHUB_OUTPUT:?}"
  exit 0
fi

cd backend/infrastructure
npm run build --if-present

if [ "$mode" = "deploy" ]; then
  {
    echo "run=true"
    echo "stacks=${CDK_STACKS:-}"
  } >> "${GITHUB_OUTPUT:?}"
  exit 0
fi

PUBLIC_PARAM_ARGS=()
ADMIN_LX_PARAM_ARGS=()
ADMIN_WEB_PARAM_ARGS=()
resolve_param_file() {
  local path="$1"
  if [ -z "$path" ]; then
    return 1
  fi
  if [ -f "$path" ]; then
    echo "$path"
    return 0
  fi
  if [ -n "${GITHUB_WORKSPACE:-}" ] && [ -f "$GITHUB_WORKSPACE/$path" ]; then
    echo "$GITHUB_WORKSPACE/$path"
    return 0
  fi
  return 1
}
if [ -n "${CDK_PARAM_FILE:-}" ]; then
  RESOLVED_PARAM_FILE=$(resolve_param_file "$CDK_PARAM_FILE" || true)
  if [ -n "$RESOLVED_PARAM_FILE" ]; then
    # shellcheck source=../../scripts/deploy/cdk-params.sh
    source ../../scripts/deploy/cdk-params.sh
    cdk_load_param_args "$RESOLVED_PARAM_FILE"
  else
    echo "::error::CDK_PARAM_FILE was not found"
    exit 1
  fi
fi
PARAM_ARGS=( "${PUBLIC_PARAM_ARGS[@]}" "${ADMIN_LX_PARAM_ARGS[@]}" "${ADMIN_WEB_PARAM_ARGS[@]}" )
if [ ${#PARAM_ARGS[@]} -gt 0 ]; then
  printf '%s\0' "${PARAM_ARGS[@]}" > "${RUNNER_TEMP:?}/cdk-args"
else
  : > "${RUNNER_TEMP:?}/cdk-args"
fi
STACK_ARGS=()
if [ -n "${CDK_STACKS:-}" ]; then
  IFS=$', \n\t' read -r -a STACK_LIST <<< "$CDK_STACKS"
  for stack in "${STACK_LIST[@]}"; do
    trimmed="${stack#"${stack%%[![:space:]]*}"}"
    trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
    if [ -n "$trimmed" ]; then
      STACK_ARGS+=("$trimmed")
    fi
  done
fi
{
  echo "run=true"
  echo "stacks=${STACK_ARGS[*]}"
} >> "${GITHUB_OUTPUT:?}"
