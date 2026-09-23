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
every Google operator; otherwise they authenticate but the API returns
**403**.

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
`POST approvals/{id}/approve|reject`, `code/promote`, `code/sync-staging`,
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

## Enable Banking account sync

The **Banking** page links PSD2 bank accounts via
[Enable Banking](https://enablebanking.com) and refreshes `recordedValue`
on the finance **Accounts** sheet from live balances ("Sync now" plus a
daily EventBridge schedule at 05:30 HKT). Only balances are read.
Authentication is an RS256 JWT signed by the stack's asymmetric KMS key
(`alias/lxsoftware-admin/enable-banking`); no private key material leaves
KMS.

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
| `OpenRouterApiKeySecretArn` | Existing secret (also used by statement parsing). Must be JSON with named keys `statement-parser` and `executive-board`. |
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
| `SiutindeiBoardMailSendingEnabled` | `false` (default) / `true`. Flip only after DKIM / SPF / DMARC are in the zone; creates the SES identity and send policy. |
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

The older `lxsoftware-admin-*` connector set stays in the stack, unused,
for a future LX Software board.

### OpenRouter bill (shared account)

LX Software pays one OpenRouter invoice; sibling products share it by
tagging requests. Catalog:
[`contracts/openrouter-apps.json`](../../contracts/openrouter-apps.json).

| App id | Product | How spend is recorded |
|--------|---------|----------------------|
| `statement-parser` | Statement OCR (this repo) | Metered here |
| `executive-board` | Executive Board (this repo) | Metered here |
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
days in place. Days older than 30 stay as last saved, so history builds
from the first successful pull.

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
address on existing orgs). The gate uses the cached `v_catalog_health`
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
   (Cloudflare proxy off).
3. SPF: `v=spf1 include:_spf.mx.cloudflare.net include:amazonses.com ~all`.
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
   `GetAccount` status (cached 10 min); one message goes from `hello@` to
   your sign-in address. A refusal shows the full SES error inline and as
   `board_mail_send_failed` in CloudWatch. Do this before asking a persona
   to reply.

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
