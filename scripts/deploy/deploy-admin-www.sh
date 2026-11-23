#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
APP_DIR="$ROOT_DIR/apps/admin_web"
BUILD_DIR="$APP_DIR/dist"
STACK_NAME="${ADMIN_WEB_STACK_NAME:-lxsoftware-admin-web}"

if [ ! -d "$BUILD_DIR" ]; then
  echo "Build output not found at $BUILD_DIR"
  echo "Run: (cd apps/admin_web && npm run build)"
  exit 1
fi

BUCKET_QUERY="Stacks[0].Outputs[?OutputKey=='AdminWebBucketName']."
BUCKET_QUERY+="OutputValue"
BUCKET_NAME="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "$BUCKET_QUERY" \
  --output text)"

if [ -z "$BUCKET_NAME" ] || [ "$BUCKET_NAME" = "None" ]; then
  echo "Admin web bucket output not found for $STACK_NAME"
  exit 1
fi

echo "Uploading hashed assets under dist/assets with long cache…"
if [ -d "$BUILD_DIR/assets" ]; then
  aws s3 sync "$BUILD_DIR/assets" "s3://$BUCKET_NAME/assets" \
    --delete \
    --cache-control "public,max-age=31536000,immutable"
fi

echo "Uploading other root build artifacts (except index.html)…"
shopt -s nullglob
for f in "$BUILD_DIR"/*; do
  base="$(basename "$f")"
  if [[ "$base" == "assets" || "$base" == "index.html" ]]; then
    continue
  fi
  if [[ -f "$f" ]]; then
    aws s3 cp "$f" "s3://$BUCKET_NAME/$base" \
      --cache-control "public,max-age=31536000,immutable"
  fi
done

echo "Uploading index.html last with no-cache…"
aws s3 cp "$BUILD_DIR/index.html" "s3://$BUCKET_NAME/index.html" \
  --cache-control "no-cache,must-revalidate" \
  --content-type "text/html; charset=utf-8"

DISTRIBUTION_QUERY="Stacks[0].Outputs[?OutputKey=='AdminWebDistributionId']."
DISTRIBUTION_QUERY+="OutputValue"
DISTRIBUTION_ID="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "$DISTRIBUTION_QUERY" \
  --output text)"

if [ -n "$DISTRIBUTION_ID" ] && [ "$DISTRIBUTION_ID" != "None" ]; then
  echo "Invalidating CloudFront distribution $DISTRIBUTION_ID"
  aws cloudfront create-invalidation \
    --distribution-id "$DISTRIBUTION_ID" \
    --paths "/*"
fi
