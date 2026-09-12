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
   (after first deploy) SPA vars `ADMIN_COGNITO_*`, `ADMIN_API_BASE_URL`
   (`ADMIN_API_BASE_URL` is also inlined as `VITE_PUBLIC_API_URL` by
   **Deploy Public Website**). Set
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

If **Deploy Backend** fails because API Gateway cannot find
`POST /webhooks/meta/siutindei` (or `GET`) in `RouteSettings`, the
`$default` stage was updated before those routes existed. The stack may be
left `UPDATE_ROLLBACK_FAILED`. Continue rollback, skipping the stage if
CloudFormation still cannot revert it:

```bash
aws cloudformation continue-update-rollback \
  --stack-name lxsoftware \
  --resources-to-skip HttpApiDefaultStage3EEB07D6
```

Then redeploy. The stage now `DependsOn` the Meta webhook routes so the
same changeset creates the routes first.

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

Stack parameters (all optional, set in `backend/infrastructure/params/*.json`).
Keys must match the names below; an unknown `lxsoftware:*` key fails
`cdk deploy`. Naming: board-only knobs are `SiutindeiBoard*` (kill
switches, models, outreach, mail, Meta / stores / web ids); Siu Tin Dei
product resources the stack integrates with are `Siutindei*` (`SiutindeiClusterArn`,
`SiutindeiDbSecretArn`, `SiutindeiDbSecretName`); stack-wide knobs stay
unprefixed (`PublicSiteOrigins`, `PublicApiBaseUrl`, Cognito, OpenRouter,
inbound mail, Enable Banking). Lambda env vars stay short (`BOARD_*`,
`OUTREACH_*`).

| Parameter | Purpose |
|-----------|---------|
| `lxsoftware:OpenRouterApiKeySecretArn` | Already required for statement parsing; the board reuses the same key. This secret already exists in the account — CDK does not create it. |
| `lxsoftware:SiutindeiBoardGitHubRepo` | `owner/name` of the repository to read (default `lx-software-ltd/siutindei`). |
| `lxsoftware:SiutindeiBoardToolsEnabled` | `true` (default) / `false`. Deploy-time kill switch for every board tool call, independent of the in-app settings. |
| `lxsoftware:SiutindeiBoardStaffEnabled` | `false` (CDK default) / `true`. Deploy-time kill switch for Executive Board staff tasks. `board_staff.env_enabled()` is fail-closed: only `1` / `true` / `yes` / `on` count as on (unset is off). The same env is set on **both** `AdminApiFn` and `InboundStatementMailFn`. Also requires `settings.staff.enabled` in the app. Production (`params/production.json`) sets `true`; the Staff UI toggle is still required before any seat runs. |
| `lxsoftware:PublicSiteOrigins` | CSV of extra browser origins allowed on the HTTP API CORS list (admin origin is always included). Stack-wide; used by the public newsletter form (`apps/public_www`) and any other unauthenticated browser client. Default includes the LX Software and Siu Tin Dei public origins. |
| `lxsoftware:SiutindeiBoardOutreachSendingDomain` | SES From domain for cold outreach (default `partners.siutindei.com`). Owner adds DKIM CNAMEs, MAIL FROM MX+TXT and DMARC before `outreach_send` will send. |
| `lxsoftware:SiutindeiBoardOutreachFromLocalPart` | Local part of the outreach From address (default `partnerships`). |
| `lxsoftware:PublicApiBaseUrl` | Public base URL of this stack's HTTP API. Used today for board unsubscribe / newsletter confirm links. Blank uses the API endpoint CloudFormation assigns. |
| `lxsoftware:SiutindeiBoardAwsStackPrefix` | CloudFormation stack-name prefix used to filter Cost Explorer / CloudWatch results (default `siutindei`). When no cost rows carry the tag, `aws_monthly_cost` falls back to the whole account and labels the result `scope: account`. |
| `lxsoftware:SiutindeiBoardAwsLambdaNames` | Comma-separated Lambda function names (the siutindei stack lives in another repo, so they cannot be derived here). `aws_lambda_health` reports 24h errors/duration for exactly these; empty means "no functions configured". |
| `lxsoftware:SiutindeiClusterArn` | Aurora cluster ARN for the siutindei database (RDS Data API). When set, CDK enables the HTTP endpoint on that cluster and applies `scripts/siutindei/receivables.sql`. Required for Executive Board `finance` and `product` tools. Leave blank to keep those tools returning a clear "not configured" error. |
| `lxsoftware:SiutindeiDbSecretArn` | Optional Secrets Manager ARN of the siutindei DB credentials. Leave blank to resolve `SiutindeiDbSecretName` (default `lxsoftware-siutindei-database-credentials`). RDS-owned; do not recreate. |
| `lxsoftware:SiutindeiDbSecretName` | Secrets Manager name used when `SiutindeiDbSecretArn` is blank (default `lxsoftware-siutindei-database-credentials`). |
| `lxsoftware:SiutindeiBoardMetaVerifyToken` | Token Meta sends on the GET verify handshake (`hub.verify_token`). Not a Secrets Manager secret. |
| `lxsoftware:SiutindeiBoardMetaPageId` / `SiutindeiBoardMetaIgUserId` / `SiutindeiBoardMetaWaPhoneNumberId` / `SiutindeiBoardMetaAdAccountId` / `SiutindeiBoardMetaWabaId` | Graph ids the `meta` tools call. |
| `lxsoftware:SiutindeiBoardAppStoreConnectAppId` / `SiutindeiBoardGooglePlayPackageName` | App id / package if they are not already inside the secrets. |
| `lxsoftware:SiutindeiBoardAppStoreConnectVendorNumber` | App Store Connect vendor number (Payments and Financial Reports page). Needed for Apple download counts, which come from yesterday's daily `SALES`/`SUMMARY` report; may also be stored as `vendorNumber` inside the key secret. Installs are not exposed by either store API and are reported as `null`. |
| `lxsoftware:SiutindeiBoardMailDomain` | Domain the board indexes (default `siutindei.com`). Every mailbox at this domain is copied to the board's SES inbound address by the Cloudflare Email Worker. |
| `lxsoftware:SiutindeiBoardMailSendingEnabled` | `false` (default) / `true`. Flip to `true` only after the DKIM CNAMEs, SPF `include:amazonses.com`, and DMARC are in the `SiutindeiBoardMailDomain` zone. Creates the SES sending identity and the IAM send policy; until then mail tools stay read-only. |
| `lxsoftware:SiutindeiBoardChatModel` / `SiutindeiBoardMeetingModel` / `SiutindeiBoardDeepDiveModel` | Default OpenRouter model slugs (`openai/gpt-4.1-mini`, `openai/gpt-4.1-mini`, `anthropic/claude-sonnet-4`). The owner can override them per board in **Settings**. |

