#!/usr/bin/env bash
set -euo pipefail
KEY_FILE="$(mktemp -u)"
python3 scripts/mint-openrouter-app-keys.py --plaintext-out "$KEY_FILE"

# Defense in depth: mask any key-shaped token in case a later step
# accidentally prints the file. GitHub already masks the management key.
grep -oE 'sk-[A-Za-z0-9_-]+' "$KEY_FILE" | while IFS= read -r token; do
  echo "::add-mask::$token"
done || true

gpg --batch --yes --symmetric --cipher-algo AES256 --armor \
  --passphrase "$GPG_PASSPHRASE" \
  --output keys.asc "$KEY_FILE"
rm -f "$KEY_FILE"

{
  echo "## Encrypted OpenRouter keys"
  echo ""
  echo "Copy the block below into \`keys.asc\`, then run"
  echo "\`gpg --decrypt keys.asc\` and enter the"
  echo "\`PUBLIC_API_KEY_GPG_PASSPHRASE\` value."
  echo ""
  echo "Merge the admin JSON into Secrets Manager secret"
  echo "\`lxsoftware-admin-openrouter-api-secret-Hzerh6\`"
  echo "(named keys \`statement-parser\` and \`executive-board\`)."
  echo "Sibling product keys stay as a plain string in that product's secret."
  echo ""
  echo '```'
  cat keys.asc
  echo '```'
} >> "$GITHUB_STEP_SUMMARY"
rm -f keys.asc
echo "Encrypted keys emitted to the job summary."
