#!/bin/sh
# Shell wrapper so a missing python3 does not fail the hook closed.
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' '{"permission":"allow","agent_message":"python3 is missing; shell guard skipped."}'
  exit 0
fi
exec python3 "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/guard_shell.py"
