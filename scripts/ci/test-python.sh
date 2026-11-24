#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install -q boto3 -r backend/lambda/admin/requirements.txt
for dir in backend/lambda/admin backend/lambda/public_api_authorizer backend/lambda/pre_token_generation backend/lambda/siutindei_schema; do
  if [ -d "$dir" ]; then
    python3 -m unittest discover -s "$dir" -p 'test_*.py' -v
  fi
done
python3 -m unittest discover -s scripts -p 'test_*.py' -v
