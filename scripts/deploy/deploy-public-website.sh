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
    *.html|*.txt|*.xml|site.webmanifest|*/*)
      # Unhashed paths (the pre-rendered pages, crawler files, and public/
      # directories such as images/) must revalidate. A year-long immutable
      # cache would keep a replaced logo or stale copy after the next deploy.
      printf '%s' "no-cache" ;;
    *.*)
      printf '%s' "$IMMUTABLE" ;;
    *)
      # Extensionless keys are the pre-rendered routes (/about).
      printf '%s' "no-cache" ;;
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

# The build pre-renders every route to dist/<route>.html (and
# dist/<route>/index.html for static previews). CloudFront maps the request
# /about straight to the S3 key "about", so each page is also uploaded under
# its extensionless key. Without that, /about would 403 and fall back to the
# home shell, and crawlers would index the home copy under the page URL.
echo "Uploading pre-rendered routes"
for path in "$BUILD_DIR"/*.html; do
  [ -f "$path" ] || continue
  name="$(basename "$path")"
  [ "$name" = "index.html" ] && continue
  upload_file "$path" "${name%.html}"
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

# IndexNow tells Bing, Yandex, Naver, Seznam and Yep that these URLs changed
# (Google does not take part; it reads sitemap.xml). The key file is public
# by design (public/indexnow.txt, served at /indexnow.txt). The ping never
# fails the deploy: a missing key, no curl, or a 4xx/5xx is only logged.
# Set INDEXNOW_DISABLED=1 to skip it.
indexnow_ping() {
  local key_file="$BUILD_DIR/indexnow.txt"
  local sitemap="$BUILD_DIR/sitemap.xml"
  if [ "${INDEXNOW_DISABLED:-0}" = "1" ]; then
    echo "IndexNow ping skipped (INDEXNOW_DISABLED=1)"
    return 0
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "IndexNow ping skipped (curl not found)"
    return 0
  fi
  if [ ! -f "$key_file" ] || [ ! -f "$sitemap" ]; then
    echo "IndexNow ping skipped (indexnow.txt or sitemap.xml missing)"
    return 0
  fi
  local key urls host origin body status
  key="$(tr -d '[:space:]' < "$key_file")"
  urls="$(sed -n 's:.*<loc>\(.*\)</loc>.*:\1:p' "$sitemap")"
  if [ -z "$key" ] || [ -z "$urls" ]; then
    echo "IndexNow ping skipped (empty key or sitemap)"
    return 0
  fi
  origin="$(printf '%s\n' "$urls" | head -n 1 | sed -E 's#^(https?://[^/]+).*#\1#')"
  host="${origin#*://}"
  body="$(printf '%s\n' "$urls" | python3 -c '
import json, sys
host, origin, key = sys.argv[1:4]
urls = [line.strip() for line in sys.stdin if line.strip()]
print(json.dumps({
    "host": host,
    "key": key,
    "keyLocation": f"{origin}/indexnow.txt",
    "urlList": urls,
}))
' "$host" "$origin" "$key")"
  echo "IndexNow: submitting $(printf '%s\n' "$urls" | wc -l | tr -d ' ') URLs for $host"
  status="$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST "https://api.indexnow.org/indexnow" \
    -H "Content-Type: application/json; charset=utf-8" \
    --data "$body" || true)"
  case "$status" in
    200|202) echo "IndexNow: accepted ($status)" ;;
    *) echo "IndexNow: not accepted (HTTP ${status:-none}); continuing" ;;
  esac
}

indexnow_ping
