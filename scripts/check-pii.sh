#!/usr/bin/env bash
# Fail when tracked source matches the hashed personal-data denylist.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${ROOT_DIR}/scripts/check_pii.py"