The **Siu Tin Dei** connector secrets (`lxsoftware-admin-siutindei-board-*`)
already exist in the account. The first #328 deploy created them, then
`RemovalPolicy.RETAIN` left them behind when rollback dropped them from the
stack. CDK now **imports those names** and grants `AdminApiFn` read; it
does not try to create them again. The same happened to the autonomy
secrets `…-board-google-places-key` and `…-board-link-signing-key` on the
first #341 deploy, so they are imported the same way (the link-signing
value generated on that first attempt is the one in use). Replace the dummy values in Secrets
Manager (`ap-southeast-1`). The older `lxsoftware-admin-*` set stays in
the stack (CDK-created, unused) for a future LX Software board. OpenRouter
stays `lxsoftware-admin-openrouter-api-secret-*` because statement parsing
also uses it. That secret must be JSON with named keys `statement-parser`
and `executive-board` (mint via `scripts/mint-openrouter-app-keys.py`).
Sibling products store their own named keys. **LX Software → Dashboard**
shows AWS and OpenRouter side by side; each card has a UTC month dropdown
(current month-to-date plus the previous 12 months).

| Secret name | Dummy shape | Replace with |
|-------------|-------------|--------------|
| `lxsoftware-admin-siutindei-board-github-token` | random 40-char string | Fine-grained GitHub PAT (plain string). Needed for write tools, security alerts, and a higher rate limit. Reads of the public `siutindei` repo work without it. |
| `lxsoftware-admin-siutindei-board-search-api-key` | random 40-char string | Brave Search API key (plain string). Until then `research` falls back to OpenRouter `:online`. |
| `lxsoftware-admin-siutindei-board-meta-token` | random 40-char string | Meta System User long-lived token (Page / Instagram / WhatsApp / ads). |
| `lxsoftware-admin-siutindei-board-meta-app-secret` | random 40-char string | Meta app secret (`X-Hub-Signature-256` on `POST /webhooks/meta/siutindei` and `/webhooks/meta`). |
| `lxsoftware-admin-siutindei-board-app-store-connect-key` | JSON `{keyId, issuerId, appId, vendorNumber, privateKey}` | Real App Store Connect API key. Paste the `.p8` into `privateKey`. |
| `lxsoftware-admin-siutindei-board-google-play-sa` | JSON `{client_email, packageName, private_key}` | Real Play Console service-account JSON. |
| `lxsoftware-admin-siutindei-board-google-analytics-sa` | JSON `{client_email, private_key}` | Dedicated GA4 / GTM service-account JSON (not the Play key). |

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

### OpenRouter bill (shared account)

