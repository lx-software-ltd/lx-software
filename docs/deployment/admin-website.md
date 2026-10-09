# Deploying and operating the admin website

Runbook for the `lxsoftware` and `lxsoftware-admin-web` stacks and the
admin SPA. Prerequisites (OIDC, `GitHubActionsRole`, CDK Bootstrap,
GitHub environment) are in [`setup.md`](./setup.md); the architecture is
in [`../architecture/overview.md`](../architecture/overview.md) and
[`../architecture/security.md`](../architecture/security.md); the
Executive Board design is in
[`../architecture/executive-board.md`](../architecture/executive-board.md).

## Pre-deploy checklist

**Deploy Backend** runs on `main` when `backend/infrastructure/**`,
`backend/lambda/**` or `contracts/**` change (or via **Run workflow**).

1. **GitHub environment** — `AWS_ACCOUNT_ID`, `AWS_REGION`, optional
   `CDK_BOOTSTRAP_QUALIFIER`, `CDK_PARAM_FILE`, `ADMIN_ACM_CERT_ARN`,
   `ADMIN_GOOGLE_CLIENT_ID`, `ADMIN_FEDERATED_EMAIL_ALLOWLIST`
   (comma-separated lower-case emails that receive `admin` via Pre Token
   Generation — every Google admin and the bootstrap email),
   `ADMIN_BOOTSTRAP_EMAIL`, and after the first deploy the SPA vars
   `ADMIN_COGNITO_*` and `ADMIN_API_BASE_URL`. Secrets
   `ADMIN_GOOGLE_CLIENT_SECRET` and `ADMIN_BOOTSTRAP_TEMP_PASSWORD` (14+
   chars, mixed classes, or `adminCreateUser` fails).
2. **Region** — `AWS_REGION` must match where CDK Bootstrap ran (SSM
   `/cdk-bootstrap/<qualifier>/version` must exist) and where the public
   site deploys.
3. **ACM** — `ADMIN_ACM_CERT_ARN` must be **ISSUED** in **us-east-1**.
4. **Cloudflare** — proxy **off** (gray cloud) for ACM validation and the
   `admin` CNAME.
5. **Google OAuth client** — add
   `https://<cognito-domain>/oauth2/idpresponse` to the authorized
   redirect URIs before the first Hosted UI sign-in.
6. **Docker / QEMU** — `AdminApiFn` bundles Pillow for `linux/arm64`;
   `deploy-backend.yml` and `cdk-diff.yml` register QEMU with
   `docker/setup-qemu-action`. For template-only synth set
   `CDK_SKIP_PYTHON_PIP=1`.

After the first deploy, verify `AdminFederatedEmailAllowlist` includes
every Google operator and nobody else: an unlisted Google account is
refused at sign-in (**This account is not authorized.**), and every listed
address is a full administrator. The variable is the complete admin list;
the Cognito **Users** page only shows accounts that have already signed in.

## 1. CDK Bootstrap and ACM

Bootstrap the stack region and `us-east-1` ([`setup.md`](./setup.md#3-cdk-bootstrap)).
Request a certificate for `admin.lx-software.com` in **us-east-1**, validate
by DNS in Cloudflare with proxy disabled, wait for **ISSUED** and record the
ARN as `ADMIN_ACM_CERT_ARN`.

## 2. Deploy admin infrastructure

Run **Deploy Backend** (or `cdk deploy` locally with the same parameters
from `backend/infrastructure/params/*.json`; see that folder's README for
the key list). Confirm both stacks finish:

- `lxsoftware` — Cognito, DynamoDB, S3 assets, HTTP API, SES inbound rule
  set, Executive Board schedules
- `lxsoftware-admin-web` — S3 origin + CloudFront for the SPA

Copy the CloudFormation outputs (user pool, client, hosted UI domain, API
URL, CloudFront domain) into the GitHub environment variables used by
**Deploy Admin Web**.

If a deploy leaves `lxsoftware` in `UPDATE_ROLLBACK_FAILED` on a resource
with no physical counterpart (a stage that references routes created in
the same changeset, or the `SiutindeiDataApiReceivablesSchema*` custom
resource), continue the rollback skipping that logical id, then redeploy:

```bash
aws cloudformation continue-update-rollback \
  --stack-name lxsoftware --resources-to-skip <logical-id>
```

### Admin web bucket policy

`lxsoftware-admin-web` used to declare two `AWS::S3::BucketPolicy` resources
on the SPA origin bucket: the bucket's own policy (`enforceSSL` deny plus the
OAC read grant CDK adds for `S3BucketOrigin.withOriginAccessControl`) and a
hand-written `AdminWebBucketPolicy` that repeated the OAC grant. S3 keeps one
policy per bucket, so whichever CloudFormation applied last was live and the
other's statements were dropped. The CDK synth reported it as
`Primary identifiers {'Bucket': …} should have unique values`.

The migration is two deploys because deleting an `AWS::S3::BucketPolicy`
calls `DeleteBucketPolicy`, which would wipe the merged policy in the same
run:

1. Current `main`: the bucket's own policy names its OAC statement
   (`AllowCloudFrontServicePrincipalReadOnly`), is applied after the legacy
   resource, and the legacy `AdminWebBucketPolicy` has `DeletionPolicy:
   Retain`. After this deploy the live policy is the complete one. Confirm
   with `aws s3api get-bucket-policy --bucket <origin bucket>`: both the
   `aws:SecureTransport` deny and the CloudFront allow must be present.
2. Follow-up: delete the `legacyBucketPolicy` block (and the `DependsOn`) in
   `backend/infrastructure/lib/lxsoftware-admin-web-stack.ts`, update
   `test/lxsoftware-admin-web-stack.test.ts` to assert a single policy, and
   deploy. Retain means CloudFormation drops the resource from the stack
   without an API call, so the live policy is untouched and the synth
   warning disappears.

## 3. DNS and Google IdP

Create a **CNAME** from `admin.lx-software.com` to the CloudFront domain
(Cloudflare proxy off). Add the Cognito `idpresponse` URL to the Google
OAuth client. Do **not** edit Cognito app client callback URLs in the
console; CDK owns them from `AdminWebDomainName` and overwrites drift.

## 4. Deploy the admin SPA

Run **Deploy Admin Web** (on `main` when `apps/admin_web/**` or
`scripts/deploy/deploy-admin-www.sh` change, or manually). It builds
`apps/admin_web` with production `VITE_*` values, then
`scripts/deploy/deploy-admin-www.sh` uploads hashed `dist/assets/**` with a
long immutable cache, uploads `index.html` with `no-cache` and invalidates
CloudFront. The script reads `AdminWebBucketName` and
`AdminWebDistributionId` from the `lxsoftware-admin-web` outputs (override
with `ADMIN_WEB_STACK_NAME`).

## 5. Smoke tests

1. Open `https://admin.lx-software.com`; the login screen appears.
2. **Sign in with Google** (allow-listed email) or **Sign in with email**
   for the bootstrap user; complete Hosted UI / MFA.
3. Tokens exist in `sessionStorage`.
4. `GET /health` without auth → **200**; `GET /me` with
   `Authorization: Bearer <id_token>` → **200**.
5. Presigned **POST** upload and confirm; a DynamoDB row exists under
   `ASSET#…` / `META`.
6. Sign out, reload, and land on the login screen again.
7. **Sign in with Google** using an address that is **not** on
   `ADMIN_FEDERATED_EMAIL_ALLOWLIST`: Cognito bounces back to the login
   screen with **This account is not authorized.**, `sessionStorage` holds
   no tokens, and the Cognito **Users** page shows no new user.

## Auditing admin sign-ins

Every sign-in, token refresh and first federated sign-up passes through the
`PreTokenGenerationFn` Lambda, which logs one JSON line per decision. To see
who signed in and why they were allowed, run this CloudWatch Logs Insights
query against that function's log group (named
`lxsoftware-AuthPreTokenGenerationFnLogGroup…`; it is the
`AuthPreTokenGenerationFnLogGroup` resource of the `lxsoftware` stack):

```
fields @timestamp, email, username, trigger_source, decision, matched_admin,
       in_admin_group, allowlist_size
| filter tag = "admin_auth_gate" or tag = "pre_token_generation"
| sort @timestamp desc
```

