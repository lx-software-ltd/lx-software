#!/usr/bin/env bash
# Smoke-test setup-board-cloudshell.sh with a fake aws CLI (no live account).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
FAKE="$(mktemp)"
chmod +x "$FAKE"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --region ]]; then shift 2; fi
svc="${1:-}"
op="${2:-}"
case "$svc $op" in
  "sts get-caller-identity")
    echo '{"Account":"588024549699","Arn":"arn:aws:iam::588024549699:root","UserId":"AIDAROOT"}'
    ;;
  "cloudformation describe-stacks")
    echo '{"Stacks":[{"Parameters":[{"ParameterKey":"GitHubReadTokenSecretArn","ParameterValue":""},{"ParameterKey":"MetaPageId","ParameterValue":""},{"ParameterKey":"GoogleClientSecret","ParameterValue":"hidden"}],"Outputs":[{"OutputKey":"AdminApiBaseUrl","OutputValue":"https://api.example/"}]}]}'
    ;;
  "lambda list-functions")
    echo '{"Functions":[{"FunctionName":"siutindei-ApiFn"},{"FunctionName":"lxsoftware-AdminApiFn"}]}'
    ;;
  "rds describe-db-clusters")
    echo '{"DBClusters":[{"DBClusterIdentifier":"siutindei","DBClusterArn":"arn:aws:rds:ap-southeast-1:588024549699:cluster:siutindei","HttpEndpointEnabled":true,"MasterUserSecret":{"SecretArn":"arn:aws:secretsmanager:ap-southeast-1:588024549699:secret:db"}}]}'
    ;;
  "secretsmanager describe-secret")
    exit 255
    ;;
  *)
    echo '{}'
    ;;
esac
EOF

bash -n "$ROOT/setup-board-cloudshell.sh"

out="$(mktemp)"
AWS="$FAKE" \
  META_PAGE_ID=1234567890 \
  BOARD_AWS_LAMBDA_NAMES="" \
  bash "$ROOT/setup-board-cloudshell.sh" --dry-run --non-interactive --yes --region ap-southeast-1 \
  | tee "$out"

grep -q "account: 588024549699" "$out"
grep -q "identity: arn:aws:iam::588024549699:root" "$out"
grep -q "siutindei-ApiFn" "$out"
grep -q "cluster:siutindei" "$out"
grep -q "MetaPageId=1234567890" "$out"
grep -q "BoardAwsLambdaNames=siutindei-ApiFn" "$out"
grep -q "Dry run — nothing written to AWS." "$out"
grep -q "Write CDK param fragment (no live stack change)" "$out"
! grep -q "Update CloudFormation stack" "$out"
# must not leak a fake token if we did not set one
! grep -qi "github_pat" "$out"

# verify subcommand uses the sibling python checker
ver="$(mktemp)"
AWS="$FAKE" bash "$ROOT/setup-board-cloudshell.sh" verify --region ap-southeast-1 --stack lxsoftware \
  >"$ver" 2>&1 || true
# fake aws from this smoke file is not the verify fake; just ensure dispatch works
# (full verify coverage is test_verify_board_secrets.py)
grep -qE "Executive Board secrets|error:|OpenRouter|aws CLI" "$ver" || {
  echo "verify dispatch produced unexpected output:" >&2
  cat "$ver" >&2
  exit 1
}
echo "cloudshell dry-run smoke: OK"
