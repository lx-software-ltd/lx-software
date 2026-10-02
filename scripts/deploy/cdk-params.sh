# Split a CDK parameter JSON file into --parameters argv arrays.
# Source from backend/infrastructure (deploy-backend.yml and cdk-diff.yml).
# cdk_load_param_args <resolved-param-file> sets:
#   PUBLIC_PARAM_ARGS, ADMIN_LX_PARAM_ARGS, ADMIN_WEB_PARAM_ARGS

cdk_load_param_args() {
  local resolved="$1"
  local public_file admin_lx_file admin_web_file unknown
  public_file="$(mktemp)"
  admin_lx_file="$(mktemp)"
  admin_web_file="$(mktemp)"
  _cdk_params_cleanup() { rm -f "$public_file" "$admin_lx_file" "$admin_web_file"; }
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
