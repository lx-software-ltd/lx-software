#!/usr/bin/env bash
# Mint a public API key and put only the encrypted block in the job summary.
set -euo pipefail
KEY_FILE="$(mktemp -u)"
ARGS=(create --label "$LABEL" --plaintext-out "$KEY_FILE" --region "$AWS_REGION")
if [ -n "${TIER:-}" ]; then
  ARGS+=(--tier "$TIER")
fi
if [ -n "${EXPIRES_AT:-}" ]; then
  ARGS+=(--expires-at "$EXPIRES_AT")
fi
if [ -n "${SCOPES:-}" ]; then
  ARGS+=(--scopes "$SCOPES")
fi
if [ -n "${ALLOWED_CIDRS:-}" ]; then
  ARGS+=(--allowed-cidrs "$ALLOWED_CIDRS")
fi
if [ "${ALLOW_WRITE:-}" = "true" ]; then
  ARGS+=(--allow-write)
fi
python3 scripts/manage-public-api-keys.py "${ARGS[@]}"
echo "::add-mask::$(tr -d '\n' < "$KEY_FILE")"
gpg --batch --yes --symmetric --cipher-algo AES256 --armor \
  --passphrase "$GPG_PASSPHRASE" \
  --output key.asc "$KEY_FILE"
rm -f "$KEY_FILE"
{
  echo "## Encrypted API key"
  echo ""
  echo "Copy the block below into \`key.asc\`, then run"
  echo "\`gpg --decrypt key.asc\` and enter the"
  echo "\`PUBLIC_API_KEY_GPG_PASSPHRASE\` value."
  echo ""
  echo '```'
  cat key.asc
  echo '```'
} >> "$GITHUB_STEP_SUMMARY"
rm -f key.asc
echo "Encrypted key emitted to the job summary."
