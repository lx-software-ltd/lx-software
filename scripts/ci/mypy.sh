#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install -q 'mypy==1.8.0'
dirs=()
for dir in backend/lambda/*; do
  if [ -d "$dir" ] && find "$dir" -name '*.py' -print -quit | grep -q .; then
    dirs+=("$dir")
  fi
done
dirs+=(scripts .cursor/hooks)
if [ "${#dirs[@]}" -eq 0 ]; then
  echo "no Python directories to check"
  exit 1
fi
for dir in "${dirs[@]}"; do
  echo "mypy $dir"
  (
    cd "$dir"
    python3 -m mypy --ignore-missing-imports .
  )
done
