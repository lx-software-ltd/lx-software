#!/usr/bin/env bash
# Check the admin SPA settings read from the backend stack.
set -euo pipefail
python3 - << 'PY'
import json
import os
import sys

data = json.loads(os.environ["JSON"])
stack = os.environ["STACK_NAME"]
domain = data["CognitoDomain"]
api_url = data["AdminApiBaseUrl"]
client_id = data["UserPoolClientId"]
if not domain.startswith("https://"):
    print(f"::error::CognitoDomain on {stack} must be an https origin", file=sys.stderr)
    sys.exit(1)
if not api_url.startswith("https://"):
    print(f"::error::AdminApiBaseUrl on {stack} must be an https origin", file=sys.stderr)
    sys.exit(1)
with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
    handle.write(f"client_id={client_id}\n")
    handle.write(f"domain={domain}\n")
    handle.write(f"api_url={api_url}\n")
PY
