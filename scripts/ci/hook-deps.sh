#!/usr/bin/env bash
# Install the dependencies the pre-commit hooks in this repository need.
set -euo pipefail
python -m pip install 'ruff==0.17.6'
npm ci --prefix apps/public_www
npm ci --prefix apps/admin_web
