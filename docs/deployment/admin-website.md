# Deploying the admin website and infrastructure

This runbook follows the same ordering as production bring-up: CDK Bootstrap,
issue the ACM certificate, deploy infrastructure, configure GitHub and Cognito,
then deploy the SPA.

## Pre-deploy checklist (junior dev)

Before triggering **Deploy Backend**:

1. **GitHub environment** — set `AWS_ACCOUNT_ID`, `AWS_REGION`, optional
   **`CDK_BOOTSTRAP_QUALIFIER`** (only if you did not use the default `hnb659fds`),
   `ADMIN_ACM_CERT_ARN`,
   `ADMIN_GOOGLE_CLIENT_ID`, **`ADMIN_FEDERATED_EMAIL_ALLOWLIST`** (comma-separated
   lower-case emails that should receive `admin` via Pre Token Generation — include
   every Google admin and the bootstrap email), `ADMIN_BOOTSTRAP_EMAIL`, and
   (after first deploy) SPA vars `ADMIN_COGNITO_*`, `ADMIN_API_BASE_URL`. Set
   **secrets** `ADMIN_GOOGLE_CLIENT_SECRET` (Google OAuth client secret) and
   `ADMIN_BOOTSTRAP_TEMP_PASSWORD` (bootstrap user password; CDK `noEcho`).
2. **Bootstrap password** — must satisfy the pool policy (14+ chars with mixed
   classes) or `adminCreateUser` fails.
3. **Region** — `AWS_REGION` for GitHub Actions must match the region where the
   stacks deploy (same as the public site). **CDK Bootstrap** must be complete in
   that same region (SSM `/cdk-bootstrap/<qualifier>/version` must exist), or
   **Deploy Backend** will fail. Cross-stack CSP wiring assumes this region.
4. **GitHubActionsRole** — must be allowed to `sts:AssumeRole` the CDK asset
   publishing / deploy roles (`cdk-hnb659fds-*` or your `CDK_BOOTSTRAP_QUALIFIER`)
   and `ssm:GetParameter` on `/cdk-bootstrap/*`. If logs show “could not be used
   to assume … file-publishing-role” and deploy fails on missing CDK Bootstrap SSM,
   fix CDK Bootstrap + IAM trust first.
5. **ACM** — `ADMIN_ACM_CERT_ARN` must be **ISSUED** in **us-east-1** (CloudFront).
6. **Cloudflare** — proxy **OFF** (gray cloud) for ACM validation and for the
   `admin` CNAME.
7. **Google OAuth client** — add `https://<cognito-domain>/oauth2/idpresponse` to
   authorized redirect URIs **before** the first Hosted UI sign-in.

After the first deploy, **verify** that `AdminFederatedEmailAllowlist` includes
every Google operator; otherwise they authenticate but the API returns **403**.

## 1. CDK Bootstrap

Run **CDK Bootstrap** for the target region used by the stacks (match the public site region),
and **us-east-1** for ACM certificates used by CloudFront:

```bash
cd backend/infrastructure
npm ci
npx cdk bootstrap aws://ACCOUNT_ID/REGION
npx cdk bootstrap aws://ACCOUNT_ID/us-east-1
```

## 2. ACM certificate (us-east-1 only)

Request a certificate for `admin.lx-software.com`, complete DNS validation in
Cloudflare with **proxy disabled**, wait until the certificate status is
**ISSUED**, and record the ARN for GitHub Actions variables.

## 3. GitHub environment configuration

Under **Settings → Environments → production**, configure variables and secrets
as described in the checklist above and in `docs/architecture/security.md`.

## 4. Deploy admin infrastructure

Run the **Deploy Backend** workflow (or invoke CDK locally with the same
parameters). Confirm both admin stacks finish successfully:

- `lxsoftware`           — Cognito, DynamoDB, S3 assets, HTTP API
- `lxsoftware-admin-web` — S3 origin + CloudFront for the SPA

Copy CloudFormation outputs for the user pool, client, hosted UI domain, API
URL, and CloudFront domain name into the GitHub environment variables used by
the **Deploy Admin Web** workflow.

## 5. DNS

