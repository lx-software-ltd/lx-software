#!/usr/bin/env bash
# Executive Board setup — run this in AWS CloudShell as root (or an admin).
#
# CloudShell already has the AWS CLI and python3. You do not need the git
# repo. Secrets are typed (hidden) or uploaded via Actions → Upload file.
#
#   curl -fsSL https://raw.githubusercontent.com/lx-software-ltd/lx-software/main/scripts/setup-board-cloudshell.sh -o setup-board-cloudshell.sh
#   bash setup-board-cloudshell.sh
#
# Do NOT pipe curl to bash — prompts need a real terminal.
#
# What it does (does NOT touch the CDK-managed CloudFormation stack):
#   1. Creates / updates Secrets Manager secrets
#   2. Writes ~/board-params-fragment.json for you to merge into
#      backend/infrastructure/params/production.json and deploy via CDK
#   3. Activates the Cost Explorer tag aws:cloudformation:stack-name
#      (Billing, not the lxsoftware stack)
#   4. Optionally applies receivables.sql via the RDS Data API (siutindei
#      Aurora, not the lxsoftware stack)
#
# It never prints a secret value. The live stack changes only on the next
# GitHub / CDK deploy, once the fragment is committed.

set -euo pipefail

AWS="${AWS:-aws}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-southeast-1}}"
STACK="${BOARD_STACK:-lxsoftware}"
LAMBDA_PREFIX="${BOARD_LAMBDA_PREFIX:-siutindei}"
SQL_URL="${BOARD_SQL_URL:-https://raw.githubusercontent.com/lx-software-ltd/lx-software/main/scripts/siutindei/receivables.sql}"
COST_TAG="aws:cloudformation:stack-name"
CE_REGION="us-east-1"
DRY_RUN=0
YES=0
NONINTERACTIVE=0
VERIFY_ONLY=0

SECRET_GITHUB="lxsoftware-admin-github-read-token"
SECRET_SEARCH="lxsoftware-admin-search-api-key"
SECRET_META_TOKEN="lxsoftware-admin-meta-board-token"
SECRET_META_APP="lxsoftware-admin-meta-app-secret"
SECRET_ASC="lxsoftware-admin-app-store-connect-key"
SECRET_PLAY="lxsoftware-admin-google-play-sa"
SECRET_GA="lxsoftware-admin-google-analytics-sa"

usage() {
  cat <<'EOF'
Usage: bash setup-board-cloudshell.sh [--dry-run] [--yes] [--region ap-southeast-1] [--stack lxsoftware]
       bash setup-board-cloudshell.sh verify [--region ap-southeast-1] [--stack lxsoftware]

Run inside AWS CloudShell while signed in as root (or an admin role).
Leave a prompt blank to skip that item.

  verify        Check secrets exist, have the right JSON/token shape, and
                are wired on the lxsoftware stack (never prints values)
  --dry-run     Print the plan; do not write to AWS
  --yes         Do not ask for the final confirmation
  --region      Override CloudShell's region (default: $AWS_REGION or ap-southeast-1)
  --stack       CloudFormation stack name (default: lxsoftware)
  --help
EOF
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_PY_URL="${BOARD_VERIFY_PY_URL:-https://raw.githubusercontent.com/lx-software-ltd/lx-software/main/scripts/verify-board-secrets.py}"

run_verify() {
  local py=""
  if [[ -f "$HERE/verify-board-secrets.py" ]]; then
    py="$HERE/verify-board-secrets.py"
  else
    py="$(mktemp)"
    curl -fsSL "$VERIFY_PY_URL" -o "$py" || die "could not download verify-board-secrets.py"
  fi
  exec python3 "$py" --region "$REGION" --stack "$STACK" --aws "$AWS"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    verify) shift; # region/stack parsed below, then run
      VERIFY_ONLY=1
      ;;
    --dry-run) DRY_RUN=1; shift ;;
    --yes) YES=1; shift ;;
    --non-interactive) NONINTERACTIVE=1; shift ;;
    --region) REGION="$2"; shift 2 ;;
    --stack) STACK="$2"; shift 2 ;;
    --lambda-prefix) LAMBDA_PREFIX="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$VERIFY_ONLY" -eq 1 ]]; then
  run_verify