`decision` is `grant_admin` (email on the allow-list), `keep_admin_group`
(native bootstrap administrator), `deny_token`, `deny_sign_up`,
`allow_sign_up` or `allow_admin_create_user`. Lines tagged
`pre_token_generation` are from before the fail-closed gate; there
`matched_admin: true` is the only way the token carried `admin`. A
`matched_admin: true` line for an address you did not expect means that
address is in `ADMIN_FEDERATED_EMAIL_ALLOWLIST` — remove it from the GitHub
environment variable and run **Deploy Backend**; the next token refresh for
that account is refused. The HTTP API access log (`claimEmail`,
`claimGroups`) and `admin_auth_denied` lines on `AdminApiFn` show the same
identity on the API side.

## Local UI without a stack

`npm run dev` needs a real Cognito pool and API. `npm run dev:mock` (from
`apps/admin_web`) loads `.env.mock`, signs in with a fake admin token and
serves `src/lib/mock/fixtures.ts`. Never set `VITE_ADMIN_MOCK=1` on a
production build.

## Read-only debugging identity

Investigators (including Cursor cloud agents) authenticate as the IAM user
`cursor-cloud-agent`. It has no managed policies; attach the inline policy
`lxsoftware-cloud-agent-read` to let it read S3 access logs, assets-bucket
metadata (never the statements themselves) and query the admin tables:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAssetsAccessLogs",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetObject"],
      "Resource": [
        "arn:aws:s3:::lxsoftware-admin-assets-logs-588024549699-ap-southeast-1",
        "arn:aws:s3:::lxsoftware-admin-assets-logs-588024549699-ap-southeast-1/*"
      ]
    },
    {
      "Sid": "ReadAssetsBucketMetadata",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketCORS", "s3:GetBucketPolicy", "s3:GetBucketLocation",
        "s3:GetBucketVersioning", "s3:GetBucketLogging", "s3:GetEncryptionConfiguration"
      ],
      "Resource": ["arn:aws:s3:::lxsoftware-admin-assets-588024549699-ap-southeast-1"]
    },
    {
      "Sid": "ReadAdminTables",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:DescribeTable"],
      "Resource": [
        "arn:aws:dynamodb:ap-southeast-1:588024549699:table/lxsoftware-admin-audit-log",
        "arn:aws:dynamodb:ap-southeast-1:588024549699:table/lxsoftware-admin-records"
      ]
    },
    {
      "Sid": "ReadBoardSesIdentities",
      "Effect": "Allow",
      "Action": ["ses:GetEmailIdentity"],
      "Resource": [
        "arn:aws:ses:ap-southeast-1:588024549699:identity/siutindei.com",
        "arn:aws:ses:ap-southeast-1:588024549699:identity/partners.siutindei.com"
      ]
    },
    {
      "Sid": "RetryBoardSesDkim",
      "Effect": "Allow",
      "Action": ["ses:PutEmailIdentityDkimAttributes", "ses:PutEmailIdentityMailFromAttributes"],
      "Resource": [
        "arn:aws:ses:ap-southeast-1:588024549699:identity/siutindei.com",
        "arn:aws:ses:ap-southeast-1:588024549699:identity/partners.siutindei.com"
      ]
    }
  ]
}
```

```bash
aws iam put-user-policy --user-name cursor-cloud-agent \
  --policy-name lxsoftware-cloud-agent-read --policy-document file://policy.json