Create a **CNAME** from `admin.lx-software.com` to the CloudFront distribution
domain name. Keep Cloudflare proxy **off** for this record.

## 6. Google OAuth client (IdP)

Add `https://<cognito-domain>/oauth2/idpresponse` to the Google Cloud OAuth
client’s authorized redirect URIs. **Do not** manually change Cognito app
client callback URLs in the console — they are owned by CDK from the
`AdminWebDomainName` parameter; console drift will be overwritten on the next
deploy.

## 7. Deploy the admin SPA

Run **Deploy Admin Web**. The workflow builds `apps/admin_web` with production
`VITE_*` values. The deploy script uploads hashed `dist/assets/**` with a long
immutable cache, then uploads `index.html` with `no-cache`, then invalidates
CloudFront.

## 8. Smoke tests

1. Open `https://admin.lx-software.com` and confirm the login screen appears.
2. Use **Sign in with Google** (allow-listed email) or **Sign in with email**
   for the bootstrap user; complete Hosted UI / MFA as applicable.
3. From DevTools, confirm session tokens exist in `sessionStorage`.
4. Call `GET /health` on the API without auth (expect **200**).
5. Call `GET /me` with `Authorization: Bearer <id_token>` (expect **200**).
6. Exercise presigned **POST** upload and confirm flows; verify a DynamoDB row
   under `ASSET#...` / `META`.
7. Sign out, reload, and confirm you return to the login screen.

## Local UI without a stack

`npm run dev` still needs a real Cognito pool and API. For layout and table
work, `npm run dev:mock` (from `apps/admin_web`) loads `.env.mock`, signs the
SPA in with a fake admin token, and serves fixture rows from
`src/lib/mock/fixtures.ts`. Never set `VITE_ADMIN_MOCK=1` on a production
build.

## Operating

For investigating production issues from CloudWatch, S3 access logs, and the
admin DynamoDB tables using the `cursor-cloud-agent` IAM identity, see
[`docs/deployment/cloud-agent-iam.md`](./cloud-agent-iam.md). That document
lists the exact inline IAM policy needed and the AWS CLI / Console commands
to attach it.

## Public read-only API keys

The HTTP API exposes read-only mirrors of the admin GET endpoints under
`/public/*`, authenticated with a static API key in the `x-api-key` header
instead of a Cognito JWT:

| Route | Mirrors |
|-------|---------|
| `GET /public/finance` | `GET /finance` |
| `GET /public/finance/quotes` | `GET /finance/quotes` |
| `GET /public/records` | `GET /records` |
| `GET /public/fx/v2/rates` | `GET /fx/v2/rates` |

Assets and parse-job endpoints are **not** mirrored (they presign S3 access to
bank statements / are owner-scoped). Every write route stays on the Cognito
JWT authorizer, and the Lambda handler enforces the same GET allowlist as
defense in depth (`PUBLIC_READ_PATHS` in `backend/lambda/admin/dispatch.py`).

Keys are validated by the `PublicApiKeyAuthorizerFn` Lambda authorizer, which
looks up the scrypt digest of the presented key in the records table
(`pk = APIKEY#<digest>`, `sk = META`; see
`backend/lambda/public_api_authorizer/api_key_hash.py` for the digest
rationale). Only the digest is ever stored or logged. API Gateway caches
authorizer verdicts for up to **5 minutes**, so revocation takes up to that
long to propagate.

Manage keys with admin AWS credentials (needs table read/write + CMK access):

```bash
# Mint (prints the key exactly once; keys look like lxpk_…)
python3 scripts/manage-public-api-keys.py create --label "reporting" \
  --expires-at 2027-01-01

# List / revoke
python3 scripts/manage-public-api-keys.py list
python3 scripts/manage-public-api-keys.py revoke --key-id <keyId>
```

### Via GitHub Actions (no local AWS setup)

The **Manage Public API Keys** workflow (`.github/workflows/manage-api-keys.yml`,
Actions tab > Run workflow) runs the same script through the `GitHubActionsRole`
OIDC role and the `production` environment.

