#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
APP_DIR="$ROOT_DIR/apps/public_www"
BUILD_DIR="$APP_DIR/dist"
STACK_NAME="${PUBLIC_WEBSITE_STACK_NAME:-lxsoftware-public-www}"
IMMUTABLE="public,max-age=31536000,immutable"

if [ ! -d "$BUILD_DIR/assets" ]; then
  echo "Hashed assets not found at $BUILD_DIR/assets"
  echo "Run: (cd apps/public_www && npm run build)"
  exit 1
fi

BUCKET_QUERY="Stacks[0].Outputs[?OutputKey=='PublicWebsiteBucketName']."
BUCKET_QUERY+="OutputValue"
BUCKET_NAME="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "$BUCKET_QUERY" \
  --output text)"

if [ -z "$BUCKET_NAME" ] || [ "$BUCKET_NAME" = "None" ]; then
  echo "Public website bucket output not found for $STACK_NAME"
  exit 1
fi

# Never sync the whole dist tree with one Cache-Control. That writes
# index.html as immutable and only corrects it afterwards, so a fetch in
# the gap caches the shell for a year.
echo "Uploading hashed assets to s3://$BUCKET_NAME/assets"
aws s3 sync "$BUILD_DIR/assets" "s3://$BUCKET_NAME/assets" \
  --cache-control "$IMMUTABLE"

if [ -d "$BUILD_DIR/media" ]; then
  echo "Syncing media by size"
  aws s3 sync "$BUILD_DIR/media" "s3://$BUCKET_NAME/media" \
    --size-only --delete \
    --cache-control "$IMMUTABLE"
fi

content_type() {
  case "$1" in
    *.html) printf '%s' "text/html; charset=utf-8" ;;
    *.json) printf '%s' "application/json; charset=utf-8" ;;
    *.txt) printf '%s' "text/plain; charset=utf-8" ;;
    *.xml) printf '%s' "application/xml; charset=utf-8" ;;
    *.webmanifest) printf '%s' "application/manifest+json" ;;
    *.svg) printf '%s' "image/svg+xml" ;;
    *.png) printf '%s' "image/png" ;;
    *.jpg|*.jpeg) printf '%s' "image/jpeg" ;;
    *.webp) printf '%s' "image/webp" ;;
    *.ico) printf '%s' "image/x-icon" ;;
    *) printf '%s' "application/octet-stream" ;;
  esac
}

cache_control() {
  case "$1" in
    index.html|robots.txt|sitemap.xml|llms.txt|llms-full.txt|site.webmanifest|*/*)
      # Unhashed paths (the shell, and public/ directories such as images/)
      # must revalidate. A year-long immutable cache would keep a replaced
      # logo after the next deploy.
      printf '%s' "no-cache" ;;
    *)
      printf '%s' "$IMMUTABLE" ;;
  esac
}

upload_file() {
  local path="$1"
  local key="$2"
  aws s3 cp "$path" "s3://$BUCKET_NAME/$key" \
    --cache-control "$(cache_control "$key")" \
    --content-type "$(content_type "$path")"
}

echo "Uploading site root"
for path in "$BUILD_DIR"/*; do
  [ -f "$path" ] || continue
  upload_file "$path" "$(basename "$path")"
done

# Vite copies public/ into dist/, including directories such as images/.
# The root loop only uploads files, and the earlier syncs only cover
# assets/ and media/, so those directories never reached S3. CloudFront
# then served index.html for the logo URLs.
echo "Uploading unhashed public directories"
for path in "$BUILD_DIR"/*; do
  [ -d "$path" ] || continue
  name="$(basename "$path")"
  case "$name" in
    assets|media) continue ;;
  esac
  while IFS= read -r -d '' file; do
    upload_file "$file" "${file#"$BUILD_DIR"/}"
  done < <(find "$path" -type f -print0)
done

echo "Pruning retired hashed assets"
aws s3 sync "$BUILD_DIR/assets" "s3://$BUCKET_NAME/assets" --delete \
  --cache-control "$IMMUTABLE"

DISTRIBUTION_QUERY="Stacks[0].Outputs[?OutputKey=='PublicWebsiteDistributionId']."
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