fi

aws_cli() {
  "$AWS" --region "$REGION" "$@"
}

aws_ce() {
  "$AWS" --region "$CE_REGION" "$@"
}

die() { echo "error: $*" >&2; exit 1; }

prompt() {
  local label="$1" dest="$2" default="${3-}"
  local reply
  if [[ "$NONINTERACTIVE" -eq 1 ]]; then
    printf -v "$dest" '%s' "${!dest-}"
    return
  fi
  if [[ -n "$default" ]]; then
    read -r -p "$label [$default]: " reply || true
    printf -v "$dest" '%s' "${reply:-$default}"
  else
    read -r -p "$label: " reply || true
    printf -v "$dest" '%s' "$reply"
  fi
}

prompt_secret() {
  local label="$1" dest="$2"
  local reply
  if [[ "$NONINTERACTIVE" -eq 1 ]]; then
    printf -v "$dest" '%s' "${!dest-}"
    return
  fi
  read -r -s -p "$label (hidden, blank=skip): " reply || true
  echo
  printf -v "$dest" '%s' "$reply"
}

confirm() {
  local label="$1" default="${2:-n}"
  local reply
  if [[ "$YES" -eq 1 && "$default" == "y" ]]; then
    return 0
  fi
  if [[ "$NONINTERACTIVE" -eq 1 ]]; then
    [[ "$default" == "y" ]]
    return
  fi
  if [[ "$default" == "y" ]]; then
    read -r -p "$label [Y/n]: " reply || true
    [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
  else
    read -r -p "$label [y/N]: " reply || true
    [[ "$reply" =~ ^[Yy] ]]
  fi
}

upsert_secret() {
  local name="$1" value="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] upsert secret $name"
    echo "arn:aws:secretsmanager:${REGION}:000000000000:secret:${name}-XXXX"
    return
  fi
  if aws_cli secretsmanager describe-secret --secret-id "$name" >/dev/null 2>&1; then
    aws_cli secretsmanager put-secret-value --secret-id "$name" --secret-string "$value" >/dev/null
  else
    aws_cli secretsmanager create-secret \
      --name "$name" \
      --description "Executive Board (setup-board-cloudshell.sh)" \
      --secret-string "$value" >/dev/null
  fi
  aws_cli secretsmanager describe-secret --secret-id "$name" --query ARN --output text
}

secret_arn_if_exists() {
  local name="$1"
  aws_cli secretsmanager describe-secret --secret-id "$name" --query ARN --output text 2>/dev/null || true
}

# --- identity ----------------------------------------------------------------

IDENTITY_JSON=$(aws_cli sts get-caller-identity --output json) || die "aws sts failed — are you in CloudShell / have credentials?"
ACCOUNT=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["Account"])' <<<"$IDENTITY_JSON")
CALLER_ARN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["Arn"])' <<<"$IDENTITY_JSON")

echo "Executive Board setup (AWS CloudShell)"
echo "  account: $ACCOUNT"
echo "  identity: $CALLER_ARN"
echo "  region:   $REGION"
echo "  stack:    $STACK"
echo

if [[ "$CALLER_ARN" != *":root" && "$CALLER_ARN" != *":assumed-role/"* && "$NONINTERACTIVE" -eq 0 ]]; then
  echo "Note: this is not the account root ARN. An admin role is fine if it can"
  echo "write Secrets Manager, update CloudFormation, and call Cost Explorer."
  echo
fi

# --- discover ----------------------------------------------------------------

echo "Discovering…"
STACK_JSON=""
if STACK_JSON=$(aws_cli cloudformation describe-stacks --stack-name "$STACK" --output json 2>/dev/null); then
  echo "  stack $STACK: found"
else
  echo "  stack $STACK: NOT FOUND (secrets can still be created; stack update will be skipped)"
  STACK_JSON=""
fi

