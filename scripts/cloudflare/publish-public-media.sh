#!/usr/bin/env bash
# Publish the harbour renditions to R2 and attach media.lx-software.com.
#
# Requires CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID.
# The token needs Account → Workers R2 Storage → Edit.
# R2 has to be enabled in the Cloudflare dashboard first. The API returns
# error 10042 until that one-time terms acceptance is done, and it cannot
# be completed from this script.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MEDIA="$ROOT/apps/public_www/public/media"
BUCKET="${R2_BUCKET:-lx-software-media}"
DOMAIN="${R2_DOMAIN:-media.lx-software.com}"
ZONE_NAME="${CF_ZONE_NAME:-lx-software.com}"
ACCOUNT="${CLOUDFLARE_ACCOUNT_ID:?Set CLOUDFLARE_ACCOUNT_ID}"
TOKEN="${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN}"

api() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "$body" \
      "$url"
  else
    curl -sS -X "$method" \
      -H "Authorization: Bearer $TOKEN" \
      "$url"
  fi
}

echo "Creating R2 bucket $BUCKET (ignored if it already exists)"
CREATE="$(api POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/r2/buckets" "{\"name\":\"$BUCKET\"}")"
python3 - "$CREATE" << 'PY'
import json, sys
payload = json.loads(sys.argv[1])
if payload.get("success"):
    raise SystemExit(0)
errors = payload.get("errors") or []
if any(err.get("code") == 10042 for err in errors):
    print("R2 is not enabled on this account.", file=sys.stderr)
    print("Cloudflare Dashboard → R2 → enable R2 and accept the terms, then re-run.", file=sys.stderr)
    raise SystemExit(2)
# 10004 / already exists is fine; anything else fails.
if any("already" in (err.get("message") or "").lower() for err in errors):
    raise SystemExit(0)
print(payload, file=sys.stderr)
raise SystemExit(1)
PY

ZONE="$(api GET "https://api.cloudflare.com/client/v4/zones?name=$ZONE_NAME")"
ZONE_ID="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["result"][0]["id"])' <<<"$ZONE")"

echo "Attaching custom domain $DOMAIN"
DOMAIN_RESULT="$(api POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/r2/buckets/$BUCKET/domains/custom" \
  "{\"domain\":\"$DOMAIN\",\"enabled\":true,\"zoneId\":\"$ZONE_ID\",\"minTLS\":\"1.2\"}")"
python3 - "$DOMAIN_RESULT" << 'PY'
import json, sys
payload = json.loads(sys.argv[1])
if payload.get("success"):
    raise SystemExit(0)
errors = payload.get("errors") or []
if any("already" in (err.get("message") or "").lower() for err in errors):
    print("Custom domain already attached")
    raise SystemExit(0)
print(payload, file=sys.stderr)
raise SystemExit(1)
PY

upload() {
  local file="$1"
  local type="$2"
  echo "Uploading $file"
  npx --yes wrangler@4 r2 object put "$BUCKET/$file" \
    --file "$MEDIA/$file" \
    --content-type "$type" \
    --cache-control "public, max-age=31536000, immutable" \
    --remote
}

upload hk-harbour-v1-720.mp4 video/mp4
upload hk-harbour-v1-480.mp4 video/mp4
upload hk-harbour-v1-720.webm video/webm
upload hk-harbour-v1-480.webm video/webm
upload hk-harbour-v1-poster.webp image/webp
upload hk-harbour-v1-poster.jpg image/jpeg

echo "Uploaded. Set the production GitHub variable VITE_MEDIA_BASE_URL=https://$DOMAIN"
echo "Then confirm a ranged GET: curl -I -H 'Range: bytes=0-1' https://$DOMAIN/hk-harbour-v1-720.mp4"
echo "After that GET returns 206, drop the video binaries from git. The posters stay; the page preloads them from this origin."
echo "Do not rewrite history with Git LFS."
echo "  git rm apps/public_www/public/media/hk-harbour-v1-720.mp4 \\"
echo "         apps/public_www/public/media/hk-harbour-v1-480.mp4 \\"
echo "         apps/public_www/public/media/hk-harbour-v1-720.webm \\"
echo "         apps/public_www/public/media/hk-harbour-v1-480.webm \\"
echo "         apps/public_www/media/source/hk-harbour-master.mp4"
