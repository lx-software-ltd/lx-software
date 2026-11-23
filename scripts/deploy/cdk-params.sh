# Split a CDK parameter JSON file into --parameters argv arrays.
# Source from backend/infrastructure (deploy-backend.yml and cdk-diff.yml).
# cdk_load_param_args <resolved-param-file> sets:
#   PUBLIC_PARAM_ARGS, ADMIN_LX_PARAM_ARGS, ADMIN_WEB_PARAM_ARGS
# cdk_append_nonempty_param KEY VALUE appends --parameters KEY=VALUE to
# ADMIN_LX_PARAM_ARGS when VALUE is non-empty after trim. It does not print VALUE.

cdk_append_nonempty_param() {
  local key="${1-}"
  local value="${2-}"
  local trimmed="${value#"${value%%[![:space:]]*}"}"
  trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
  if [[ -z "$key" || -z "$trimmed" ]]; then
    return 0
  fi
  ADMIN_LX_PARAM_ARGS+=( --parameters "${key}=${trimmed}" )
}

cdk_resolve_placeholders() {
  local src="$1"
  local dest="$2"
  python3 - "$src" "$dest" << 'PY'
import json
import os
import re
import sys

secret = re.compile(r"^<FROM_GITHUB_SECRET:\s*([^>]+?)\s*>$")
variable = re.compile(r"^<FROM_GITHUB_VAR:\s*([^>]+?)\s*>$")
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
resolved = {}
for key, value in data.items():
    if isinstance(value, str):
        match = secret.fullmatch(value.strip()) or variable.fullmatch(value.strip())
        if match:
            value = os.environ.get(match.group(1), "")
    resolved[key] = value
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump(resolved, handle)
PY
}

cdk_load_param_args() {
  local resolved="$1"
  local public_file admin_lx_file admin_web_file unknown resolved_json
  resolved_json="$(mktemp)"
  if ! cdk_resolve_placeholders "$resolved" "$resolved_json"; then
    rm -f "$resolved_json"
    return 1
  fi
  resolved="$resolved_json"
  public_file="$(mktemp)"
  admin_lx_file="$(mktemp)"
  admin_web_file="$(mktemp)"
  _cdk_params_cleanup() { rm -f "$public_file" "$admin_lx_file" "$admin_web_file" "$resolved_json"; }
  unknown="$(jq -r 'to_entries[] | select(.value != null) | .value = (if .value | type == "string" then .value else (.value | tostring) end) | select(.value != "") | .key | select(test(":")) | select(test("^(lxsoftware:|lxsoftware-public-www:|lxsoftware-admin-web:)") | not)' "$resolved")"
  if [[ -n "$unknown" ]]; then
    echo "unknown parameter key prefix:" >&2
    echo "$unknown" >&2
    _cdk_params_cleanup
    return 1
  fi
  if ! jq -r 'to_entries[] | select(.value != null) | .value = (if .value | type == "string" then .value else .value | tostring end) | .value = (.value | gsub("\r\n"; "\n") | gsub("\r"; "\n") | gsub("\n"; "\\n") | ltrimstr(" ") | rtrimstr(" ")) | select(.value != "") | select((.key | contains(":") | not) or (.key | startswith("lxsoftware-public-www:"))) | .key = (if (.key | test(":")) then .key else "lxsoftware-public-www:\(.key)" end) | "--parameters", "\(.key)=\(.value)"' "$resolved" > "$public_file"; then
    _cdk_params_cleanup
    return 1
  fi
  if ! jq -r 'to_entries[] | select(.value != null) | .value = (if .value | type == "string" then .value else .value | tostring end) | .value = (.value | gsub("\r\n"; "\n") | gsub("\r"; "\n") | gsub("\n"; "\\n") | ltrimstr(" ") | rtrimstr(" ")) | select(.value != "") | select(.key | test("^lxsoftware:")) | "--parameters", "\(.key)=\(.value)"' "$resolved" > "$admin_lx_file"; then
    _cdk_params_cleanup
    return 1
  fi
  if ! jq -r 'to_entries[] | select(.value != null) | .value = (if .value | type == "string" then .value else .value | tostring end) | .value = (.value | gsub("\r\n"; "\n") | gsub("\r"; "\n") | gsub("\n"; "\\n") | ltrimstr(" ") | rtrimstr(" ")) | select(.value != "") | select(.key | test("^lxsoftware-admin-web:")) | "--parameters", "\(.key)=\(.value)"' "$resolved" > "$admin_web_file"; then
    _cdk_params_cleanup
    return 1
  fi
  PUBLIC_PARAM_ARGS=()
  ADMIN_LX_PARAM_ARGS=()
  ADMIN_WEB_PARAM_ARGS=()
  readarray -t PUBLIC_PARAM_ARGS < "$public_file"
  readarray -t ADMIN_LX_PARAM_ARGS < "$admin_lx_file"
  readarray -t ADMIN_WEB_PARAM_ARGS < "$admin_web_file"
  _cdk_params_cleanup
}