# remove:
aws iam delete-user-policy --user-name cursor-cloud-agent --policy-name lxsoftware-cloud-agent-read
```

`ReadBoardSesIdentities` lets a Health `AWS_SES_DKIM_PENDING_TO_FAILED` be
diagnosed; `RetryBoardSesDkim` is only needed for
`scripts/sync-ses-sending-dns.py --retry` and can be left out.
No `s3:GetObject` on the assets bucket, no `dynamodb:Scan`, no KMS
(AWS-managed keys). CloudWatch Logs read access is a separate policy on the
user. S3 access logs under `assets-data-bucket/` follow the standard S3 log
format; for presigned-upload failures look at `Operation`
(`REST.POST.OBJECT`), `HTTP status` (204 = success) and `Error Code`
(`AccessDenied`, `EntityTooLarge`, `MalformedPOSTRequest`).

## Public API keys

The HTTP API mirrors admin endpoints under `/public/*`, authenticated with
a static key in the `x-api-key` header instead of a Cognito JWT. Keys are
scoped; existing keys stay GET-only unless minted or updated with
`allowWrite`.

| Route | Mirrors |
|-------|---------|
| `GET /public/finance`, `/public/finance/quotes`, `/public/records`, `/public/fx/v2/rates` | the JWT GETs (finance stays GET-only) |
| `GET /public/siu-tin-dei/board` and `GET /public/siu-tin-dei/board/{proxy+}` | every JWT GET under `/siu-tin-dei/board` |
| `PUT` / `POST` / `DELETE /public/siu-tin-dei/board/{proxy+}` | the matching JWT write, when the key has `allowWrite` and `PublicApiWritesEnabled` is `true` |

Assets and parse-job endpoints are not mirrored. `/public/records`
excludes `BOARD#` rows. Legacy keys with only `scope=read` are finance-only.
The handler enforces scopes, the write flag and the kill switch
(`PUBLIC_READ_PATHS` / `PUBLIC_BOARD_PREFIX` in `dispatch.py`).

| Scope | Routes |
|-------|--------|
| `finance` | `/public/finance`, quotes, records, FX (GET only) |
| `siutindei-board-ops` | overview, staff, tasks, breakers, review, holds, ramp, tools, tool-calls; writes on those heads with `allowWrite` (except owner-only) |
| `siutindei-board-full` | every JWT GET under `/siu-tin-dei/board` except the PII heads; matching writes with `allowWrite` |
| `siutindei-pii` | unmasked mail; `allowList` / `digestTo` on overview and `GET /tools` `config.allowList`; `prospects`, `outreach`, `receivables` (with board-full); prospect import / PUT / merge |
| `siutindei-assets` | content creative presigned URLs (GET only) |

Writes need **`allowWrite`** on the key (`create --allow-write` or
`set-write`) **and** stack parameter **`PublicApiWritesEnabled=true`**
(CDK default `false`; production `true`). Denied writes return **403**
`{"message": "Forbidden", "reason": "writes_disabled"|"key_read_only"|"owner_only"|"scope"}`;
GET denials stay 404; unknown keys get API Gateway 401/403. Owner-only
even for a write key: `PUT settings` / `boundaries` / `tools`,
`POST approvals/{id}/approve|reject`, `code/promote`, `code/sync-staging`, `catalog/preview`, `catalog/import`,
`catalog/skip`, `catalog/requeue`, `catalog/reimport`,
`ramp/{classKey}/promote|pause`, `mail/selftest`, `DELETE chat/{persona}`,
`POST meetings/{id}/cancel`, `POST tasks/{id}/cancel`, `POST staff/tick`.

`PUT charter` / `brief` / `members` and `POST updates` / `tasks` / `chat`
feed persona and staff prompts, so a leaked write key can steer the board
within the existing propose / act / hold boundaries. Mint write keys with
`--allowed-cidrs` and a short `--expires-at`. `POST` is not idempotent; the
1 req/s write throttle limits accidental duplicates.

Without `siutindei-pii`, mail is aliased, allow-list / digest addresses
are stripped (a blank `settings.review.digestTo` on the public overview
means the key lacks the scope, not that it is unset) and `prospects` /
`outreach` / `receivables` return 404. Without `siutindei-assets`,
creative GETs return the object key only.

Keys expire in **90 days** unless `--expires-at` is set; optional
`--allowed-cidrs` fail closed when the client IP is missing. The
`PublicApiKeyAuthorizerFn` authorizer looks up the scrypt digest
(`pk = APIKEY#<digest>`, `sk = META`; only the digest is stored or
logged) and API Gateway caches verdicts **60 seconds** per key + source
IP, so revocation takes up to that long. Throttles: GET 2 req/s burst 10;
board writes 1 req/s burst 5.

Every **write** emails `settings.review.digestTo` from `hello@`. Successful
**reads** and denied known keys (revoked / expired / CIDR) coalesce to one
mail per 60 seconds per `(keyId, path class, source IP)`. Notification
needs `digestTo` and `SiutindeiBoardMailSendingEnabled`; the request
succeeds either way. Audit rows for key writes use `USER#apikey:<keyId>`.

Mint a Cloud Agent key as `finance,siutindei-board-ops`, not
`siutindei-board-full`, and without `--allow-write` unless it should
mutate board state.

```bash
# Mint (prints the key exactly once; keys look like lxpk_…)
python3 scripts/manage-public-api-keys.py create --label "reporting" \
  --scopes finance,siutindei-board-ops --expires-at 2027-01-01 \
  --allowed-cidrs 203.0.113.0/24

# Write-capable key (also flip lxsoftware:PublicApiWritesEnabled=true)
python3 scripts/manage-public-api-keys.py create --label "board-writer" \
  --scopes finance,siutindei-board-ops --allow-write

# Toggle write, list, revoke
python3 scripts/manage-public-api-keys.py set-write --key-id <keyId> --allow-write
python3 scripts/manage-public-api-keys.py set-write --key-id <keyId> --read-only
python3 scripts/manage-public-api-keys.py list
python3 scripts/manage-public-api-keys.py revoke --key-id <keyId>
```

**Via GitHub Actions:** **Manage Public API Keys**
(`.github/workflows/manage-api-keys.yml`) runs the same script through
`GitHubActionsRole` and the `production` environment. One-time setup: add
the `PUBLIC_API_KEY_GPG_PASSPHRASE` secret. Because the repository and its
logs are public, a minted key is emitted as a gpg-encrypted block in the
run summary (`gpg --decrypt key.asc`). `list` and `revoke` print to the
summary directly.

```bash
curl -H "x-api-key: lxpk_..." "$ADMIN_API_BASE_URL/public/finance"
curl -H "x-api-key: lxpk_..." "$ADMIN_API_BASE_URL/public/siu-tin-dei/board/breakers"
curl -X POST -H "x-api-key: lxpk_..." -H "Content-Type: application/json" \
  -d '{"assignee":"support","brief":"Triage inbound"}' \
  "$ADMIN_API_BASE_URL/public/siu-tin-dei/board/tasks"
```

## Statement PDF import

The admin SPA polls parse jobs for up to eight minutes
(`apps/admin_web/src/hooks/useParseStatement.ts`). That window matches the
`lxsoftware` stack Lambda timeout (300s), `OPENROUTER_TIMEOUT_SECONDS`
(210s), and `PARSE_JOB_STUCK_SECONDS` (420s) on `AdminApiFn`. Change those
together when extending OCR-heavy parsing.

## Enable Banking account sync

The **Banking** page links PSD2 bank accounts via
[Enable Banking](https://enablebanking.com) and refreshes `recordedValue`
on the finance **Accounts** sheet from live balances ("Sync now" plus a
daily EventBridge Scheduler schedule `lxsoftware-admin-bank-sync` at 05:30 HKT). Only balances are read.
Authentication is an RS256 JWT signed by the stack's asymmetric KMS key
(`alias/lxsoftware-admin/enable-banking`, `backend/lambda/admin/bank_sync.py`);
no private key material leaves KMS. The feature stays off until
`EnableBankingAppId` is set.

One-time setup:

1. Deploy the stack (the KMS key exists even while the feature is off).
2. Export the public key as PEM with admin AWS credentials:

   ```bash
   { echo "-----BEGIN PUBLIC KEY-----"
     aws kms get-public-key --key-id alias/lxsoftware-admin/enable-banking \
       --region ap-southeast-1 --query PublicKey --output text | fold -w 64
     echo "-----END PUBLIC KEY-----"; } > enable-banking.pem
   ```

3. Create an account at enablebanking.com, register a **production**
   application, paste the PEM as the certificate and add the redirect
   URLs `https://<AdminWebDomainName>/banking/callback` and
   `http://localhost:5173/banking/callback`.
4. Activate the application by linking your own accounts ("Activate by
   linking accounts"). Restricted applications can only read accounts you
   link, which is this use case.
5. Set the application id as `lxsoftware:EnableBankingAppId` in
   `backend/infrastructure/params/*.json` and redeploy. Blank keeps the
   feature off.

Then **Banking → Connect a bank**, map each linked account to an
Accounts-sheet record and run **Sync now**. Consents expire per PSD2 (90
days for most UK banks; the stack caps requests at 180 days); reconnect
from the same page.

## Executive Board

Design: [`../architecture/executive-board.md`](../architecture/executive-board.md).
Everything runs on `AdminApiFn` and the records table.

### Stack parameters

All optional, set in `backend/infrastructure/params/*.json`; an unknown
`lxsoftware:*` key fails `cdk deploy`. Naming: board-only knobs are
`SiutindeiBoard*`; Siu Tin Dei product resources are `Siutindei*`;
stack-wide knobs are unprefixed. Lambda env vars stay short
(`BOARD_*`, `OUTREACH_*`).

| Parameter | Purpose |
|-----------|---------|
| `OpenRouterApiKeySecretArn` | Existing secret (also used by statement parsing). Must be JSON with named keys `statement-parser`, `executive-board`, and `management` (a Management API key, not an inference key). |
| `SiutindeiBoardGitHubRepo` | `owner/name` to read (default `lx-software-ltd/siutindei`). |
| `SiutindeiBoardToolsEnabled` | `true` (default) / `false`. Deploy-time kill switch for every tool call. |
| `SiutindeiBoardStaffEnabled` | `false` (default) / `true`. Deploy-time kill switch for staff tasks; fail-closed (`1|true|yes|on`), set on `AdminApiFn` and `InboundStatementMailFn`. Production sets `true`; the Staff UI toggle is still required. |
| `PublicSiteOrigins` | CSV of extra browser origins on the HTTP API CORS list (admin origin always included). Needed by the public newsletter form. |
| `PublicApiBaseUrl` | Public base URL of the HTTP API for unsubscribe / confirm links. Blank uses the CloudFormation endpoint. |
| `SiutindeiBoardOutreachSendingDomain` / `SiutindeiBoardOutreachFromLocalPart` | Cold-outreach From (`partnerships@partners.siutindei.com`). Publish the three `SiutindeiOutreachDkimCnameN` outputs (or run `python3 scripts/sync-ses-sending-dns.py --domain partners.siutindei.com --retry`) plus MAIL FROM MX + TXT and DMARC before `outreach_send` will send. SES Easy DKIM that sits in `FAILED` does not re-check DNS on its own. |
| `SiutindeiBoardAwsStackPrefix` / `SiutindeiBoardAwsLambdaNames` | Alarm-name prefix (default `siutindei`) and CSV of siutindei Lambda names for `aws_lambda_health`. `aws_monthly_cost` filters by the `Project` tag and falls back to the account (`scope: account`). |
| `SiutindeiClusterArn` | Aurora cluster ARN. When set, CDK enables the HTTP Data API and applies `scripts/siutindei/receivables.sql`; required for `finance` / `product` tools. |
| `SiutindeiDbSecretArn` / `SiutindeiDbSecretName` | DB credentials secret (default name `lxsoftware-siutindei-database-credentials`; RDS-owned, do not recreate). |
| `SiutindeiBoardMetaVerifyToken` | Meta GET verify token (not a Secrets Manager secret). |
| `SiutindeiBoardMetaPageId` / `MetaIgUserId` / `MetaWaPhoneNumberId` / `MetaAdAccountId` / `MetaWabaId` | Graph ids for the `meta` tools. |
| `SiutindeiBoardAppStoreConnectAppId` / `AppStoreConnectVendorNumber` / `GooglePlayPackageName` | Store ids if not inside the secrets. The vendor number is needed for Apple download counts. |
| `SiutindeiBoardGa4PropertyIds` / `SiutindeiBoardGtmContainers` | CSV of GA4 properties; `account:container` pairs. |
| `SiutindeiBoardMailDomain` | Domain the board indexes (default `siutindei.com`). |
| `SiutindeiBoardMailSendingEnabled` | `false` (default) / `true`. Flip only after DKIM / SPF / DMARC are in the zone; creates the SES identity and send policy. The Lambda reads `BOARD_MAIL_SENDING_ENABLED` with the shared flag parser (`1`, `true`, `yes`, `on`). |
| `SiutindeiBoardChatModel` / `MeetingModel` / `DeepDiveModel` | Default OpenRouter slugs (`openai/gpt-4.1-mini`, `openai/gpt-4.1-mini`, `anthropic/claude-sonnet-4`); overridable in **Settings**. They are also sent as `models` fallbacks so a 429 on a cheap primary continues on the defaults. |
| `SiutindeiBoardCatalogImportEnabled` | `false` (CDK default) / `true`. Kill switch for `catalog_import`; preview and local dry-run work while it is off. Production is `true`. |
| `SiutindeiAdminApiBaseUrl` / `SiutindeiUserPoolId` / `SiutindeiBoardImporterClientId` / `SiutindeiBoardCatalogManagerId` | siutindei admin API base URL, Cognito user pool and importer app client for the catalog importer user, and the default manager id stamped on imported organisations. Blank until the product side exists. |

### Secrets

The `lxsoftware-admin-siutindei-board-*` secrets are **imported by name**
(they outlive stack rollbacks under `RemovalPolicy.RETAIN`); CDK grants
`AdminApiFn` read and never recreates them. Replace the dummy values in
Secrets Manager (`ap-southeast-1`):

| Secret | Replace with |
|--------|--------------|
| `…-board-github-token` | Fine-grained PAT scoped to `siutindei`: Contents **read and write**, Issues read/write, Pull requests **write**, Actions **read and write**, Metadata read, Security events read (for CISO findings). Public reads work without it. |
| `…-board-search-api-key` | Brave Search key; until then `research` falls back to OpenRouter `:online`. |
| `…-board-meta-token` / `…-board-meta-app-secret` | Meta System User long-lived token; app secret for `X-Hub-Signature-256`. |
| `…-board-app-store-connect-key` | JSON `{keyId, issuerId, appId, vendorNumber, privateKey}` (`.p8` body in `privateKey`). |
| `…-board-google-play-sa` | Play Console service-account JSON (+ `packageName` if not a parameter). |
| `…-board-google-analytics-sa` | Dedicated GA4 / GTM service-account JSON (not the Play key); may carry `propertyIds` / `gtmContainers`. |
| `…-board-google-places-key` | Google Places API (New) key. |
| `…-board-importer-credentials` | `{username, password}` of the siutindei Cognito `importer` service user (catalog import). |
| `…-board-link-signing-key` | Generated on first deploy; leave as is. |

The seven unused `lxsoftware-admin-*` connector placeholders (github read
token, search, meta token, meta app secret, app store, play, analytics)
are not in this stack. They were created with `RemovalPolicy.RETAIN`, so
dropping them from the template leaves the Secrets Manager values in the
account. Delete those orphans in the console when they are no longer
needed. `AdminApiFn` reads the imported `lxsoftware-admin-siutindei-board-*`
secrets instead.

### OpenRouter bill (shared account)

LX Software pays one OpenRouter invoice; sibling products share it by
tagging requests. Catalog:
[`contracts/openrouter-apps.json`](../../contracts/openrouter-apps.json).

| App id | Product | How spend is recorded |
|--------|---------|----------------------|
| `statement-parser` | Statement OCR (this repo) | Metered here |
| `executive-board` | Executive Board (this repo) | Metered here |
| `linkedin` | LinkedIn drafts on LX Software (this repo) | Metered here |
| `evolvesprouts` | [lx-software-ltd/evolvesprouts](https://github.com/lx-software-ltd/evolvesprouts) | Pulled hourly (`ingestUsage`) |
| `siutindei` | [lx-software-ltd/siutindei](https://github.com/lx-software-ltd/siutindei) | Pulled hourly once `lxsoftware:siutindei` exists |

Each request sets `HTTP-Referer` / `X-OpenRouter-Title` from the catalog,
`X-OpenRouter-App-Visibility: hidden` and a stable `user`
`{app-id}:{owner-or-workload}` (no PII). Mint one named key per app
(`lxsoftware:{app-id}`):

```bash
OPENROUTER_MANAGEMENT_API_KEY=sk-or-... python3 scripts/mint-openrouter-app-keys.py
```

or **Actions → Mint OpenRouter App Keys** (secrets
`OPENROUTER_MANAGEMENT_API_KEY` and `PUBLIC_API_KEY_GPG_PASSPHRASE`;
leave **Preview only** checked to list existing names, uncheck to mint,
decrypt the armored block with `gpg --decrypt keys.asc`). Create the
management key at
[openrouter.ai/settings/management-keys](https://openrouter.ai/settings/management-keys);
it stays in GitHub, not in AWS.

This admin's secret `lxsoftware-admin-openrouter-api-secret-*` must be
JSON — parser and board calls fail without their named field, and the
sibling pull stays at USD 0.00 without `management`:

```json
{
  "statement-parser": "sk-or-v1-parser",
  "executive-board": "sk-or-v1-board",
  "linkedin": "sk-or-v1-linkedin",
  "management": "sk-or-v1-management"
}
```

`management` is a [Management API key](https://openrouter.ai/settings/management-keys),
not an inference key. Leave it off the statement-parser and executive-board
fields. An hourly schedule (`lxsoftware-admin-openrouter-usage-pull`, no
board key) lists every key on the account. It calls
`GET /api/v1/activity` once for the whole account and
`GET /api/v1/activity?api_key_hash=` once per key that has usage. Catalog
keys are stored under their app id. Any other key name is its own line.
`Other` is the account total minus every key, which is where OpenRouter
Chat lands. A completed day OpenRouter has not aggregated yet is stored
as USD 0.00 and replaced on the next pull that includes it.
The current UTC day uses the key's `usage_daily` and has no call count until
Activity includes that day. A failed request leaves the previously saved
days in place and marks the bill `partial` or `http_error`. Days older
than 30 stay as last saved, so history builds from the first successful pull.

Evolve Sprouts stores `lxsoftware:evolvesprouts` in its own secret (plain
string) and tags requests with `https://evolvesprouts.com` / `Evolve
Sprouts` / `evolvesprouts:{workload}`. When siutindei gets a client, mint
`lxsoftware:siutindei` and tag with `https://siutindei.com` / `Siu Tin
Dei` / `siutindei:{workload}`. Until that named key exists, the dashboard
shows Siu Tin Dei at USD 0.00 with no spend on the key. Extra keys and
`Other` appear on the card only in a month that has spend.

**LX Software → Dashboard → OpenRouter** (`GET /openrouter/usage`) rolls up
UTC spend by app, month-to-date by default with the previous 12 months on
the dropdown (`?from=YYYY-MM-DD&to=YYYY-MM-DD`). Sibling lines, extra key
names, and Other are the pulled Activity totals. Parser and board lines
are still metered here, so a gap between that meter and the key's own
Activity is not added to Other.

### LinkedIn drafts

LX Software → **LinkedIn** (`/lx-software?tab=linkedin`) stores a personal
posting queue. Rows use the `LINKEDIN#` prefix and stay out of `/records`.
Drafts are written as a senior architect with the `lxsoftware:linkedin`
key. The company name stays blocked in every draft. Draft calls send
`reasoning: {enabled: false}`. A model that still thinks fails the batch
(`linkedin_draft_parse_failed` carries `finish_reason`). `RECOMMENDED_VOICE`
is mirrored as `RECOMMENDED_LINKEDIN_VOICE` in `linkedinModel.ts`; keep
both texts identical and under 1000 characters. The Image API has no
`data_collection: deny`. Character headshots are the `linkedin_character`
job.
Generation uses the `linkedin` OpenRouter key above and books each call on the OpenRouter usage ledger.
Settings → Drafts can pin an OpenRouter model slug next to Notify; an empty field uses `OpenRouterModel`.
Voice is the tone the model must follow on new drafts and on guardrail rewrites. It overrides the default tone (first person, short lines, a closing question). Substance rules (written as I, never a company we — one `we` is allowed for a real conversation; one real situation told in the order it happened, with its system, constraint and figures; no sensationalism, buzzwords or emoji; no opening question, no moral first, no `Agree?`) and safety rules (hook length, employer, availability, pitch, blocked phrases) stay in force. **Use recommended voice** fills the field with `RECOMMENDED_VOICE` from `linkedin_store.py`, which is also the default: a plain first line specific to the story, the story in order, named constraints and figures, plain dashes, dry self-deprecation, an admitted gap, and a different way in and out for every post. The voice quotes no catchphrase, because the model copies any phrase it is given. Leave Voice blank to use the default tone only. **Example post** (`styleExample`, up to 3000 characters) is a post in the owner's own words that the system prompt shows for its register only (how plain, how much admitted, how little sold); its structure, opening formula, closing move and phrases are not to be reused. The default is `STYLE_EXAMPLE` in `linkedin_store.py`; replace it with a newer post or clear it to send no example. Within a batch each draft gets its own shape from `linkedin_draft.OPENINGS` × `CLOSINGS` × `LENGTHS` (rotating from the number of existing posts, so successive weeks differ), and the user message lists the openings and closing lines of the example, the last 12 posts, and the drafts already written. A draft that contains an emoji, a phrase from `SLOP_PHRASES` (`linkedin_draft.py`), more than one `we` / `our`, or that opens with the same three words, closes with the same four words, or shares any seven-word phrase with one of those posts (`repeat_findings`) gets the one rewrite pass, which repeats the shape. Draft temperature is 0.9. When Ideas has no `new` rows, each draft is written from a seed in `backend/lambda/admin/linkedin_seeds.py` — first-person situations from problems this codebase solved, with no company or product names — and the post stores `seedId` so a seed is not reused while others remain. Each draft also stores `generation.voiceHash` for the voice that produced it.

When **Draw a black-and-white comic for each draft** is on (the default), the same call also returns `imageScene`, `imageExpression`, and `imageCaption`, and a separate worker (`linkedin_image`) asks OpenRouter's Image API (`POST /api/v1/images`) for one panel. The default model is `bytedance-seed/seedream-4.5`; `qwen/qwen-image-3` is the alternative named in Settings, and the owner can replace the slug. The Image API call sets resolution `2K` and waits up to `LINKEDIN_IMAGE_TIMEOUT_SECONDS` (default 200; Seedream 4.5 at 2K with a reference sheet answers in 70–120 s, and the old 90 s default failed most draws with `OpenRouter request timed out: The read operation timed out` in `linkedin_image_failed`). A model slug that OpenRouter does not know fails the draw with a 404 in the same log line; Settings only checks the slug shape. Seedream 4.5 rejects `1K` because those sizes are under its 3,686,400 pixel minimum, so a post drawing and the four character headshots never start at that tier. Pillow turns the result grayscale and fits the Settings shape (square 1200×1200, portrait 1080×1350, wide 1200×675). The caption is drawn inside the bottom of that picture, with no quotation marks, using `fonts/NotoSerif-Italic.ttf`. The same line is the LinkedIn alt text. `imageExpression` is two to five words for the face in that scene. All three are written from the post: the scene is a light gag cartoon of the author living the moment the post is about (head-scratching at a monitor full of scribbled nonsense, a wall of sticky notes), the expression is the face in that moment, and the caption always ends with a mark (`finish_caption`: a full stop unless the line ends with `?` or `!`). An owner-written post is queued for a picture on save; the worker (`picture_text`) asks the draft model for any field that is blank (`picture_brief`, `LINKEDIN_BRIEF_TIMEOUT_SECONDS` 25) and falls back to a plain desk scene when that call fails (`linkedin_picture_brief_failed`). **New scene, expression and caption** is `POST /lx-software/linkedin/posts/{id}/image/brief` (202): it queues `internal: linkedin_image_brief`, which rewrites all three from the post, books the cost, and does not draw; a ready picture stays until **Redraw picture**. The model call never runs inside the HTTP request, because API Gateway cuts an integration at 30 s and Safari reports that cut as “Load failed”. `image.brief.status` is `pending` / `done` / `failed`; the SPA polls while pending, a pending rewrite older than `BRIEF_PENDING_SECONDS` (120) is shown as failed, and a second click or a redraw during a pending rewrite is a 409. A repeated room is allowed across drafts; only repeated scene wording is sent back for a rewrite. The character sheet is a caricature with a neutral face; redraw it after changing the style or the description, because later pictures copy the sheet you pick. The photo is uploaded once under **Character**, used to draw four headshots, and can be deleted after one is chosen. Later pictures send that sheet from the private assets bucket (`linkedin/character/`), not the photo. The photo and the sheet are not stored in the repo, DynamoDB, or fixtures. With pictures turned off, the draft prompt does not ask for a scene or caption. A picture that has never been ready is posted as text when the slot arrives, and the row records `imageNote`. A redraw keeps the previous ready picture, and its alt text, until the new panel is saved, so a pending or failed redraw still publishes that picture. Picture spend shares `maxUsdPerMonth`: each image call reserves $0.05 before the request, and the actual cost is booked on the OpenRouter ledger as `linkedin` / `image` only after the panel is saved. `LINKEDIN_IMAGE_TIMEOUT_SECONDS` defaults to 90. Character headshots stop inside 240s so they finish before the 300s Lambda timeout, and a character job still running after six minutes is marked failed on the next read. Candidate ids are only `c1`–`c4`. **Redraw picture** is `POST /lx-software/linkedin/posts/{id}/image/regenerate`.

| Parameter | Default | Production |
|-----------|---------|------------|
| `LxSoftwareLinkedinEnabled` | `false` | `true` |
| `LxSoftwareLinkedinPublishEnabled` | `false` | `true` |

The app credentials live in Secrets Manager `lxsoftware-admin-linkedin-app`
(`clientId`, `clientSecret`). The stack creates that secret with
`clientId` set to `replace-me`. Replace both values in the console. The
redirect URL to register on the LinkedIn app is
`https://admin.lx-software.com/lx-software/linkedin/callback`.
That URL is the deployed admin origin (`ADMIN_WEB_ORIGIN`), so a local dev
server cannot finish the LinkedIn redirect unless its origin is the one
registered on the app.
Enable Sign In with LinkedIn using OpenID Connect and Share on LinkedIn, and
request `openid profile w_member_social`. Company pages are optional: Settings
→ **Include company pages** also requests
`w_organization_social r_organization_social rw_organization_admin`, which
need Community Management approval. An unapproved scope fails the whole
consent screen, so leave company pages off until that product is approved.
`rw_organization_admin` lists the pages you administer. **Refresh pages**
reloads that list without reconnecting. Page impressions use the same
approval. Member post analytics are not requested. A denied reaction read is
stored and not retried; page impressions are read only for posts that went
out as a page.

With the first switch on, Sunday 18:00 HKT
(`lxsoftware-admin-linkedin-plan`) drafts the configured batch, and a
15-minute schedule (`lxsoftware-admin-linkedin-publish`) runs. The rate
starts from deploy time, so an 08:30 HKT slot is posted on the first tick
after 08:30, within about 15 minutes. Both schedules are created only when
`LxSoftwareLinkedinEnabled` is `true`. Production sets that, so a deploy
creates the Sunday plan and the 15-minute worker. Connect from **LinkedIn → Settings**. The default
destination is your profile. Choose the company page there when you want
posts to go out as the page. Settings shows when the access expires; a
standard app has no refresh token, so connect again before that time.
When `LxSoftwareLinkedinPublishEnabled` is also `true` and a member is
connected, one due approved draft is posted per tick through the Posts API,
and only when the slot is less than three hours old. Older approved slots
stay for the share box. The first comment is added, and a ready PNG or JPEG
attached on the draft is uploaded with it (the caption, without quotes, is
the alt text). A picture that has never been ready does not hold
the slot: the post goes out as text. A redraw that is still pending or that
failed publishes the previous ready picture instead. A comment failure leaves the post
published. An image upload or API failure counts as a failed attempt (three tries,
then a second email that posting has stopped). A missing connection or an
expired token does not use up those tries. Reactions and comments refresh
for page and profile posts from the last 30 days, at most every six hours.
While the publish switch is off, or LinkedIn is not connected, the share
box and **Mark posted** stay the way to publish.
Add any employer name under Settings → extra phrases; do not put it in source.

### AWS bill (shared account)

One AWS invoice for account `588024549699`. Cost allocation tags
**Organization** and **Project** are active. Catalog:
[`contracts/aws-billing.json`](../../contracts/aws-billing.json); first
matching row wins:

| Company | `Organization` | `Project` |
|---------|----------------|-----------|
| Siu Tin Dei | `LX Software` | `Siu Tin Dei` |
| Evolve Sprouts | `Evolve Sprouts` | any |
| LX Software | `LX Software` | anything else |

Untagged resources land in **Unallocated**. AWS's invoice PDF is one
account total; the internal split is **LX Software → Dashboard → AWS**
(`GET /aws/usage`, last complete UTC month by default) and **Download
allocation PDF** (`GET /aws/usage.pdf`). Keep tagging new stacks with
`cdk.Tags` and never rotate the tag keys (Cost Explorer only groups by
activated tags; a key change orphans history).

### Schedules and invoke permissions

Schedules are EventBridge Scheduler with an IAM-role target and are listed
in the architecture doc §12. API Gateway holds one API-wide invoke
permission (`AdminApiInvoke`); when adding triggers for `AdminApiFn` use
Scheduler or an event source mapping, never per-route permissions or
`events.Rule` targets (20 KB resource-policy limit).

`AdminApiFn` has `RecursiveLoop = Allow` because it Event-invokes itself
(staff steps, meeting phases, workers, crawl pages). Alarm
`lxsoftware-admin-siutindei-admin-api-invocations` trips above 250
invocations in 5 minutes (observed stand-up peak ~145). A Health event
`AWS_LAMBDA_RUNAWAY_TERMINATION_NOTIFICATION` after deploy therefore means
a **different** function is looping.

Stand-ups at 06:00 / 18:00 HKT stay off until enabled in **Executive
Board → Settings**; a run is refused when the daily budget is exhausted or
another meeting is running.

### Emergency stop

In order of reach:

1. **Tools enabled** off in Settings, or `settings.staff.enabled` off (UI /
   `PUT settings`).
2. `lxsoftware:SiutindeiBoardStaffEnabled=false` and redeploy (with either
   staff flag off, `POST …/tasks` returns 409 `Staff is disabled`).
3. `lxsoftware:SiutindeiBoardToolsEnabled=false` and redeploy.
4. `lxsoftware:SiutindeiBoardMailSendingEnabled=false` and redeploy.

All leave the permission matrix intact.

### Staff seat rollout

Default-on seats: `support`, `provider-success`, `community-manager`,
`business-analyst`, `data-analyst`. `maxRunningTasks` default 3. Flip
others on from **Staff** (or `PUT /siu-tin-dei/board/staff/{id}`):

1. Set `settings.review.digestTo` (Settings card), deploy with
   `SiutindeiBoardStaffEnabled=true` and flip `settings.staff.enabled`.
   Default-on seats handle triage and the daily review.
2. **Market:** activate `market-analyst`; add about five watchlist entries.
   A `listingsIndex` watch (competitor listing index pages) may set a
   district; leave it blank when the URLs already carry an area slug
   (`/area/tung_chung`). Nav chrome is stripped from extracted names.
   The first Monday brief creates CPO `later` actions.
3. **Pipeline:** owner tasks first — DNS for `partners.siutindei.com`
   (SES DKIM CNAMEs, MAIL FROM MX + TXT, DMARC; `scripts/sync-ses-sending-dns.py --retry`
   after a DKIM `FAILED` Health event), Places key into the
   secret, SES production access, mailboxes `partnerships@`, `market@`,
   `news@`, `dmarc@` on Cloudflare (fan-out copies them automatically).
   Then activate `prospector`, approve the default sequences; first sends
   are 24 h holds and the daily cap rises only via the 7-day warm-up
   (max 100).
4. **Content:** activate `content-marketer` and `growth-specialist`; drop
   logo and colours into `backend/lambda/admin/brand/`; Meta App Review
   for `pages_manage_posts` / `instagram_content_publish` is an owner task.
   Raise **Concurrent tasks** to 6 after the first stable week.
5. **Newsletter / duties:** set `PublicSiteOrigins`; confirm
   `ADMIN_API_BASE_URL` on the production environment; activate
   `accountant` and `security-analyst`; then enable
   `settings.staff.dutiesEnabled` (Settings → Run scheduled seat duties).
6. **Engineering:** once the siutindei workflows exist (architecture doc,
   Appendix A) and the GitHub token has Actions / Pull requests / Contents
   write, activate `architect`, `engineer-1`, `engineer-2`, `product-dev`.
   `code_merge_staging` stays an Approval until taken off
   `always_propose`.
7. After two weeks, act on ramp promotions from the daily review.

**Staff → Run staff tick now** queues the same work as the 5-minute
schedule and returns `200 {queued}`; the SPA retries a dropped fetch once.

### Smoke test after deploy

Open the tab, save a company vision / mission, edit one member's mandate,
chat with the CEO (reply within ~30 s), **Run stand-up** and confirm
minutes and actions. Tools: ask the CTO "what is open on GitHub about
bookings?" (reply lists `Searched GitHub issues`); ask the CPO to open an
issue (lands in **Approvals**); ask the CFO "what did AWS cost last month?"
and the CISO "any HIGH findings?" (cached reads after the hourly refresh).
Mail: open **Mail**, toggle **Board's view** (addresses become
`contact#N`), ask the CMO "what's unread?". Receivables: with
`SiutindeiClusterArn` set, open **Receivables** and ask the CFO to draft
the first listing plan.

### Board receivables (Aurora Data API)

1. Set `lxsoftware:SiutindeiClusterArn` to the `lxsoftware-siutindei-db-cluster`
   ARN and redeploy. The stack enables the HTTP Data API and applies
   `scripts/siutindei/receivables.sql`; the secret defaults to
   `lxsoftware-siutindei-database-credentials`.
2. Scheduler `lxsoftware-admin-siutindei-data-api-ensure` (15 min)
   re-enables the endpoint and reapplies the script if a siutindei deploy
   drifts it; the product CDK should still set `enableDataApi: true`. A SQL
   error on the deploy custom resource ACKs SUCCESS so `AdminApiFn` keeps
   its env; the scheduler retries. The custom resource has a 15-minute
   `ServiceTimeout`.
3. `finance_send_invoice` / `finance_send_reminder` mail from
   `billing@siutindei.com` and stay in **Approvals** unless the payer is on
   the allow-list. Bank ingest waits on the HK account; use
   `finance_record_manual_payment` until then.
4. `python3 scripts/siutindei/smoke_data_api.py --cluster-arn … --secret-arn …`
   exercises every view and a rolled-back insert with the same typed
   parameters `AdminApiFn` uses (`--dry-run` prints the statements).

### Evolve Sprouts finance (Aurora Data API)

The Evolve Sprouts page is the statement book `evolveSprouts`. It is
read-only: expenses and gains are mirrored, and `PUT` or statement import
on that book returns 403. LX Software and Siu Tin Dei stay editable.

1. On the Evolve Sprouts database, set `enableDataApi: true` on that
   product stack and create a **read-only** database user with a
   password login and `SELECT` on `customer_payments`, `expenses`,
   `organizations` (vendor names), and `customer_invoices`. Do not reuse
   `evolvesprouts_app`: it has `rds_iam`, which blocks the password login
   the Data API uses. This stack never writes that database and does not
   apply SQL there. The secret's
   KMS key policy must allow `AdminApiFn` to decrypt via Secrets Manager
   (the default account-root key policy is enough).
2. Set `lxsoftware:EvolvesproutsClusterArn` and either
   `EvolvesproutsDbSecretArn` or `EvolvesproutsDbSecretName` to the
   **read-only** user. Both secret fields default to blank — do not use
   the cluster master name `evolvesprouts-database-credentials`.
   `HasEvolvesproutsDataApi` is the cluster ARN **and** a secret. Redeploy.
   `AdminApiFn` receives `EVOLVESPROUTS_CLUSTER_ARN` and
   `EVOLVESPROUTS_DB_SECRET_ARN` (a secret name or ARN). The database name
   defaults to `evolvesprouts`.
   IAM is `rds-data:ExecuteStatement` on the cluster,
   `secretsmanager:GetSecretValue` on the resolved secret, and
   `kms:Decrypt` via Secrets Manager (`AdminEvolvesproutsDataApiPolicy`).
   Decrypt stays on `*` because `DescribeSecret` returns an alias for the
   AWS-managed key. A customer-managed key still needs this role in its
   key policy.
3. Scheduler `lxsoftware-admin-evolvesprouts-data-api-ensure` (15 min)
   re-enables the HTTP endpoint only (`applySql` false). It exists only
   when the cluster and secret are set. The product stack should still
   set `enableDataApi: true`.
4. Scheduler `lxsoftware-admin-evolvesprouts-finance-mirror` runs at 00:45
   HKT when the Data API is configured. **Sync now** queues the same
   mirror (`POST /evolve-sprouts/sync` returns `{queued}`, internal event
   `evolvesprouts_finance_mirror`; the page polls
   `GET /evolve-sprouts/summary`). The page load reads the last snapshot
   and does not query Aurora.
5. Mirrored lines replace the previous mirror and leave any other lines
   alone. Issued `customer_invoices` become income `es-inv-*` (Gains).
   Succeeded refunds become expenditure `es-ref-*`, and expenses
   with status `submitted` or `paid` become expenditure `es-exp-*`. Draft,
   voided, and amended expenses are omitted. Issued invoices with
   `balance_due > 0` also stay on the summary (outstanding by currency,
   open-invoice count). Each row keeps its own currency. Invoice and
   expense net is `subtotal`, VAT is `tax` / `tax_total`, and gross is
   `total`. Dates follow the Evolve Sprouts Finance **Tax** panel, which
   classifies revenue and expenses by document date: `invoice_date`, and
   for an issued invoice with no `invoice_date` (issued before
   evolvesprouts migration `0057` added the column, 2 May 2026) the HKT day
   of `issued_at`. A backdated invoice therefore sits in its own fiscal
   year even when the record was created later; the statement table orders
   by that date, not by `created_at` (the Client Invoices list order).
   Lines do not carry `sortUtc`; a stored line that still has it is
   rewritten once.
   Refunds use `succeeded_at`. Calendar days are Asia/Hong_Kong,
   stored as that day at 00:00 UTC. Codes outside GBP, HKD, USD, EUR, CNY,
   SGD, AED are skipped and counted separately from rows missing an
   amount, currency, or date. Expense descriptions are the vendor name and
   invoice number. Gain descriptions are the invoice number and bill-to
   name. Refund descriptions use the row id only. Previous `es-pay-*`
   payment income is removed on the next sync. A book that exceeds the
   DynamoDB item limit (or 5,000 lines) fails the sync with a clear error
   instead of a 500.

### Catalog import

Tool `catalog` (`catalog_preview`, `catalog_dry_run`, `catalog_import`;
design in the architecture doc §6.4) turns an accepted catalog
micro-batch sheet into siutindei importer JSON and calls the product admin
API as a dedicated Cognito **importer** user. This stack never writes
Aurora and no LLM runs in that path. `catalog_import` is always an
Approval (`always_propose`, class `catalog_import`); owner
`POST /siu-tin-dei/board/catalog/preview`, `POST …/catalog/import`,
`POST …/catalog/skip`, `POST …/catalog/requeue` and
`POST …/catalog/reimport` are JWT-only
(`owner_only` on the public API). Bulk sources live on **Progress**
(`GET …/catalog/sources`, `POST …/catalog/bulk/{source}/preview|import`
and `POST …/catalog/discovery/run` return `200 {queued}` and run in the
background like **Run staff tick now**; Progress shows the job phase and
disables Preview/Import for that source while it is `queued` or
`running`. `GET …/catalog/candidates` filters by `source` / `district` /
`q` and pages with `cursor`; owner `POST …/catalog/candidates/bulk`
approves, rejects, or closes the matching `new` rows (Progress **Close
leftover competitors** uses `decision=close`, `source=competitor`,
`missingPlaceId=true`, and `before` = 7 days ago — the same filter as
the discovery tick).
Discovery refreshes LCSD / EDB / SWD on Monday **or** when a cache is
missing/empty, ingests a source in-process
when it has ≤ 500 rows, and queues 500-row `ingest` jobs when it is
larger (EDB today; any later feed over that size uses the same path).
Owner Preview / Import of a large source run those chunks first.
Bulk Import waits 20 s per siutindei hop (a 50-org batch has taken 8.5 s).
A read timeout on one batch leaves that batch `approved` and continues
the rest; click Import again for leftovers. Sync sheet **Import now**
still uses the 8 s cap so API Gateway cannot 504.
Open-data rows gzip to `board/{BOARD_KEY}/opendata/{name}.json.gz`;
Dynamo only stores a pointer so a large file cannot exceed the 400 KB
item limit. An empty official fetch (no `fetchedAt`, or zero rows) writes review gap `opendata-{source}`.
A failed enqueue of the next ingest chunk writes `phase: error` so Preview/Import unlock.
A failed job writes `phase: error` instead of staying
`running`. Per-row candidate approve/reject stay
synchronous). A second
import of the same task returns 409 unless the body has `{"force": true}`.
`settings.catalog.microBatchEnabled` (default on) pauses the 3-per-district
duty while bulk import fills toward 1000 live listings.

Accepted catalog sheets leave **Review** as `awaiting_import` (SPA
**In progress**, **To import** tag) after a siutindei dry-run. Name collisions
(`updated` rows) and rejected rows park at `needs_owner`. The staff
tick backfills older delivered-but-unimported sheets and re-validates
`pending` sheets at most once an hour (using `lastValidatedAt`, including
local-only sheets). It also re-validates a parked `invalid` / `rejected`
sheet whose last dry-run reached siutindei or recorded a `remoteError`
(same 1 h spacing, three attempts). A transient siutindei error keeps
the sheet parked and does not spend an attempt. After three still-parked
retries the sheet stays on **Attention** with an open question; the
daily review Catalog line reports `revalidateExhausted`. Owner Preview
(including local-only `{"remote": false}`) / Requeue reset the counter.
The task drawer shows `Automatic re-validation: N/3`. When
`settings.catalog.autoImport` is on plus
the kill switch, it schedules an internal `catalog_import` hold (default
2 h; a stored `holds.catalog_import` of 0 is treated as 2 unless
`holdOverrides.catalog_import` is set). Auto bulk-import of a source
with ≥ 50 approved rows uses the same hold (`catalog_bulk_import`)
instead of queueing immediately; a promoted `holdOverrides.catalog_import`
of 0 still queues at once. The sweep never imports
immediately. **Import now** / **Skip** / **Queue again** drop the
scheduled hold so it cannot fail later as "already imported". The
catalog duty pauses when `catalog.maxAwaitingImport` (3) sheets are
waiting (`awaiting_import` plus parked import `needs_owner` rows), and
when more than `maxLowCompletenessDistricts` (3) imported districts sit
below 50% completeness (then `catalog-enrich` refills hours, price and
address on existing orgs). The gate uses the cached `v_board_catalog_health`
rows only and ignores districts with no score, so a cold cache does not
pause new districts. After deploy, live districts around 28% completeness
will pause `catalog-micro-batch` until enrich + import raise them. The
`content-marketer` seat has `research: read` and `web: read`; official
pages come from `research_fetch_page` (already offered) so a catalog
sheet must not `task_request_help` for `web` (`web_*` is GA4 only). Enrich
sheets that would update existing organisations stay on the import path
(`validated` / `awaiting_import`); they are not parked as collisions.
Accept of a catalog sheet skips the unverified-evidence hold (enrich
briefs mention Fill/send). ALS geocode failures of any kind fail open.
Owner **Re-import failed rows** (`POST …/catalog/reimport`) force-sends
an already-imported or partial sheet so omitted or failed activity rows
can create after the transform always emits an activity. Owner **Import
anyway** (`force:true`) on a delivered sheet is the same live path.
**Skip import** marks the sheet delivered without sending organisations
so the district stays claimed. A partial live import returns 200
`{ok:false,partial:true}` and retries send only the failed
organisations.

1. The siutindei importer group, #502 fields and `dry_run` are already
   on `main`. Create the service user in `importer` and put
   `{username, password}` in
   `lxsoftware-admin-siutindei-board-importer-credentials`.
2. Set `SiutindeiAdminApiBaseUrl`, `SiutindeiUserPoolId`,
   `SiutindeiBoardImporterClientId` and `SiutindeiBoardCatalogManagerId`
   (the `SiutindeiBoardImporterAuthPolicy` IAM statement is gated on a
   non-blank pool id). Production params already carry these.
3. **Tasks → In progress** → open a **To import** sheet → **Preview import**. That
   button calls siutindei with `dry_run` (the SPA sends `{remote:true}`;
   the API also defaults to remote). The footer shows **Previewing…**
   until the dry-run returns; the catalog panel then shows
   `remote dry-run` (or a `remoteError` if Cognito / the product API
   failed). A collision parks the sheet on **Attention** and hides
   **Import now** until **Import anyway**. Production has
   `SiutindeiBoardCatalogImportEnabled=true`, so **Import now** is live
   after Deploy Backend. Leave **Auto-import validated catalog sheets**
   off until a few manual imports look right.

### Board Meta (Page, Instagram, WhatsApp)

1. Create a Business-type app under the Siu Tin Dei Business Manager and
   a System User token (`pages_*`, `instagram_*`, `whatsapp_business_*`,
   `ads_read` / `ads_management`); replace the two Meta secrets.
2. Turn on **WhatsApp coexistence** so the owner's phone keeps working. If
   unavailable, the number moves fully to the Cloud API and the owner
   replies from **Approvals**.
3. Subscribe the app to `GET/POST https://<admin-api>/webhooks/meta/siutindei`
   (legacy `/webhooks/meta` still works).
4. Set the `SiutindeiBoardMeta*` ids; until then `meta` tools return "not
   configured".
5. WhatsApp `act` is only inside the 24-hour window and only to
   allow-listed E.164 numbers. Set **Meta ads spend caps** on the Tools
   card (defaults USD 10 / 50; clamped to 500 / 2 000).

### Board stores (App Store Connect + Google Play)

1. Fill `…-board-app-store-connect-key` (`keyId`, `issuerId`, `privateKey`;
   optional `appId` / `vendorNumber`) and `…-board-google-play-sa`.
2. Set the store parameters if not inside the secrets. Until one store is
   configured the `stores` tools return an error and the hourly refresh
   skips them.
3. `stores_reply_review`: CMO may **act**; `stores_draft_release_notes`
   always stays in **Approvals**.

### Board web (GA4 + GTM)

1. Create a GCP service account with `analytics.readonly` and
   `tagmanager.readonly`; grant Viewer on every GA4 property and GTM
   container; replace `…-board-google-analytics-sa`.
2. Set `SiutindeiBoardGa4PropertyIds` and `SiutindeiBoardGtmContainers`
   (or `propertyIds` / `gtmContainers` inside the secret).

### Shared inbound SES rule set

SES allows one active receipt rule set per region. `lxsoftware` owns
`lxsoftware-inbound-mail` and activates it on deploy:

| Recipient | Raw store | Processor |
|---|---|---|
| `32-hillmarton@inbound.lx-software.com` | `lxsoftware-admin-inbound-mail-…` / `inbound-raw/hillmarton/` | `InboundStatementMailFn` (house `hillmarton`) |
| `the-morrison@inbound.lx-software.com` | same / `inbound-raw/morrison/` | `InboundStatementMailFn` (house `morrison`) |
| `billing@inbound.lx-software.com` | same / `inbound-raw/lx-software/` | `InboundStatementMailFn` (book `lxSoftware`, expenses only) |
| `siutindei-board@inbound.lx-software.com` | same / `inbound-raw/siutindei/` | `board_mail.ingest_raw_object` |
| `invoices@inbound.evolvesprouts.com` | `evolvesprouts-assets-…` / `inbound-email/raw/` | Evolve Sprouts `InboundInvoiceEmailProcessor` |

`lx-software.com` MX stays on iCloud; forward the iCloud mailbox
`billing@lx-software.com` to `billing@inbound.lx-software.com` (output
`lxsoftware-InboundMailbox-lxSoftware`). Inbound PDFs are written under
`inbound/{owner}/{batch}/` with an `ASSET#` row so they show on **Assets**
even if parsing fails. Set `lxsoftware:StatementParseNotifyEmail` to get a
mail from `statements@inbound.lx-software.com` when a parse job succeeds or
fails.

The Evolve Sprouts stack still owns its bucket, topic, queue, role and
processor and must **not** call `SetActiveReceiptRuleSet` on its own set;
its bucket / role / KMS policies must allow the shared-set SourceArn
`…:receipt-rule-set/lxsoftware-inbound-mail:receipt-rule/evolvesprouts-inbound-invoice-email-rule`.

### Board mail (Cloudflare + SES)

**Read path (no DNS change on `siutindei.com`):**

1. Deploy `lxsoftware`; copy the `SiutindeiBoardMailInboundAddress` output.
2. In the `siutindei.com` Cloudflare zone, **Email Routing → Destination
   addresses**, add that address. The verification mail lands in the
   inbound S3 bucket; open it once and click the link.
3. **Workers & Pages → Create**, paste
   `scripts/cloudflare/siutindei-mail-fanout.js`; set `OWNER_DESTINATION`
   (owner's verified inbox) and `BOARD_DESTINATION` (step 1); optional
   `SKIP_SENDERS` (addresses or `@domain`, never copied).
4. **Routing rules → Catch-all**: **Send to a Worker**. Existing
   per-address rules win, so point them at the Worker too or delete them.

**Send path (after DKIM / SPF / DMARC):**

1. Set `lxsoftware:SiutindeiBoardMailSendingEnabled=true` and redeploy.
2. Add the three `SiutindeiBoardMailDkimCnameN` outputs as CNAMEs
   (Cloudflare proxy off), plus the custom MAIL FROM subdomain
   `mail.<SiutindeiBoardMailDomain>` (MX →
   `feedback-smtp.ap-southeast-1.amazonses.com`, TXT
   `v=spf1 include:amazonses.com ~all`). Or sync both in one shot:

   ```bash
   CLOUDFLARE_API_TOKEN=... python3 scripts/sync-ses-sending-dns.py \
     --domain siutindei.com --retry
   ```

   Without the MAIL FROM host, SES keeps `*.amazonses.com` as the envelope
   sender: DMARC SPF stays fail (unaligned) and only Easy DKIM saves the
   message. A single domain-DKIM miss then quarantines under `p=quarantine`.
3. Apex SPF: `v=spf1 include:_spf.mx.cloudflare.net include:amazonses.com ~all`.
4. `_dmarc` TXT: `v=DMARC1; p=quarantine; rua=mailto:dmarc@siutindei.com`
   (dedicated `dmarc@` mailbox, not `hello@`). Google / Yahoo aggregate
   reports to `dmarc@` (or a `Report domain:` subject on `hello@`) are
   archived at ingest and never count as unread. A later human reply on
   that thread returns it to the inbox; an Auto-Submitted bounce does not
   archive a live conversation. Aggregate reports are parsed at ingest
   (`board_dmarc.py`): the hourly refresh writes `dmarc:summary`, the
   daily review **DMARC** section shows reports received in the last 24 h,
   and a medium or high finding opens a security-analyst task when staff
   is on. An unknown source under 5 messages in 7 days stays informational.
   A summary older than 26 hours opens one stale-summary task instead of
   paging on the old findings. Defaults treat only `amazonses.com`, the mail
   domain and the outreach domain as our senders, and only when that domain
   authenticated or the header_from is one of those domains. Add
   `google.com` or `icloud.com` under **Executive Board → Settings → DMARC**
   (`settings.dmarc.knownSenderDomains`) if you send as `@siutindei.com` from
   Gmail or iCloud, or the first run flags that source. `security_dmarc_summary`
   reads the hourly cache and does not recompute it. The raw XML is kept
   gzipped under `board/{boardKey}/dmarc/` in the assets bucket.
5. **Settings → Tools & permissions → Recipient allow-list**
   (`@siutindei.com`, vendors, WhatsApp numbers).
6. **Mail → Send test email**: the header shows SES `GetEmailIdentity` /
   `GetAccount` status (cached 10 min), including the custom MAIL FROM
   domain and `MailFromDomainStatus`. One message goes from `hello@` to
   your sign-in address. A refusal shows the full SES error inline and as
   `board_mail_send_failed` in CloudWatch. Do this before asking a persona
   to reply. `SUCCESS` means SPF can align with the header From; `FAILED`
   or a missing domain leaves the envelope on `*.amazonses.com`.

**Outreach sending domain (`partners.siutindei.com`):**

The stack always creates `SiutindeiOutreachSendingIdentity`; its Easy DKIM
tokens differ from the apex `siutindei.com` board-mail tokens. After a CDK
deploy, or after SES moves DKIM from `PENDING` to `FAILED` (Health event
`AWS_SES_DKIM_PENDING_TO_FAILED`), the three
`token._domainkey.partners.siutindei.com` CNAMEs must match the current
identity:

```bash
CLOUDFLARE_API_TOKEN=... python3 scripts/sync-ses-sending-dns.py \
  --domain partners.siutindei.com --retry
```

That upserts DNS-only CNAMEs plus the `mail.partners.siutindei.com` MX and
SPF records and asks SES to verify again (`FAILED` never self-heals).
Confirm `token.dkim.amazonses.com` resolves to a TXT record; `NXDOMAIN`
means the Cloudflare targets are stale. `GET /siu-tin-dei/board` and
**Pipeline → Outreach stats** show `outreachIdentity.dkimStatus` and the
current CNAME names.

Replies go out from the mailbox the thread was addressed to. Every outbound
message is indexed as `direction=out` so it appears in **Mail**. Bodies and
threads expire after 90 days (`BOARD_MAIL_MESSAGE_TTL_DAYS`).