LAMBDAS=()
if FN_JSON=$(aws_cli lambda list-functions --output json 2>/dev/null); then
  mapfile -t LAMBDAS < <(python3 -c '
import json,sys
p=sys.argv[1]
fns=json.load(sys.stdin).get("Functions") or []
for f in fns:
    n=f.get("FunctionName") or ""
    if n.startswith(p):
        print(n)
' "$LAMBDA_PREFIX" <<<"$FN_JSON")
fi
if [[ ${#LAMBDAS[@]} -gt 0 ]]; then
  echo "  Lambdas starting with $LAMBDA_PREFIX:"
  for n in "${LAMBDAS[@]}"; do echo "    - $n"; done
else
  echo "  Lambdas starting with $LAMBDA_PREFIX: (none)"
fi

CLUSTER_ARN=""
CLUSTER_SECRET=""
if CL_JSON=$(aws_cli rds describe-db-clusters --output json 2>/dev/null); then
  while IFS=$'\t' read -r cid carc csec http; do
    [[ -z "${cid:-}" ]] && continue
    echo "  Aurora: $cid  http=$http"
    echo "          $carc"
    if [[ "$cid" == *siutindei* || "$carc" == *siutindei* ]]; then
      CLUSTER_ARN="$carc"
      CLUSTER_SECRET="$csec"
    fi
  done < <(python3 -c '
import json,sys
for c in json.load(sys.stdin).get("DBClusters") or []:
    sec=(c.get("MasterUserSecret") or {}).get("SecretArn") or ""
    http="yes" if c.get("HttpEndpointEnabled") else "no"
    print("\t".join([c.get("DBClusterIdentifier") or "", c.get("DBClusterArn") or "", sec, http]))
' <<<"$CL_JSON")
else
  echo "  Aurora: (could not list clusters)"
fi

EXISTING_SECRETS=()
for s in "$SECRET_GITHUB" "$SECRET_SEARCH" "$SECRET_META_TOKEN" "$SECRET_META_APP" "$SECRET_ASC" "$SECRET_PLAY" "$SECRET_GA"; do
  arn=$(secret_arn_if_exists "$s")
  if [[ -n "$arn" ]]; then
    echo "  secret exists: $s"
    EXISTING_SECRETS+=("$s=$arn")
  fi
done
echo

# --- prompts -----------------------------------------------------------------

GITHUB_TOKEN="${GITHUB_TOKEN-}"
SEARCH_API_KEY="${SEARCH_API_KEY-}"
META_BOARD_TOKEN="${META_BOARD_TOKEN-}"
META_APP_SECRET="${META_APP_SECRET-}"
META_VERIFY_TOKEN="${META_VERIFY_TOKEN-}"
META_PAGE_ID="${META_PAGE_ID-}"
META_IG_USER_ID="${META_IG_USER_ID-}"
META_WA_PHONE_NUMBER_ID="${META_WA_PHONE_NUMBER_ID-}"
META_WABA_ID="${META_WABA_ID-}"
META_AD_ACCOUNT_ID="${META_AD_ACCOUNT_ID-}"
ASC_KEY_ID="${ASC_KEY_ID-}"
ASC_ISSUER_ID="${ASC_ISSUER_ID-}"
ASC_KEY_FILE="${ASC_KEY_FILE-}"
ASC_APP_ID="${ASC_APP_ID-}"
ASC_VENDOR_NUMBER="${ASC_VENDOR_NUMBER-}"
PLAY_SA_FILE="${PLAY_SA_FILE-}"
PLAY_PACKAGE_NAME="${PLAY_PACKAGE_NAME-}"
GA_SA_FILE="${GA_SA_FILE-}"
GA4_PROPERTY_IDS="${GA4_PROPERTY_IDS-}"
GTM_CONTAINERS="${GTM_CONTAINERS-}"
BOARD_AWS_LAMBDA_NAMES="${BOARD_AWS_LAMBDA_NAMES-}"
SIUTINDEI_CLUSTER_ARN="${SIUTINDEI_CLUSTER_ARN:-$CLUSTER_ARN}"
SIUTINDEI_DB_SECRET_ARN="${SIUTINDEI_DB_SECRET_ARN:-$CLUSTER_SECRET}"
GRANT_BOARD_API_TO="${GRANT_BOARD_API_TO-}"
BOARD_MAIL_SENDING_ENABLED="${BOARD_MAIL_SENDING_ENABLED-}"

if [[ "$NONINTERACTIVE" -eq 0 ]]; then
  echo "Leave a prompt blank to skip. Upload files first: CloudShell → Actions → Upload file."
  echo
  echo "--- GitHub ---"
  prompt_secret "Fine-grained PAT (siutindei: Contents read, Issues r/w, Actions read, Metadata read, Security events read)" GITHUB_TOKEN
  echo "--- Research ---"
  prompt_secret "Brave Search API key" SEARCH_API_KEY
  echo "--- Meta ---"
  prompt_secret "System User long-lived token" META_BOARD_TOKEN
  prompt_secret "App secret (X-Hub-Signature-256)" META_APP_SECRET
  prompt "Verify token (blank = generate one)" META_VERIFY_TOKEN
  prompt "Page id" META_PAGE_ID
  prompt "Instagram professional-account id" META_IG_USER_ID
  prompt "WhatsApp phone-number id" META_WA_PHONE_NUMBER_ID
  prompt "WhatsApp Business Account id (optional)" META_WABA_ID
  prompt "Ad account id (act_… or numeric)" META_AD_ACCOUNT_ID
  echo "--- App Store Connect ---"
  echo "Upload the .p8 or a JSON {keyId,issuerId,privateKey} via Actions → Upload file."
  prompt "Path to .p8 or ASC JSON" ASC_KEY_FILE
  prompt "Key id (if not in the JSON)" ASC_KEY_ID
  prompt "Issuer id (if not in the JSON)" ASC_ISSUER_ID
  prompt "App id (numeric)" ASC_APP_ID
  prompt "Vendor number (Payments and Financial Reports)" ASC_VENDOR_NUMBER
  echo "--- Google Play ---"
  prompt "Path to Play service-account JSON" PLAY_SA_FILE
  prompt "Package name (e.g. com.siutindei.app)" PLAY_PACKAGE_NAME
  echo "--- GA4 / GTM (dedicated SA, not the Play key) ---"
  prompt "Path to Analytics service-account JSON" GA_SA_FILE
  prompt "GA4 property ids (comma-separated)" GA4_PROPERTY_IDS
  prompt "GTM account:container pairs" GTM_CONTAINERS
  echo "--- AWS / Aurora ---"
  local_default=""
  if [[ ${#LAMBDAS[@]} -gt 0 ]]; then
    local_default=$(IFS=,; echo "${LAMBDAS[*]}")
  fi
  prompt "Lambda names for aws_lambda_health" BOARD_AWS_LAMBDA_NAMES "$local_default"
  prompt "Siutindei cluster ARN" SIUTINDEI_CLUSTER_ARN "$SIUTINDEI_CLUSTER_ARN"
  prompt "Siutindei DB secret ARN" SIUTINDEI_DB_SECRET_ARN "$SIUTINDEI_DB_SECRET_ARN"
  prompt "GRANT board_api TO this DB username (optional)" GRANT_BOARD_API_TO
  prompt "BoardMailSendingEnabled (true/false, blank=keep)" BOARD_MAIL_SENDING_ENABLED
fi

if [[ -z "$BOARD_AWS_LAMBDA_NAMES" && ${#LAMBDAS[@]} -gt 0 ]]; then
  BOARD_AWS_LAMBDA_NAMES=$(IFS=,; echo "${LAMBDAS[*]}")
fi

if [[ -z "$META_VERIFY_TOKEN" && ( -n "$META_BOARD_TOKEN" || -n "$META_APP_SECRET" || -n "$META_PAGE_ID" ) ]]; then
  META_VERIFY_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
  echo "Generated MetaVerifyToken (saved to ~/board-meta-verify-token.txt; add it as a GitHub Actions secret, do not commit it)."
fi

# --- build ASC / SA payloads -------------------------------------------------

ASC_JSON=""
if [[ -n "$ASC_KEY_FILE" ]]; then
  [[ -f "$ASC_KEY_FILE" ]] || die "ASC file not found: $ASC_KEY_FILE"
  ASC_JSON=$(python3 - "$ASC_KEY_FILE" "$ASC_KEY_ID" "$ASC_ISSUER_ID" "$ASC_APP_ID" "$ASC_VENDOR_NUMBER" <<'PY'
import json, pathlib, sys
path, key_id, issuer, app_id, vendor = sys.argv[1:6]
raw = pathlib.Path(path).read_text()
payload = {}
if raw.lstrip().startswith("{"):
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("ASC JSON must be an object")
    key_id = key_id or str(payload.get("keyId") or payload.get("kid") or "")
    issuer = issuer or str(payload.get("issuerId") or payload.get("iss") or "")
    pem = str(payload.get("privateKey") or payload.get("p8") or payload.get("key") or "")
    app_id = app_id or str(payload.get("appId") or payload.get("app_id") or "")
    vendor = vendor or str(payload.get("vendorNumber") or payload.get("vendor_number") or "")
else:
    pem = raw
out = {"keyId": key_id.strip(), "issuerId": issuer.strip(), "privateKey": pem.strip()}
if not (out["keyId"] and out["issuerId"] and out["privateKey"]):
    raise SystemExit("ASC secret needs keyId, issuerId and privateKey")
if app_id.strip():
    out["appId"] = app_id.strip()
if vendor.strip():
    out["vendorNumber"] = vendor.strip()
print(json.dumps(out))
PY
)
  ASC_APP_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("appId",""))' "$ASC_JSON")
  ASC_VENDOR_NUMBER=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("vendorNumber",""))' "$ASC_JSON")
fi

PLAY_JSON=""
if [[ -n "$PLAY_SA_FILE" ]]; then
  [[ -f "$PLAY_SA_FILE" ]] || die "Play SA file not found: $PLAY_SA_FILE"
  PLAY_JSON=$(python3 - "$PLAY_SA_FILE" "$PLAY_PACKAGE_NAME" <<'PY'
import json, pathlib, sys
raw = json.loads(pathlib.Path(sys.argv[1]).read_text())
if not isinstance(raw, dict):
    raise SystemExit("Play SA must be a JSON object")
if not (raw.get("client_email") or raw.get("clientEmail")) or not (raw.get("private_key") or raw.get("privateKey")):
    raise SystemExit("Play SA JSON needs client_email and private_key")
pkg = sys.argv[2].strip()
if pkg and "packageName" not in raw and "package_name" not in raw:
    raw = {**raw, "packageName": pkg}
print(json.dumps(raw))
PY
)
  PLAY_PACKAGE_NAME=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("packageName") or d.get("package_name") or "")' "$PLAY_JSON")
fi

GA_JSON=""
if [[ -n "$GA_SA_FILE" ]]; then
  [[ -f "$GA_SA_FILE" ]] || die "GA SA file not found: $GA_SA_FILE"
  GA_JSON=$(python3 - "$GA_SA_FILE" <<'PY'
import json, pathlib, sys
raw = json.loads(pathlib.Path(sys.argv[1]).read_text())
if not (raw.get("client_email") or raw.get("clientEmail")) or not (raw.get("private_key") or raw.get("privateKey")):
    raise SystemExit("GA SA JSON needs client_email and private_key")
print(json.dumps(raw))
PY
)
fi

DO_COST=1
DO_SQL=0
if [[ "$NONINTERACTIVE" -eq 0 ]]; then
  confirm "Activate Cost Explorer tag $COST_TAG (Billing, not the CDK stack)?" y && DO_COST=1 || DO_COST=0
  confirm "Apply receivables.sql via the RDS Data API (siutindei Aurora)?" n && DO_SQL=1 || DO_SQL=0
fi

# --- plan --------------------------------------------------------------------

declare -A CFN_SET=()
ACTIONS=()

plan_secret() {
  local name="$1" value="$2" cfn="$3"
  [[ -z "$value" ]] && return
  ACTIONS+=("Upsert secret $name")
  CFN_SET["$cfn"]="__SECRET__:$name"
}

plan_secret "$SECRET_GITHUB" "$GITHUB_TOKEN" "GitHubReadTokenSecretArn"
plan_secret "$SECRET_SEARCH" "$SEARCH_API_KEY" "SearchApiKeySecretArn"
plan_secret "$SECRET_META_TOKEN" "$META_BOARD_TOKEN" "MetaBoardTokenSecretArn"
plan_secret "$SECRET_META_APP" "$META_APP_SECRET" "MetaAppSecretSecretArn"
plan_secret "$SECRET_ASC" "$ASC_JSON" "AppStoreConnectKeySecretArn"
plan_secret "$SECRET_PLAY" "$PLAY_JSON" "GooglePlayServiceAccountSecretArn"
plan_secret "$SECRET_GA" "$GA_JSON" "GoogleAnalyticsServiceAccountSecretArn"

put_cfn() {
  local k="$1" v="$2"
  if [[ -n "$v" ]]; then
    CFN_SET["$k"]="$v"
  fi
}

put_cfn MetaVerifyToken "$META_VERIFY_TOKEN"
put_cfn MetaPageId "$META_PAGE_ID"
put_cfn MetaIgUserId "$META_IG_USER_ID"
put_cfn MetaWaPhoneNumberId "$META_WA_PHONE_NUMBER_ID"
put_cfn MetaWabaId "$META_WABA_ID"
put_cfn MetaAdAccountId "$META_AD_ACCOUNT_ID"
put_cfn AppStoreConnectAppId "$ASC_APP_ID"
put_cfn AppStoreConnectVendorNumber "$ASC_VENDOR_NUMBER"
put_cfn GooglePlayPackageName "$PLAY_PACKAGE_NAME"
put_cfn Ga4PropertyIds "$GA4_PROPERTY_IDS"
put_cfn GtmContainers "$GTM_CONTAINERS"
put_cfn BoardAwsLambdaNames "$BOARD_AWS_LAMBDA_NAMES"
put_cfn SiutindeiClusterArn "$SIUTINDEI_CLUSTER_ARN"
put_cfn SiutindeiDbSecretArn "$SIUTINDEI_DB_SECRET_ARN"
put_cfn BoardMailSendingEnabled "$BOARD_MAIL_SENDING_ENABLED"

[[ "$DO_COST" -eq 1 ]] && ACTIONS+=("Activate cost allocation tag $COST_TAG (us-east-1 Billing)")
[[ "$DO_SQL" -eq 1 ]] && ACTIONS+=("Apply receivables.sql via RDS Data API")
ACTIONS+=("Write CDK param fragment (no live stack change)")

echo
echo "Plan:"
if [[ ${#ACTIONS[@]} -eq 0 && ${#CFN_SET[@]} -eq 0 ]]; then
  echo "  (nothing to do)"
else
  if ((${#ACTIONS[@]})); then
    for a in "${ACTIONS[@]}"; do
      echo "  - $a"
    done
  fi
  if [[ ${#CFN_SET[@]} -gt 0 ]]; then
    echo "  Stack / fragment keys:"
    for k in $(printf '%s\n' "${!CFN_SET[@]}" | sort); do
      val="${CFN_SET[$k]}"
      if [[ "$val" == __SECRET__:* ]]; then
        echo "    $k=<ARN of ${val#__SECRET__:}>"
      elif [[ "$k" == "MetaVerifyToken" ]]; then
        echo "    $k=<redacted ${#val} chars>"
      else
        echo "    $k=$val"
      fi
    done
  fi
fi
echo

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry run — nothing written to AWS."
  exit 0
fi

if [[ ${#ACTIONS[@]} -eq 0 && ${#CFN_SET[@]} -eq 0 ]]; then
  echo "Nothing to apply."
  exit 0
fi

if ! confirm "Create secrets / write the CDK fragment (the live stack is not changed)?" n; then
  echo "Aborted."
  exit 1
fi

# --- apply -------------------------------------------------------------------

FRAGMENT="{}"
add_fragment() {
  local key="$1" value="$2"
  FRAGMENT=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); d[sys.argv[2]]=sys.argv[3]; print(json.dumps(d, indent=2))' \
    "$FRAGMENT" "lxsoftware:$key" "$value")
}

echo
echo "Applying…"

if [[ -n "$GITHUB_TOKEN" ]]; then
  arn=$(upsert_secret "$SECRET_GITHUB" "$GITHUB_TOKEN")
  CFN_SET[GitHubReadTokenSecretArn]="$arn"
  echo "  $SECRET_GITHUB -> $arn"
fi
if [[ -n "$SEARCH_API_KEY" ]]; then
  arn=$(upsert_secret "$SECRET_SEARCH" "$SEARCH_API_KEY")
  CFN_SET[SearchApiKeySecretArn]="$arn"
  echo "  $SECRET_SEARCH -> $arn"
fi
if [[ -n "$META_BOARD_TOKEN" ]]; then
  arn=$(upsert_secret "$SECRET_META_TOKEN" "$META_BOARD_TOKEN")
  CFN_SET[MetaBoardTokenSecretArn]="$arn"
  echo "  $SECRET_META_TOKEN -> $arn"
fi
if [[ -n "$META_APP_SECRET" ]]; then
  arn=$(upsert_secret "$SECRET_META_APP" "$META_APP_SECRET")
  CFN_SET[MetaAppSecretSecretArn]="$arn"
  echo "  $SECRET_META_APP -> $arn"
fi
if [[ -n "$ASC_JSON" ]]; then
  arn=$(upsert_secret "$SECRET_ASC" "$ASC_JSON")
  CFN_SET[AppStoreConnectKeySecretArn]="$arn"
  echo "  $SECRET_ASC -> $arn"
fi
if [[ -n "$PLAY_JSON" ]]; then
  arn=$(upsert_secret "$SECRET_PLAY" "$PLAY_JSON")
  CFN_SET[GooglePlayServiceAccountSecretArn]="$arn"
  echo "  $SECRET_PLAY -> $arn"
fi
if [[ -n "$GA_JSON" ]]; then
  arn=$(upsert_secret "$SECRET_GA" "$GA_JSON")
  CFN_SET[GoogleAnalyticsServiceAccountSecretArn]="$arn"
  echo "  $SECRET_GA -> $arn"
fi

if [[ -n "$META_VERIFY_TOKEN" ]]; then
  umask 077
  printf '%s\n' "$META_VERIFY_TOKEN" > "$HOME/board-meta-verify-token.txt"
  echo "  MetaVerifyToken saved to ~/board-meta-verify-token.txt (not printed)."
fi

for k in "${!CFN_SET[@]}"; do
  val="${CFN_SET[$k]}"
  [[ "$val" == __SECRET__:* ]] && continue
  add_fragment "$k" "$val"
done

FRAGMENT_PATH="${HOME:-/tmp}/board-params-fragment.json"
printf '%s\n' "$FRAGMENT" > "$FRAGMENT_PATH"
echo "  wrote $FRAGMENT_PATH"
echo "  merge that into backend/infrastructure/params/production.json, commit, then run Deploy Backend (CDK)."

if [[ "$DO_COST" -eq 1 ]]; then
  aws_ce ce update-cost-allocation-tags-status \
    --cost-allocation-tags-status "TagKey=$COST_TAG,Status=Active" >/dev/null \
    || echo "  warning: could not activate $COST_TAG (Billing permissions / 24h delay is normal)"
  echo "  cost allocation tag $COST_TAG requested Active"
fi

if [[ "$DO_SQL" -eq 1 ]]; then
  [[ -n "$SIUTINDEI_CLUSTER_ARN" && -n "$SIUTINDEI_DB_SECRET_ARN" ]] \
    || die "apply SQL needs Siutindei cluster ARN and DB secret ARN"
  SQL_FILE=$(mktemp)
  if [[ -f "${BOARD_SQL_FILE:-}" ]]; then
    cp "$BOARD_SQL_FILE" "$SQL_FILE"
  else
    curl -fsSL "$SQL_URL" -o "$SQL_FILE" || die "could not download $SQL_URL"
  fi
  python3 - "$SQL_FILE" "$SIUTINDEI_CLUSTER_ARN" "$SIUTINDEI_DB_SECRET_ARN" "${SIUTINDEI_DATABASE:-siutindei}" "$REGION" "$GRANT_BOARD_API_TO" "$AWS" <<'PY'
import json, re, subprocess, sys

sql_path, cluster, secret, database, region, grant_to, aws = sys.argv[1:8]

def split_sql(sql: str) -> list[str]:
    statements, buf, i = [], [], 0
    in_single = False
    dollar = None
    dollar_re = re.compile(r"\$[A-Za-z0-9_]*\$")

    def flush():
        text = "".join(buf).strip()
        buf.clear()
        if not text:
            return
        stripped = re.sub(r"^\s*--[^\n]*\n?", "", text, flags=re.M).strip()
        upper = re.sub(r"\s+", " ", stripped).upper()
        if upper in {"BEGIN", "BEGIN;", "COMMIT", "COMMIT;"}:
            return
        statements.append(stripped)

    while i < len(sql):
        ch = sql[i]
        if dollar:
            if sql.startswith(dollar, i):
                buf.append(dollar)
                i += len(dollar)
                dollar = None
                continue
            buf.append(ch)
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'" and sql[i:i+2] == "''":
                buf.append("'")
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if sql.startswith("--", i):
            nl = sql.find("\n", i)
            if nl == -1:
                break
            buf.append(sql[i:nl+1])
            i = nl + 1
            continue
        m = dollar_re.match(sql, i)
        if m:
            dollar = m.group(0)
            buf.append(dollar)
            i = m.end()
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            flush()
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    return statements

stmts = split_sql(open(sql_path, encoding="utf-8").read())
for i, stmt in enumerate(stmts, start=1):
    preview = re.sub(r"\s+", " ", stmt)[:80]
    subprocess.run(
        [aws, "--region", region, "rds-data", "execute-statement",
         "--resource-arn", cluster, "--secret-arn", secret,
         "--database", database, "--sql", stmt],
        check=True, stdout=subprocess.DEVNULL,
    )
    print(f"  SQL {i}/{len(stmts)} OK {preview}")
if grant_to:
    safe = grant_to.replace('"', "")
    subprocess.run(
        [aws, "--region", region, "rds-data", "execute-statement",
         "--resource-arn", cluster, "--secret-arn", secret,
         "--database", database, "--sql", f'GRANT board_api TO "{safe}"'],
        check=True, stdout=subprocess.DEVNULL,
    )
    print(f"  SQL GRANT board_api TO {safe} OK")
PY
fi

API=""
INBOUND=""
if [[ -n "$STACK_JSON" ]]; then
  API=$(python3 -c 'import json,sys; o={x["OutputKey"]:x["OutputValue"] for x in json.load(sys.stdin)["Stacks"][0].get("Outputs") or []}; print(o.get("AdminApiBaseUrl",""))' <<<"$STACK_JSON")
  INBOUND=$(python3 -c 'import json,sys; o={x["OutputKey"]:x["OutputValue"] for x in json.load(sys.stdin)["Stacks"][0].get("Outputs") or []}; print(o.get("BoardMailInboundAddress",""))' <<<"$STACK_JSON")
fi

echo
echo "Done. The CDK stack was not modified."
echo
echo "Next (git / CDK):"
echo "  1. Merge $FRAGMENT_PATH into backend/infrastructure/params/production.json,"
echo "     commit, and run the Deploy Backend workflow. That is what updates"
echo "     AdminApiFn. Put MetaVerifyToken in GitHub Actions as a secret"
echo "     (do not commit it; it is also in ~/board-meta-verify-token.txt)."
echo
echo "Still manual:"
echo "  2. Meta: subscribe GET/POST ${API:-<AdminApiBaseUrl>}/webhooks/meta"
echo "     with that verify token. Enable WhatsApp coexistence."
echo "  3. Cloudflare Email Routing → destination ${INBOUND:-<BoardMailInboundAddress>}"
echo "     Worker scripts/cloudflare/siutindei-mail-fanout.js (OWNER + BOARD dest)."
echo "  4. App Store / Play / GA4 console roles for the keys you uploaded."
echo "  5. Executive Board → Settings: allow-list, spend caps, stand-ups."