LX Software pays one OpenRouter invoice. Sibling products share that account
by tagging every chat-completions request. The catalog is
[`contracts/openrouter-apps.json`](../../contracts/openrouter-apps.json)
(`payer: lxSoftware`).

| App id | Product | Metered in this admin |
|--------|---------|----------------------|
| `statement-parser` | Statement OCR in this repo | Yes |
| `executive-board` | Executive Board in this repo | Yes |
| `evolvesprouts` | [lx-software-ltd/evolvesprouts](https://github.com/lx-software-ltd/evolvesprouts) | No (tag only) |
| `siutindei` | [lx-software-ltd/siutindei](https://github.com/lx-software-ltd/siutindei) (when it starts calling OpenRouter) | No (tag only) |

**What this admin sends.** Each request sets a distinct app (`HTTP-Referer` +
`X-OpenRouter-Title` from the catalog) and a stable `user` of `{app-id}:{owner}`
(`statement-parser:hillmarton`, `executive-board:siuTinDei`, …). Apps are
created **hidden**, so they do not appear on OpenRouter's public rankings.
OpenRouter Activity / Analytics can then group by **app**.

**Named keys (required).** Mint one OpenRouter key per catalog app on the
LX Software account, then store each key in that product's secret.

```bash
OPENROUTER_MANAGEMENT_API_KEY=sk-or-... python3 scripts/mint-openrouter-app-keys.py
```

Create the management key at
[openrouter.ai/settings/management-keys](https://openrouter.ai/settings/management-keys).
The script names keys `lxsoftware:{app-id}` and prints plaintext once.

**Via GitHub Actions** (`.github/workflows/mint-openrouter-keys.yml`, Actions
tab → **Mint OpenRouter App Keys** → Run workflow). One-time setup under
**Settings → Environments → production → Secrets**:

- `OPENROUTER_MANAGEMENT_API_KEY` — the management key (GitHub secret names
  cannot contain hyphens; do not use `OPENROUTER-_MANAGEMENT_API_KEY`)
- `PUBLIC_API_KEY_GPG_PASSPHRASE` — same passphrase as the public API-key
  workflow; used to encrypt minted inference keys in this public repo's logs

Leave **Preview only** checked to list which catalog names already exist.
Uncheck it to mint. Copy the armored block from the job summary and decrypt
locally (`gpg --decrypt keys.asc`). Then merge the admin JSON into
`lxsoftware-admin-openrouter-api-secret-*` as below. The management key stays
in GitHub; it does not go in that AWS secret.

**This admin.** Replace the plain string in
`lxsoftware-admin-openrouter-api-secret-*` with JSON. Parser and board
calls fail if their named field is missing (no shared-key fallback):

```json
{
  "statement-parser": "sk-or-v1-parser",
  "executive-board": "sk-or-v1-board"
}
```

**Evolve Sprouts** already has its own Secrets Manager secret
(`CDK_PARAM_OPENROUTER_API_KEY` / `OPENROUTER_API_KEY_SECRET_ARN`). Put the
`lxsoftware:evolvesprouts` plaintext there (plain string is fine — that
stack does not read this admin's JSON). Also tag every chat-completions
request in `backend/src/app/services/openrouter_client.py`:

```
HTTP-Referer: https://evolvesprouts.com
X-OpenRouter-Title: Evolve Sprouts
X-OpenRouter-App-Visibility: hidden
```

Body `user`: `evolvesprouts:{workload}` (`expense-parser`,
`sales-daily-plan`, `helper-detector`, … — no PII).

**Siu Tin Dei product** (`lx-software-ltd/siutindei`) has no OpenRouter
client yet. When it does, mint `lxsoftware:siutindei`, store that key in
the product's secret, and send `https://siutindei.com` / `Siu Tin Dei` /
`siutindei:{workload}`.

**Where the invoice lands.** Admin **LX Software → Dashboard → OpenRouter**
(and `GET /openrouter/usage`) rolls up UTC spend metered here, grouped by
app. The card defaults to month-to-date and can switch to any of the previous
12 UTC months (`?from=YYYY-MM-DD&to=YYYY-MM-DD`). Parser rows still record
which book or house the OCR ran against. Evolve Sprouts / Siu Tin Dei product
spend shows in OpenRouter Activity by app and named key until those repos
write to this ledger.

The OpenRouter invoice itself stays on the LX Software card. Parser spend is
only recorded after this deploy; the board's daily budget row remains the cap,
and the ledger is the in-admin split.

### AWS bill (shared account)

LX Software pays one AWS invoice for account `588024549699`. Sibling products
share that account by tagging every resource. Cost allocation tags
**Organization** and **Project** are already **Active** in Billing → Cost
allocation tags (required before Cost Explorer can group by them).

The catalog is [`contracts/aws-billing.json`](../../contracts/aws-billing.json)
(`payer: lxSoftware`). First matching row wins:

| Company | `Organization` tag | `Project` tag |
|---------|--------------------|---------------|
| Siu Tin Dei | `LX Software` | `Siu Tin Dei` |
| Evolve Sprouts | `Evolve Sprouts` | any |
| LX Software | `LX Software` | anything else (`Admin Console`, `Public Website`, …) |

Untagged resources and leftover values such as `Organization=Personal` land in
**Unallocated**. August 2026 Cost Explorer (UnblendedCost) was about half
Evolve Sprouts (`Project=Backend`) and half Siu Tin Dei, with LX Software's
own websites under a few dollars.

**AWS's own invoice PDF cannot be split.** It is one account total. The
internal allocation is:

- Admin **LX Software → Dashboard → AWS** (`GET /aws/usage`) — last complete
  UTC calendar month by default, with the current month-to-date and previous
  12 months on the card dropdown (`?from=YYYY-MM-DD&to=YYYY-MM-DD` to override).
- **Download allocation PDF** (`GET /aws/usage.pdf`) — the tagged split to
  attach to the LX Software book or send to the other companies.

Keep tagging new stacks the same way (`cdk.Tags` `Organization` + `Project`).
Do not rotate tag keys; Cost Explorer only groups by **activated** cost
allocation tags, and a key change orphans historical spend.

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
  `GET /siu-tin-dei/board/mail`, `POST /siu-tin-dei/board/mail/selftest`,
  `GET /siu-tin-dei/board/mail/{threadId}`,
  `POST /siu-tin-dei/board/mail/{threadId}/read`,
  `GET /siu-tin-dei/board/receivables`.
  Admin-group JWT only. `GET/POST /webhooks/meta/siutindei` is the
  canonical **unauthenticated** admin-API route (`/webhooks/meta` stays
  for an already-subscribed Meta app; HMAC / verify-token only).
- **Emergency stop:** set `lxsoftware:SiutindeiBoardToolsEnabled=false` and redeploy,
  or flip **Tools enabled** off in the app. Both leave the matrix intact.
  Staff tasks have a second ladder: `settings.staff.enabled` (UI / settings
  PUT), then `lxsoftware:SiutindeiBoardStaffEnabled=false` (redeploy), then the tools
  kill switch. `BOARD_STAFF_ENABLED` unset or any value other than
  `1`/`true`/`yes`/`on` is off. With either staff flag off,
  `POST /siu-tin-dei/board/tasks` returns 409
  `{"message":"Staff is disabled"}`.
- **Staff (WP1):** `GET/PUT/DELETE /siu-tin-dei/board/staff`,
  `GET/POST /siu-tin-dei/board/tasks`, `GET …/tasks/{taskId}`,
  `POST …/tasks/{taskId}/cancel|review`. Schedule
  `lxsoftware-admin-siutindei-board-staff-tick` every 5 minutes. Assets stay
  under `board/siuTinDei/staff/{taskId}/` on the existing assets bucket
  (already bucket-wide read/write). The **Staff** tab is inert until both
  flags are on.
- **Holds (WP2):** `GET /siu-tin-dei/board/holds`,
  `POST …/holds/{holdId}/veto`, `POST …/holds/veto-class`,
  `PUT …/boundaries`, `GET …/ramp`. A hold is "the founder may say no";
  an Approval is "the founder must say yes". Default hours: internal /
  inbound_reply / outbound_known = 0; cold_outreach / publish / spend = 24;
  code_staging = 12. Quiet hours (default 22:00–08:00 HKT) push
  `executeAt` to the next 08:00 HKT. When staff is on, `always_propose`
  publish ops (`meta_propose_post`, `meta_propose_story`, newsletter send)
  become 24 h holds rather than Approvals; `code_production` stays an
  Approval (`action_class_exempt`). `code_merge_staging` stays
  `always_propose` until the siutindei Appendix A workflows exist. The
  **Approvals** section shows **Scheduled (veto to stop)**; **Settings**
  has the Boundaries card.
- **Triage (WP3):** with both staff flags on, inbound `siutindei.com` mail,
  Meta webhooks and newly seen store reviews open tasks for Parent Support,
  Provider Success or Community Manager. Escalation keywords (English and
  Chinese) send the acknowledgement template and park the task on
  **Needs owner**. Quiet hours hold replies until 08:00 HKT. Finance and
  phishing mail still route to `accountant` / `security-analyst` (those
  seats are active from WP9).
- **Daily review (WP4):** `GET /siu-tin-dei/board/review`,
  `POST …/review/sample/{callId}/wrong`, `GET/POST …/lessons`,
  `GET/POST …/breakers/{name}/reset`, `POST …/ramp/{classKey}/promote`.
  Schedules `lxsoftware-admin-siutindei-board-review-compile` (07:15 HKT)
  and `…-board-review-send` (07:30 HKT). Set `settings.review.digestTo`
  (Settings card) before expecting the digest; sending still requires
  `SiutindeiBoardMailSendingEnabled`. **Daily review** is the default board section
  once `settings.staff.enabled` is on. Confirming a lesson injects it into
  the next staff-task prompt. A budget breaker at 100% of
  `settings.staff.dailyBudgetUsd` flips `settings.staff.enabled` off.
- **Market intelligence (WP5):** `GET/POST /siu-tin-dei/board/watchlist`,
  `PUT/DELETE …/watchlist/{watchId}`, `GET …/changes?days=7`. Schedules
  `lxsoftware-admin-siutindei-board-intel-crawl` (03:00 HKT daily) and
  `…-board-intel-weekly` (Monday 04:00 HKT). Digests live under
  `board/siuTinDei/intel/{watchId}/` on the assets bucket. User-Agent
  `SiuTinDeiBoardBot/1.0 (+https://siutindei.com/bot)`. The **Market**
  section is the watchlist, candidates (Promote / Ignore), change notes,
  and the latest weekly brief. `market-analyst` starts inactive — flip
  it on at runbook step 3. Owner: add about five competitor watches
  after enabling staff; the first Monday brief creates CPO `later`
  actions from the JSON block.
- **Prospecting and outreach (WP6):** `GET /siu-tin-dei/board/prospects`,
  `GET/PUT …/prospects/{id}`, `POST …/prospects/import`,
  `POST …/prospects/{id}/merge`, `GET/PUT …/sequences/{type}`,
  `GET …/outreach/stats`. Public
  `GET/POST /public/outreach/unsubscribe/{token}` (no JWT; HMAC token).
  Schedule `lxsoftware-admin-siutindei-board-targets` (08:00 HKT).
  Secrets `lxsoftware-admin-siutindei-board-google-places-key` (replace
  dummy) and `lxsoftware-admin-siutindei-board-link-signing-key`
  (generated) are imported by name, like the connector set. SES identity for `SiutindeiBoardOutreachSendingDomain` is created
  pending DNS; sends refuse until `VerifiedForSendingStatus`.
  Configuration set `lxsoftware-admin-siutindei-outreach` → SNS → SQS.
  Outreach and board-mail IAM include both `configuration-set/…-outreach`
  and `…-newsletter` plus `ses:SendBulkEmail`; templates are scoped to
  `template/lxsoftware-admin-siutindei-*`. List-Unsubscribe is HTTPS-only
  (RFC 8058). **Pipeline** section. `prospector` starts inactive — flip
  it on at runbook step 4. Owner: DNS for `partners.siutindei.com`,
  Places key, SES production / identity verify, then raise the daily cap
  only via the 7-day warm-up (max 100).

- **Content calendar (WP7):** `GET/POST /siu-tin-dei/board/content`,
  `PUT /content/{id}`, `POST /content/{id}/render`,
  `GET /content/{id}/creative/{n}`. Sunday 18:00 HKT
  `…-board-content-plan`, Monday 09:00 HKT `…-board-content-readout`.
  `AdminApiFn` memory 1536 MB; first pip dependency is Pillow (Docker
  arm64 wheel — `deploy-backend.yml` and `cdk-diff.yml` register QEMU
  with `docker/setup-qemu-action` so the x86-64 runner can execute the
  `linux/arm64` build image). **Content** section. Flip `content-marketer` and
  `growth-specialist` on at runbook step 5. Meta App Review for
  `pages_manage_posts` / `instagram_content_publish` stays an owner task.

- **Newsletter (WP8):** Public `POST /public/newsletter/subscribe`,
  `GET /public/newsletter/confirm/{token}`,
  `GET/POST /public/newsletter/unsubscribe/{token}` (no JWT; HMAC token).
  Sends from `news@siutindei.com` when `SiutindeiBoardMailSendingEnabled=true`.
  Config set `lxsoftware-admin-siutindei-newsletter` → same SNS/SQS as
  outreach, plus OPEN/CLICK (records are routed by configuration-set /
  `issueId` so newsletter bounces do not trip the outreach breaker).
  Public site form uses `VITE_PUBLIC_API_URL` (CI inlines
  `vars.ADMIN_API_BASE_URL` at build) and needs the public origin
  in `PublicSiteOrigins`. Subscriber rows are `newsletter#sub#{list}#{digest}`
  (no live migration; no rows existed). Owner: create the
  `news@siutindei.com` mailbox (fan-out already copies `@siutindei.com`)
  and set `PublicSiteOrigins`. Confirm `ADMIN_API_BASE_URL` is set on the
  production GitHub environment (already required for the admin SPA).

- **Duties and remaining desks (WP9):** Flip `accountant`, `data-analyst`
  and `security-analyst` on at runbook step 6, then enable
  `settings.staff.dutiesEnabled` (Settings → Run scheduled seat duties)
  after staff is on. HKT crons on the 5-minute staff tick: BA weekly KPI
  (Mon 08:00), accountant month-end (1st 09:00) and weekly aging (Thu
  09:00), security weekly triage (Tue 09:00), data-analyst attribution
  (Mon 10:00). Hourly `board_cache_refresh` opens architect/CTO tasks for
  new CloudWatch ALARMs and security-analyst tasks for new Hub /
  Analyzer / GitHub alerts. Daily dunning creates an accountant task
  when staff is on (Approval path unchanged when staff is off). Stand-up
  minutes may include `boundarySuggestions` that prepend the daily
  review suggestions list.

- **Engineering runner (WP10):** `GET /siu-tin-dei/board/code/staging`,
  `POST …/code/promote`. Tool ops `code_run_task`, `code_get_run`,
  `code_review_pr`, `code_merge_staging`, `code_promote`. Widen the board
  GitHub token to **Actions: write**. Workflows
  `board-agent.yml` / `board-merge-staging.yml` / `board-promote.yml` must
  exist on **lx-software-ltd/siutindei** (see appendix A). Daily review
  **Promote** queues an Approval; the owner merges the GitHub
  `staging → main` PR. Architect weekly duty grooms `board-ready` issues.
  Keep `code_merge_staging` as an Approval (`always_propose`) until the
  siutindei Appendix A workflows exist; then flip architect / engineer-1 /
  engineer-2 / product-dev on (runbook step 7).

**Staff seat rollout (R-24).** Default-on seats: `support`,
`provider-success`, `community-manager`, `business-analyst`.
`maxRunningTasksDefault` is 3. Flip others on from **Staff** (or
`PUT /siu-tin-dei/board/staff/{id}`) at these steps:

1. Deploy with `SiutindeiBoardStaffEnabled=false` (CDK default). No seats needed.
2. After WP2–WP4: set `review.digestTo`, then deploy `SiutindeiBoardStaffEnabled=true`
   (`params/production.json` already does) and flip `settings.staff.enabled=true`.
   Default-on seats handle triage and the daily review. Leave `maxRunningTasks` at 3.
3. WP5: activate `market-analyst`; add ~five watchlist entries.
4. WP6: activate `prospector` after `partners.siutindei.com` DNS and SES
   identity verify. First sends are 24 h holds.
5. WP7: activate `content-marketer` and `growth-specialist`; raise
   `maxRunningTasks` to 6 after the first content week is stable.
6. WP8–WP9: set `PublicSiteOrigins`; activate `accountant`,
   `data-analyst`, `security-analyst`; then `settings.staff.dutiesEnabled`.
7. After Appendix A is live in siutindei: activate `architect`,
   `engineer-1`, `engineer-2`, `product-dev`. First staging merges stay
   Approvals until `code_merge_staging` is taken off `always_propose`.

Smoke test after deploy: open the tab, save a company vision/mission, edit one
member's mandate, send a chat message to the CEO (reply arrives within ~30 s),
then **Run stand-up** and confirm minutes and action items appear. For tools:
ask the CTO "what is open on GitHub about bookings?" and check the reply lists
a `Searched GitHub issues` row; ask the CPO to open an issue and confirm it
lands in **Approvals** rather than on GitHub. Ask the CFO "what did AWS cost
last month?" and the CISO "any HIGH findings?" — both should cite cached
reads after the hourly `SiutindeiBoardCacheRefreshSchedule` has run once. For mail: open **Mail**, confirm
mailbox chips and threads, toggle **Board's view** (addresses become
`contact#N`), then ask the CMO "what's unread?" and confirm a `Listed threads`
row. For receivables: set `lxsoftware:SiutindeiClusterArn` and redeploy
(CDK enables the HTTP Data API and applies `scripts/siutindei/receivables.sql`),
open **Receivables**, and
ask the CFO to draft the first listing plan (`finance_propose_price_change`).
Nightly `SiutindeiBoardReceivablesMirrorSchedule` (00:30 HKT) writes `[receivables]`
lines into the Siu Tin Dei book; daily `SiutindeiBoardDunningSchedule` (09:00 HKT)
queues D+7 / D+21 / D+35 accountant tasks when staff is enabled, or reminder
Approvals when staff is off.

### Board receivables (Aurora Data API)

Listing invoices live in the **siutindei** Aurora database so the product can
show billing state later; this admin app only reaches them through the RDS
Data API (no VPC). Design:
[`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md) §5.4–§5.7.

1. Set `lxsoftware:SiutindeiClusterArn` to the existing
   `lxsoftware-siutindei-db-cluster` ARN (production.json already has it) and
   redeploy. The stack turns on the RDS HTTP Data API and applies
   `scripts/siutindei/receivables.sql` (tables `listing_plans`,
   `listing_subscriptions`, `invoices`, `payments`, plus views
   `v_catalog_health`, `v_funnel_daily`, `v_provider_pipeline` aligned to the
   live siutindei Alembic schema, plus `listing_events_daily` for funnel rows
   the product does not yet write). Secret ARN is optional: blank resolves
   `lxsoftware-siutindei-database-credentials`.
2. The stack attaches a conditional `rds-data:ExecuteStatement` /
   `BatchExecuteStatement` policy plus `secretsmanager:GetSecretValue` on the
   resolved DB secret.
3. Scheduler `lxsoftware-admin-siutindei-data-api-ensure` (every 15 minutes)
   calls `rds.enableHttpEndpoint` and reapplies the script. A later **siutindei**
   deploy that omits `enableDataApi: true` can turn HTTP off for at most one
   interval; this stack turns it back on without waiting for an admin deploy.
   The product CDK should still set `enableDataApi: true`. A SQL error during
   the deploy custom resource does not roll the stack back — `AdminApiFn` keeps
   the cluster/secret env and the scheduler retries the script. The custom
   resource carries a 15-minute `ServiceTimeout`, so a provider Lambda that
   never answers (for example a failure at import) fails the deploy in
   minutes instead of CloudFormation's default one-hour wait. If a stack ever
   ends in `UPDATE_ROLLBACK_FAILED` on `SiutindeiDataApiReceivablesSchema*`,
   run **Continue update rollback** on the `lxsoftware` stack and skip that
   logical id (`aws cloudformation continue-update-rollback --stack-name
   lxsoftware --resources-to-skip <logical-id>`); the resource has no
   physical counterpart, so skipping it loses nothing.
4. Invoice numbers are `STD-{year}-0001`; each draft also gets a unique FPS
   reference. Drafts also write a PDF to `board/siuTinDei/invoices/` on the assets
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
3. Subscribe the app to `GET/POST https://<admin-api>/webhooks/meta/siutindei`
   (or the legacy `/webhooks/meta` path). This is the first admin-API route
   **without** a Cognito JWT: GET checks
   `SiutindeiBoardMetaVerifyToken`; POST checks `X-Hub-Signature-256`. The handler stores
   masked `BOARD#…#meta#` rows and returns 200 without calling OpenRouter.
4. Set `SiutindeiBoardMetaPageId`, `SiutindeiBoardMetaIgUserId`, `SiutindeiBoardMetaWaPhoneNumberId`,
   `SiutindeiBoardMetaAdAccountId`, and optionally `SiutindeiBoardMetaWabaId` (used by
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
   passed as `SiutindeiBoardGooglePlayPackageName`).
3. Set `SiutindeiBoardAppStoreConnectAppId` and `SiutindeiBoardGooglePlayPackageName` if they are not
   inside the secrets, plus `SiutindeiBoardAppStoreConnectVendorNumber` for Apple
   downloads. Until at least one store is configured the `stores`
   tools return a clear error; the hourly cache refresh skips them.
4. Reads (`stores_metrics`, `stores_crashes`, `stores_ratings`,
   `stores_list_reviews`) are cached 20 hours and refreshed by
   `SiutindeiBoardCacheRefreshSchedule`. Review text is masked (`contact#hidden` /
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
2. Set `SiutindeiBoardGa4PropertyIds` to a comma-separated list (`123456789,987654321` or
   `properties/123456789,…`). Set `SiutindeiBoardGtmContainers` to
   `accountId:containerId` pairs. Both can also live inside the secret as
   `propertyIds` / `gtmContainers`.
3. Until the SA plus at least one property or container is set, `web` tools
   return a clear error and the hourly cache refresh skips them.
4. Reads (`web_sessions`, `web_conversions`, `web_gtm_status`) are cached
   20 hours and refreshed by `SiutindeiBoardCacheRefreshSchedule`. Page paths are
   masked (`contact#hidden` / `phone#hidden`) before they reach the model.
5. Google Ads (`ads` tool) is T8b. `gtm_propose_publish` is T8c and always
   stays in **Approvals**.

### Shared inbound SES rule set

SES allows only **one** active receipt rule set per region. `lxsoftware`
owns `lxsoftware-inbound-mail` and activates it on deploy. That set must
include every mailbox that receives mail in `ap-southeast-1`:

| Recipient | Raw store | Processor |
|---|---|---|
| `32-hillmarton@inbound.lx-software.com` | `lxsoftware-admin-inbound-mail-…` / `inbound-raw/hillmarton/` | `InboundStatementMailFn` (house `hillmarton`) |
| `the-morrison@inbound.lx-software.com` | same bucket / `inbound-raw/morrison/` | `InboundStatementMailFn` (house `morrison`) |
| `billing@inbound.lx-software.com` | same bucket / `inbound-raw/lx-software/` | `InboundStatementMailFn` (book `lxSoftware`, expenses only) |
| `siutindei-board@inbound.lx-software.com` | same bucket / `inbound-raw/siutindei/` | `board_mail.ingest_raw_object` |
| `invoices@inbound.evolvesprouts.com` | `evolvesprouts-assets-…` / `inbound-email/raw/` | Evolve Sprouts `InboundInvoiceEmailProcessor` |

`lx-software.com` apex MX stays on iCloud. Public address `billing@lx-software.com`
is not an SES recipient; after deploy, forward that iCloud mailbox to
`billing@inbound.lx-software.com` (stack output
`lxsoftware-InboundMailbox-lxSoftware`). PDFs then use the same extract →
assets → `enqueue_parse_statement_async_job` path as the house inboxes, with
`lineTypeOnly=expenditure` so lines land on **LX Software → Expenses**.
Inbound PDFs are written under `inbound/{owner}/{batch}/` in the assets
bucket and get an `ASSET#` META row immediately (original filename, not the
`00_` S3 prefix), so they show on **Assets** even if parse later fails.

Set **`lxsoftware:StatementParseNotifyEmail`** (CDK / `params/*.json`) to
receive an email from `statements@inbound.lx-software.com` when a statement
parse job succeeds or fails. Leave it empty to disable. SES must be able to
send from `InboundMailDomain` to that address (account out of the sandbox,
or the destination verified).

The Evolve Sprouts stack still owns the invoice bucket, SNS topic, SQS
queue, receipt IAM role, and processor. It must **not** call
`SetActiveReceiptRuleSet` on `evolvesprouts-inbound-invoice-email-rule-set`
(that hid hillmarton + board mail). Before this stack activates the
shared set, deploy the companion change in
[evolvesprouts](https://github.com/lx-software-ltd/evolvesprouts) so the
invoice bucket / role / KMS policies allow the shared-set SourceArn
`…:receipt-rule-set/lxsoftware-inbound-mail:receipt-rule/evolvesprouts-inbound-invoice-email-rule`
as well as the old rule-set ARN.

### Board mail (Cloudflare + SES)

The owner's existing `siutindei.com` inbox is unchanged. A Cloudflare Email
Worker copies every message to the board as well. Design:
[`docs/architecture/executive-board-tools-plan.md`](../architecture/executive-board-tools-plan.md) §5.2.

**Read path (no DNS change on `siutindei.com`):**

1. Deploy the `lxsoftware` stack (after the Evolve Sprouts companion above).
   Copy the `SiutindeiBoardMailInboundAddress` output
   (`siutindei-board@<InboundMailDomain>`). The receipt rule stores raw MIME
   under `inbound-raw/siutindei/` and `inbound_email_handler` hands those
   objects to `board_mail.ingest_raw_object`. The stack also activates
   `lxsoftware-inbound-mail`, so you do not run `set-active-receipt-rule-set`
   by hand.
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

1. Set `lxsoftware:SiutindeiBoardMailSendingEnabled=true` and redeploy. The stack
   creates an SES email identity for `SiutindeiBoardMailDomain` and attaches
   `ses:SendEmail` / `ses:SendRawEmail` on `AdminApiFn`, constrained to
   `ses:FromAddress` `*@SiutindeiBoardMailDomain` (SendRawEmail authorizes the
   mailbox identity, not the verified domain ARN, so identity-ARN resource
   lists deny in production). Every SES send grant in the stack uses this
   shape (`sesSendFromDomainStatement`).
2. Add the three `SiutindeiBoardMailDkimCnameN` outputs as CNAMEs on the
   `siutindei.com` zone (Cloudflare proxy **off**).
3. Extend SPF to
   `v=spf1 include:_spf.mx.cloudflare.net include:amazonses.com ~all`.
4. Add `_dmarc` TXT (`v=DMARC1; p=quarantine; rua=mailto:hello@siutindei.com`).
5. In **Executive Board → Settings → Tools & permissions**, set the
   **Recipient allow-list** (`@siutindei.com`, known vendor addresses, and
   WhatsApp numbers). Sends to anyone else stay in **Approvals** even when
   the member is at `act`.
6. Open **Executive Board → Mail**. The header shows what SES itself reports
   (`GetEmailIdentity` + `GetAccount`, cached 10 min): domain verified, DKIM
   status, production access (sandbox accounts can only reach verified
   recipients). Click **Send test email**: one message goes from `hello@` to
   your sign-in address and is not indexed. A refusal shows the full SES
   error, including the resource ARN, inline and in CloudWatch as
   `board_mail_send_failed`. Do this before asking a persona to reply.

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
