# Validate a comma-separated email allow-list without printing it.
# Source from backend/infrastructure (deploy-backend.yml).
# check_email_allowlist <value> returns 0 when every entry is an email
# address. On failure it writes a message that names the position only.

check_email_allowlist() {
  local raw="${1-}"
  local email_re='^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
  local entry trimmed
  local index=0
  local -a entries=()
  if [[ -z "${raw//[[:space:]]/}" ]]; then
    echo "ADMIN_FEDERATED_EMAIL_ALLOWLIST is empty." >&2
    return 1
  fi
  # read -a drops a trailing empty field, so a final comma would otherwise pass.
  local trimmed_raw="${raw#"${raw%%[![:space:]]*}"}"
  trimmed_raw="${trimmed_raw%"${trimmed_raw##*[![:space:]]}"}"
  if [[ "$trimmed_raw" == *, ]]; then
    local commas="${trimmed_raw//[^,]/}"
    echo "ADMIN_FEDERATED_EMAIL_ALLOWLIST entry $((${#commas} + 1)) is not an email address." >&2
    return 1
  fi
  IFS=',' read -r -a entries <<< "$trimmed_raw"
  for entry in "${entries[@]}"; do
    index=$((index + 1))
    trimmed="${entry#"${entry%%[![:space:]]*}"}"
    trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
    if [[ ! "$trimmed" =~ $email_re ]]; then
      echo "ADMIN_FEDERATED_EMAIL_ALLOWLIST entry ${index} is not an email address." >&2
      return 1
    fi
  done
  return 0
}