One-time setup: add a `PUBLIC_API_KEY_GPG_PASSPHRASE` secret under
**Settings > Environments > production > Secrets** (any strong passphrase you
keep locally). Because this repository is public and workflow logs are
world-readable, a minted key is never printed — the job emits a
gpg-encrypted block in the run summary instead. Retrieve it with:

```bash
# paste the armored block from the job summary into key.asc, then:
gpg --decrypt key.asc   # enter the PUBLIC_API_KEY_GPG_PASSPHRASE value
```

`list` and `revoke` need no passphrase and print straight to the job summary.
If the run fails with `AccessDenied` on `dynamodb:PutItem` or `kms:Decrypt`,
grant `GitHubActionsRole` those actions on the records table and the shared
CMK.

Call the API:

```bash
curl -H "x-api-key: lxpk_..." "$ADMIN_API_BASE_URL/public/finance"
```

A `.gitleaks.toml` rule flags any `lxpk_…` value committed to the repo.

## Enable Banking account sync

The admin SPA's **Banking** page links open-banking (PSD2) bank accounts via
[Enable Banking](https://enablebanking.com) and refreshes `recordedValue` on
the finance **Accounts** sheet from live balances — manually ("Sync now") and
on a daily EventBridge schedule (05:30 HKT). Only balances are read; no
payment scopes are requested.

Authentication to the Enable Banking API uses an RS256 JWT signed by the
stack's asymmetric KMS key (`lxsoftware-admin/enable-banking`) — no private
key material is ever stored or exported.

One-time setup:

1. Deploy the stack (the KMS key is created even while the feature is off).
2. Export the public key with admin AWS credentials:

   ```bash
   python3 scripts/export-enable-banking-public-key.py
   ```

3. Create an account at [enablebanking.com](https://enablebanking.com/sign-in/)
   and register a **production** application, pasting the PEM public key as the
   certificate. Add the redirect URLs
   `https://<AdminWebDomainName>/banking/callback` and (for local dev)
   `http://localhost:5173/banking/callback`.
4. Activate the inactive production application by linking your own accounts
   ("Activate by linking accounts" in the Control Panel). Restricted
   applications can only read accounts you link — which is exactly this use
   case (no Enable Banking contract needed for individual non-commercial use).
5. Set the returned application id as the `EnableBankingAppId` parameter
   (`lxsoftware:EnableBankingAppId` in `backend/infrastructure/params/*.json`)
   and redeploy. Leaving it blank keeps the feature disabled.

Then, in the admin SPA: **Banking → Connect a bank** (redirects through the
bank's own consent screen and back to `/banking/callback`), map each linked
bank account to an Accounts-sheet record, and run **Sync now**. Consents
expire per PSD2 (90 days for most UK banks; the stack caps requests at 180
days) — reconnect from the same page when a session expires.

## Executive Board (AI board for Siu Tin Dei)

The **Siu Tin Dei → Executive Board** tab hosts a fixed board of eight AI
personas (CEO, CFO, COO, CPO, CTO, CIO, CISO, CMO) that chat with the owner,
run stand-ups and deep dives through OpenRouter, and keep a list of next
actions. Design notes live in
[`docs/architecture/executive-board-plan.md`](../architecture/executive-board-plan.md).

Everything runs on the existing `lxsoftware` stack (`AdminApiFn` + the records
table); there is no new Lambda, table, or bucket. Board rows use the
`BOARD#` prefix and are excluded from the generic `/records` scan.

Stack parameters (all optional, set in `backend/infrastructure/params/*.json`):

| Parameter | Purpose |
|-----------|---------|
| `lxsoftware:OpenRouterApiKeySecretArn` | Already required for statement parsing; the board reuses the same key. This secret already exists in the account — CDK does not create it. |
| `lxsoftware:BoardGitHubRepo` | `owner/name` of the repository to read (default `lx-software-ltd/siutindei`). |
| `lxsoftware:BoardToolsEnabled` | `true` (default) / `false`. Deploy-time kill switch for every board tool call, independent of the in-app settings. |
| `lxsoftware:BoardAwsStackPrefix` | CloudFormation stack-name prefix used to filter Cost Explorer / CloudWatch results (default `siutindei`). When no cost rows carry the tag, `aws_monthly_cost` falls back to the whole account and labels the result `scope: account`. |
| `lxsoftware:BoardAwsLambdaNames` | Comma-separated Lambda function names (the siutindei stack lives in another repo, so they cannot be derived here). `aws_lambda_health` reports 24h errors/duration for exactly these; empty means "no functions configured". |
| `lxsoftware:SiutindeiClusterArn` | Aurora cluster ARN for the siutindei database (RDS Data API). Required for Executive Board `finance` and `product` tools. Leave blank to keep those tools returning a clear "not configured" error. |
| `lxsoftware:SiutindeiDbSecretArn` | Secrets Manager ARN of the siutindei DB credentials the Data API uses (RDS-owned; do not recreate). |
| `lxsoftware:MetaVerifyToken` | Token Meta sends on the GET verify handshake (`hub.verify_token`). Not a Secrets Manager secret. |
| `lxsoftware:MetaPageId` / `MetaIgUserId` / `MetaWaPhoneNumberId` / `MetaAdAccountId` / `MetaWabaId` | Graph ids the `meta` tools call. |
| `lxsoftware:AppStoreConnectAppId` / `GooglePlayPackageName` | App id / package if they are not already inside the secrets. |
| `lxsoftware:AppStoreConnectVendorNumber` | App Store Connect vendor number (Payments and Financial Reports page). Needed for Apple download counts, which come from yesterday's daily `SALES`/`SUMMARY` report; may also be stored as `vendorNumber` inside the key secret. Installs are not exposed by either store API and are reported as `null`. |
| `lxsoftware:BoardMailDomain` | Domain the board indexes (default `siutindei.com`). Every mailbox at this domain is copied to the board's SES inbound address by the Cloudflare Email Worker. |
| `lxsoftware:BoardMailSendingEnabled` | `false` (default) / `true`. Flip to `true` only after the DKIM CNAMEs, SPF `include:amazonses.com`, and DMARC are in the `BoardMailDomain` zone. Creates the SES sending identity and the IAM send policy; until then mail tools stay read-only. |
| `lxsoftware:BoardChatModel` / `BoardMeetingModel` / `BoardDeepDiveModel` | Default OpenRouter model slugs (`openai/gpt-4.1-mini`, `openai/gpt-4.1-mini`, `anthropic/claude-sonnet-4`). The owner can override them per board in **Settings**. |

CDK creates these connector secrets with dummy values and wires their ARNs
into `AdminApiFn`. After **Deploy Backend**, open each secret in Secrets
Manager (`ap-southeast-1`) and replace the dummy. Later CDK deploys do
**not** overwrite a value you edited in the console (unless the generator
properties in `lxsoftware-stack.ts` change). Secrets use
`RemovalPolicy.RETAIN`, so a stack delete keeps the filled-in tokens.
Names are `lxsoftware-admin-siutindei-board-*`: `lxsoftware-admin` is this
stack; `siutindei-board` is the Siu Tin Dei Executive Board (same local-part
as the inbound mailbox). OpenRouter stays `lxsoftware-admin-openrouter-api-secret-*`
because statement parsing also uses it.

| Secret name | Dummy shape | Replace with |
|-------------|-------------|--------------|
| `lxsoftware-admin-siutindei-board-github-token` | random 40-char string | Fine-grained GitHub PAT (plain string). Needed for write tools, security alerts, and a higher rate limit. Reads of the public `siutindei` repo work without it. |
| `lxsoftware-admin-siutindei-board-search-api-key` | random 40-char string | Brave Search API key (plain string). Until then `research` falls back to OpenRouter `:online`. |
| `lxsoftware-admin-siutindei-board-meta-token` | random 40-char string | Meta System User long-lived token (Page / Instagram / WhatsApp / ads). |
| `lxsoftware-admin-siutindei-board-meta-app-secret` | random 40-char string | Meta app secret (`X-Hub-Signature-256` on `POST /webhooks/meta`). |
| `lxsoftware-admin-siutindei-board-app-store-connect-key` | JSON `{keyId, issuerId, appId, vendorNumber, privateKey}` | Real App Store Connect API key. Paste the `.p8` into `privateKey`. |
| `lxsoftware-admin-siutindei-board-google-play-sa` | JSON `{type, client_email, packageName, private_key}` | Real Play Console service-account JSON. |
| `lxsoftware-admin-siutindei-board-google-analytics-sa` | JSON `{type, client_email, private_key}` | Dedicated GA4 / GTM service-account JSON (not the Play key). |

GitHub token setup (only needed for write tools, security alerts, or a higher
rate limit):

1. On GitHub create a fine-grained personal access token scoped to the
   `siutindei` repository only, with **Contents: read**, **Issues: read and
   write**, **Actions: read**, **Metadata: read** and, if you want the CISO to
   see Dependabot / code-scanning findings, **Security events: read**. Set an
   expiry and rotate it like any other secret.
2. After the stack is deployed, open
   `lxsoftware-admin-siutindei-board-github-token` in Secrets Manager and replace the
   dummy string with the PAT. No stack parameter or redeploy is required.

Scheduled stand-ups: two EventBridge Scheduler schedules invoke `AdminApiFn`
with `{ internal: "board_meeting", trigger: "schedule", slot: "morning" | "evening" }`
at 06:00 HKT and 18:00 HKT (`Asia/Hong_Kong` cron, no DST maths). Both are
off until the owner turns them on in **Executive Board → Settings**; the
handler also refuses to start a meeting when the daily budget is exhausted or
another meeting is still running.

Lambda invoke permissions: `AdminApiFn` is fronted by 60+ HTTP API routes.
API Gateway is granted **one** API-wide invoke permission (`AdminApiInvoke`,
source ARN `arn:aws:execute-api:…:<api-id>/*/*/*`) instead of one
`AWS::Lambda::Permission` per route — per-route statements exceeded Lambda's
fixed 20 KB resource-based policy limit. Scheduler targets use an IAM role
for the same reason. When adding new triggers for `AdminApiFn`, prefer
role-based invocation (Scheduler, Step Functions) or widen an existing
statement rather than adding new resource-policy statements.

Cost controls: every OpenRouter call records usage under the board's daily
usage row, and chats/meetings stop when the configured daily budget
(default USD 15) is reached. OpenRouter requests are sent with data
collection denied. The context pack shares only aggregated finance totals
(never individual transactions) and no owner PII.

### Board tools (function calling)

Members can look things up and act while answering, through OpenRouter
function calling. Design:
[`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md).

- **Tools shipped:** `github` (search/get issues and PRs, workflow runs,
  commits, files, security alerts; create issue, comment, set labels),
  `board` (read actions/minutes/decisions; add an action, update the member's
  own actions), `mail` (list mailboxes and threads, read a thread,
  contact history; reply, send, or forward), `research` (Brave Search /
  OpenRouter `:online`, 24 h cache), `aws` (Cost Explorer, CloudWatch
  alarms, Lambda health, Health events; budget-alert proposal), and
  `security` (GitHub alerts, Security Hub, Access Analyzer, Cognito MFA;
  remediation issue proposal), `product` (catalog / funnel / provider-pipeline
  SQL views),   `meta` (Page / Instagram insights, comments, DMs, WhatsApp
  threads, ad spend; post, story, reply, ad set, boost a post, or lead relay),
  `stores` (App Store Connect + Play metrics, review reply, release-notes
  draft), `web` (GA4 sessions / conversions and GTM live version), and
  `finance` (listing subscriptions, invoices, aging, draft/send
  invoice, dunning, match or record a payment, price-change proposal). The
  board never initiates a bank payment.
- **Levels** per tool per member: `off`, `read`, `propose` (writes are queued
  for the owner), `act` (writes run directly). A **global mode**
  (`readOnly` / `propose` / `act`) caps the whole matrix, and **Tools
  enabled** in the same card is the in-app kill switch. Defaults live in
  `contracts/board-tools.json` (e.g. CTO `act` on GitHub, CFO/COO/CMO `off`);
  the shipped global mode is `propose`, so nothing writes to GitHub without
  an approval until the owner raises it.
- **Approvals** (`Executive Board → Approvals`): each proposed write shows
  the member, the reason, and the exact arguments; the owner can edit the
  arguments, approve (the call runs as the owner and the result is logged)
  or reject with a note the member sees next time. Mail writes render an
  unmasked To / From / Subject / body preview; a guard on `act` downgrades
  any send whose recipients are not on the allow-list (email, `@domain`, or
  E.164 phone) to `propose`. Meta ads writes that would breach the owner-set
  daily / monthly caps also drop to `propose`.
- **Audit:** every call is a `BOARD#TOOLCALL#` row (persona, level, actor,
  arguments, result preview, duration) and is visible under **Settings →
  Tools & permissions → Show the tool call log**. Meeting transcripts record
  a `tool` turn before the member's statement; chat replies list their calls.
- **Limits** (contract): at most 4 tool rounds and 8 calls per reply, 10 s
  per external call, tool loops capped at 120 s in chat and 60 s per meeting
  statement, tool results truncated to 6 000 characters, 200 pending
  approvals; approvals expire after 60 days and call-log rows after 90.
- **Routes:** `GET/PUT /siu-tin-dei/board/tools`, `GET /siu-tin-dei/board/tools/calls`,
  `GET /siu-tin-dei/board/approvals`, `POST …/approvals/{id}/approve|reject`,
  `GET /siu-tin-dei/board/mail`, `GET /siu-tin-dei/board/mail/{threadId}`,
  `POST /siu-tin-dei/board/mail/{threadId}/read`,
  `GET /siu-tin-dei/board/receivables`.
  Admin-group JWT only. `GET/POST /webhooks/meta` is the **first
  unauthenticated** admin-API route (HMAC / verify-token only).
- **Emergency stop:** set `lxsoftware:BoardToolsEnabled=false` and redeploy,
  or flip **Tools enabled** off in the app. Both leave the matrix intact.

Smoke test after deploy: open the tab, save a company vision/mission, edit one
member's mandate, send a chat message to the CEO (reply arrives within ~30 s),
then **Run stand-up** and confirm minutes and action items appear. For tools:
ask the CTO "what is open on GitHub about bookings?" and check the reply lists
a `Searched GitHub issues` row; ask the CPO to open an issue and confirm it
lands in **Approvals** rather than on GitHub. Ask the CFO "what did AWS cost
last month?" and the CISO "any HIGH findings?" — both should cite cached
reads after the hourly `BoardCacheRefreshSchedule` has run once. For mail: open **Mail**, confirm
mailbox chips and threads, toggle **Board's view** (addresses become
`contact#N`), then ask the CMO "what's unread?" and confirm a `Listed threads`
row. For receivables: apply `scripts/siutindei/receivables.sql` on the
siutindei cluster, set the two Data API parameters, open **Receivables**, and
ask the CFO to draft the first listing plan (`finance_propose_price_change`).
Nightly `BoardReceivablesMirrorSchedule` (00:30 HKT) writes `[receivables]`
lines into the Siu Tin Dei book; daily `BoardDunningSchedule` (09:00 HKT)
queues D+7 / D+21 / D+35 reminders in **Approvals**.

### Board receivables (Aurora Data API)

Listing invoices live in the **siutindei** Aurora database so the product can
show billing state later; this admin app only reaches them through the RDS
Data API (no VPC). Design:
[`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md) §5.4–§5.7.

1. Enable the Data API on the siutindei Aurora cluster if it is not already on.
2. Apply `scripts/siutindei/receivables.sql` in that repo (tables
   `listing_plans`, `listing_subscriptions`, `invoices`, `payments`, plus
   views `v_catalog_health`, `v_funnel_daily`, `v_provider_pipeline` aligned
   to the live siutindei Alembic schema, plus `listing_events_daily` for
   funnel rows the product does not yet write).
3. Set `lxsoftware:SiutindeiClusterArn` and `lxsoftware:SiutindeiDbSecretArn`
   and redeploy. The stack attaches a conditional `rds-data:ExecuteStatement`
   / `BatchExecuteStatement` policy plus `secretsmanager:GetSecretValue` on
   the DB secret.
4. Invoice numbers are `STD-{year}-0001`; each draft also gets a unique FPS
   reference. Drafts also write a PDF to `board/invoices/` on the assets
   bucket (`pdf_key` on the invoice). `finance_send_invoice` / `finance_send_reminder` email from
   `billing@siutindei.com` and stay in **Approvals** unless the payer is on
   the mail allow-list. `finance_match_payment` acts only when amount and FPS
   reference agree.
5. Bank ingest (alert mail or an API-first HK account) is **T4b** — the
   account has not been opened yet. Until then use
   `finance_record_manual_payment`.

### Board Meta (Page, Instagram, WhatsApp)

The board owns the existing WhatsApp number through the Cloud API, plus the
Facebook Page and Instagram account. Design:
[`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md) §5.3.

1. Create a Business-type app under the Siu Tin Dei Business Manager and a
   System User token (`pages_*`, `instagram_*`, `whatsapp_business_*`,
   `ads_read` / `ads_management`). After deploy, replace the dummy values
   in `lxsoftware-admin-siutindei-board-meta-token` and
   `lxsoftware-admin-siutindei-board-meta-app-secret`.
2. **WhatsApp coexistence:** turn coexistence on for the number so the
   owner's phone app keeps working while the board reads and replies through
   the API. If coexistence is unavailable, the number moves fully to the
   Cloud API and the owner replies from **Approvals**.
3. Subscribe the app to `GET/POST https://<admin-api>/webhooks/meta`. This
   is the first admin-API route **without** a Cognito JWT: GET checks
   `MetaVerifyToken`; POST checks `X-Hub-Signature-256`. The handler stores
   masked `BOARD#…#meta#` rows and returns 200 without calling OpenRouter.
4. Set `MetaPageId`, `MetaIgUserId`, `MetaWaPhoneNumberId`,
   `MetaAdAccountId`, and optionally `MetaWabaId` (used by
   `meta_list_whatsapp_templates`; otherwise the phone-number id is asked
   for its WhatsApp Business Account). Until they are set the `meta` tools
   return a clear "not configured" error.
5. WhatsApp `act` is only inside the 24-hour customer-service window and
   only to numbers on the allow-list (E.164 phones are first-class entries
   next to email / `@domain`); everyone else (and every reply outside the
   window) stays in **Approvals**, optionally as a template.
   `meta_relay_lead` emails the provider and the parent from `hello@`.
6. Ads: set **Meta ads spend caps** on the Tools card (defaults daily USD
   10 / monthly USD 50, clamped to 500 / 2 000). `meta_create_ad_set` and
   `meta_boost_post` **act** only while recorded commitment plus Graph
   month-to-date spend still fits; otherwise they go to Approvals. The
   shipped global mode stays `propose` until you flip it.

### Board stores (App Store Connect + Google Play)

The App Store Connect API key and Google Play service account already exist.
Design: [`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md) §4 `stores`.

1. After deploy, edit `lxsoftware-admin-siutindei-board-app-store-connect-key`: set
   `keyId`, `issuerId`, and `privateKey` (the `.p8` body). Optional
   `appId` / `vendorNumber` can live here or in the matching stack
   parameters. The Lambda signs a 20-minute ES256 JWT on each call.
2. Edit `lxsoftware-admin-siutindei-board-google-play-sa` with the real Play
   service-account JSON (standard GCP key; add `packageName` if it is not
   passed as `GooglePlayPackageName`).
3. Set `AppStoreConnectAppId` and `GooglePlayPackageName` if they are not
   inside the secrets, plus `AppStoreConnectVendorNumber` for Apple
   downloads. Until at least one store is configured the `stores`
   tools return a clear error; the hourly cache refresh skips them.
4. Reads (`stores_metrics`, `stores_crashes`, `stores_ratings`,
   `stores_list_reviews`) are cached 20 hours and refreshed by
   `BoardCacheRefreshSchedule`. Review text is masked (`contact#hidden` /
   `phone#hidden`) before it reaches the model.
5. `stores_reply_review`: CMO may **act**; every other role proposes.
   `stores_draft_release_notes` always stays in **Approvals** and writes a
   board action — it never publishes to either store.

### Board web (GA4 + GTM)

Dedicated Analytics service account — not the Play publisher key. Design:
[`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md) §5.8.

1. Create a GCP service account with `analytics.readonly` and
   `tagmanager.readonly`. Grant it Viewer on every GA4 property and GTM
   container the board should see. After deploy, replace the dummy JSON in
   `lxsoftware-admin-siutindei-board-google-analytics-sa`.
2. Set `Ga4PropertyIds` to a comma-separated list (`123456789,987654321` or
   `properties/123456789,…`). Set `GtmContainers` to
   `accountId:containerId` pairs. Both can also live inside the secret as
   `propertyIds` / `gtmContainers`.
3. Until the SA plus at least one property or container is set, `web` tools
   return a clear error and the hourly cache refresh skips them.
4. Reads (`web_sessions`, `web_conversions`, `web_gtm_status`) are cached
   20 hours and refreshed by `BoardCacheRefreshSchedule`. Page paths are
   masked (`contact#hidden` / `phone#hidden`) before they reach the model.
5. Google Ads (`ads` tool) is T8b. `gtm_propose_publish` is T8c and always
   stays in **Approvals**.

### Board mail (Cloudflare + SES)

The owner's existing `siutindei.com` inbox is unchanged. A Cloudflare Email
Worker copies every message to the board as well. Design:
[`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md) §5.2.

**Read path (no DNS change on `siutindei.com`):**

1. Deploy the `lxsoftware` stack. Copy the `BoardMailInboundAddress` output
   (`siutindei-board@<InboundMailDomain>`). The receipt rule stores raw MIME
   under `inbound-raw/siutindei/` and `inbound_email_handler` hands those
   objects to `board_mail.ingest_raw_object`.
2. In the `siutindei.com` Cloudflare zone: **Email → Email Routing →
   Destination addresses**, add that inbound address. Cloudflare sends a
   verification mail; it lands in the inbound S3 bucket. Open the object
   once and click the link.
3. **Workers & Pages → Create**, paste
   `scripts/cloudflare/siutindei-mail-fanout.js`. Set two plain-text
   variables: `OWNER_DESTINATION` (the owner's already-verified inbox) and
   `BOARD_DESTINATION` (the address from step 1). Optional `SKIP_SENDERS`
   is a comma-separated list of addresses or `@domain` wildcards never
   copied to the board.
4. **Email Routing → Routing rules → Catch-all**: action **Send to a
   Worker**, pick that Worker. Existing per-address rules still win; either
   delete them or point them at the Worker too, or those mailboxes never
   reach the board.

**Send path (optional, after DKIM/SPF/DMARC):**

1. Set `lxsoftware:BoardMailSendingEnabled=true` and redeploy. The stack
   creates an SES email identity for `BoardMailDomain` and attaches
   `ses:SendEmail` on that domain to `AdminApiFn`.
2. Add the three `BoardMailDkimCnameN` outputs as CNAMEs on the
   `siutindei.com` zone (Cloudflare proxy **off**).
3. Extend SPF to
   `v=spf1 include:_spf.mx.cloudflare.net include:amazonses.com ~all`.
4. Add `_dmarc` TXT (`v=DMARC1; p=quarantine; rua=mailto:hello@siutindei.com`).
5. In **Executive Board → Settings → Tools & permissions**, set the
   **Recipient allow-list** (`@siutindei.com`, known vendor addresses, and
   WhatsApp numbers). Sends to anyone else stay in **Approvals** even when
   the member is at `act`.

Replies go out from the mailbox the thread was addressed to. Every outbound
message is indexed as `direction=out` so it appears in **Mail**. Bodies and
threads expire after 90 days (`BOARD_MAIL_MESSAGE_TTL_DAYS`).

## Scripts

Local or CI deploy of static files after a build:

```bash
bash scripts/deploy/deploy-admin-www.sh
```

The script reads `AdminWebBucketName` and `AdminWebDistributionId` from the
`lxsoftware-admin-web` stack outputs (override with `ADMIN_WEB_STACK_NAME`).
