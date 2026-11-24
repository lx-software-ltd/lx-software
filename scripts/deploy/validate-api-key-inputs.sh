#!/usr/bin/env bash
# Validate a manage-api-keys dispatch before it calls AWS.
set -euo pipefail
if [ "$ACTION" = "create" ]; then
  if [ -z "$LABEL" ]; then
    echo "::error::'label' is required for action=create"
    exit 1
  fi
  if [ "$HAS_PASSPHRASE" != "true" ]; then
    echo "::error::Secret PUBLIC_API_KEY_GPG_PASSPHRASE is not set. Add it under Settings > Environments > production > Secrets; it is needed to encrypt the minted key in this public repo's logs."
    exit 1
  fi
fi
if [ "$ACTION" = "revoke" ] && [ -z "$KEY_ID" ]; then
  echo "::error::'key_id' is required for action=revoke"
  exit 1
fi
if [ "$ACTION" = "set-write" ] && [ -z "$KEY_ID" ]; then
  echo "::error::'key_id' is required for action=set-write"
  exit 1
fi
if [ "$ACTION" = "set-scopes" ] && { [ -z "$KEY_ID" ] || [ -z "$SCOPES" ]; }; then
  echo "::error::'key_id' and 'scopes' are required for action=set-scopes"
  exit 1
fi
