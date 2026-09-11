# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

This repository hosts the LX Software public website in `apps/public_www/`, a
separate **admin** SPA in `apps/admin_web/`, and AWS CDK infrastructure in
`backend/infrastructure/`. There is no backend API for the public site; the admin
console calls the `lxsoftware` stack deployed from the same CDK app.

### Running the dev server

```bash
cd apps/public_www && npm run dev
```

The Vite dev server starts on `http://localhost:5173/` with HMR enabled.

### Admin website dev server

```bash
cd apps/admin_web && npm run dev
```

Use a local `.env` copied from `apps/admin_web/.env.example` so `VITE_*` values
resolve (Cognito and API URLs can point to a dev stack or be stubbed for UI-only work).

To exercise every table and tab with fixture rows and no AWS stack:

```bash
cd apps/admin_web && npm run dev:mock
```

That loads `.env.mock`, signs in with a fake admin token, and serves
`src/lib/mock/fixtures.ts` through `adminFetch`. Playwright viewport smoke
tests use the same mode (`npm run test:e2e`).

### Lint / Build / Test

| Command | Directory | Purpose |
|---------|-----------|---------|
| `npm run lint` | `apps/public_www` | ESLint (flat config, TS + React) |
| `npm run build` | `apps/public_www` | TypeScript check + Vite production build |
| `npm run lint` | `apps/admin_web` | ESLint (flat config, TS + React) |
| `npm run build` | `apps/admin_web` | TypeScript check + Vite build |
| `npm run test` | `apps/admin_web` | Vitest + admin Lambda Python unit tests |
| `npm run test:e2e` | `apps/admin_web` | Playwright viewport smoke (fixture API) |
| `npm run dev:mock` | `apps/admin_web` | Vite + fixture admin API (no AWS) |
| `npm run build` | `backend/infrastructure` | Compile CDK TypeScript |

There are no automated test suites for `apps/public_www` or CDK currently.

### Gotchas

- **Admin UI patterns** (tables, editors, money/date formatting): see [`apps/admin_web/docs/UI_COMPONENTS.md`](apps/admin_web/docs/UI_COMPONENTS.md).

- **OpenRouter bill:** LX Software pays one OpenRouter invoice. Each catalog app in `contracts/openrouter-apps.json` has its own named key (`lxsoftware:{app-id}`). This admin’s secret JSON must include `statement-parser` and `executive-board`. Sibling products store their named key in their own secret and tag requests with the catalog `referer` / `title` / `user {id}:{workload}`. Mint with `python3 scripts/mint-openrouter-app-keys.py`. Book UTC spend from **LX Software → Dashboard → OpenRouter** (current month-to-date plus the previous 12 months). See [`docs/deployment/admin-website.md`](docs/deployment/admin-website.md).

- **AWS bill:** LX Software pays one AWS invoice for this account (Siu Tin Dei and Evolve Sprouts share it). Cost Explorer splits UnblendedCost by activated cost-allocation tags `Organization` and `Project` (`contracts/aws-billing.json`). AWS's own invoice PDF is one account total; **LX Software → Dashboard → AWS** (`GET /aws/usage` and `GET /aws/usage.pdf`) is the tagged split, defaulting to the last complete UTC month with the same 12-month dropdown. See [`docs/deployment/admin-website.md`](docs/deployment/admin-website.md).

- **Currencies (admin):** supported codes are GBP, HKD, USD, EUR, CNY, SGD, AED. Global default is HKD; each house can set `defaultCurrency` on its finance record. Use `CurrencySelect` and `src/lib/currencies.ts`; the admin Lambda validates the same set on finance writes.
- **Shared contracts:** cross-app constants live in `contracts/*.json`. After editing, run `python3 scripts/sync-contracts.py` and `python3 scripts/check-contracts.py` (also enforced in CI).

- The public website fetches `/content.json` at runtime (served from `public/content.json` in dev). If you see missing content, ensure that file exists.
- The admin SPA requires `VITE_*` Cognito and API settings; see `apps/admin_web/.env.example`.
- **Public read-only API keys:** `/public/{finance,finance/quotes,records,fx/v2/rates}` GET routes accept an `x-api-key` header validated by `backend/lambda/public_api_authorizer/` (scrypt digest lookup in the records table, `pk=APIKEY#<digest>`). Mint/list/revoke with `scripts/manage-public-api-keys.py`; docs in `docs/deployment/admin-website.md`. Write routes stay Cognito-JWT only.
- Admin tokens are stored in **sessionStorage**; closing the browser tab ends the session and requires signing in again.
- CDK synth/deploy requires AWS credentials and is not needed for local website development.
- `apps/public_www`, `apps/admin_web`, and `backend/infrastructure` use npm (lockfiles are `package-lock.json`).
- **Enable Banking sync:** the admin Banking page (`/banking`) links PSD2 bank accounts through Enable Banking and refreshes accounts-sheet balances (manual "Sync now" + daily EventBridge rule). JWTs are signed by the `lxsoftware-admin/enable-banking` KMS key (`backend/lambda/admin/bank_sync.py`); the feature is off until the `EnableBankingAppId` stack parameter is set. Setup steps in `docs/deployment/admin-website.md`.
- **Executive Board (admin):** the Siu Tin Dei page has an "Executive Board" tab backed by `/siu-tin-dei/board/*` routes on `AdminApiFn`. Personas, meeting modes and limits are contract-driven (`contracts/executive-board.json`, `contracts/board-timeouts.json`); the roster is a **fixed eight roles** (no add/remove) with owner-editable vision/mission/mandate stored as overrides. Backend modules are `backend/lambda/admin/board_*.py` (tests in `test_board.py`); all LLM calls go through `openrouter_client.py` and are metered against a daily budget. Board rows use the `BOARD#` pk prefix and are filtered out of the generic `/records` scan. Setup (GitHub token secret, model params, schedules) in `docs/deployment/admin-website.md`.
- **Executive Board staff (WP1):** background tasks. Dual kill switch: `SiutindeiBoardStaffEnabled` (default `false`, fail-closed — unset is off) and `settings.staff.enabled` (default `false`). Both `AdminApiFn` and inbound-mail carry the flag. Tick schedule `lxsoftware-admin-siutindei-board-staff-tick` every 5 minutes. Contract `contracts/board-staff.json`. Scratchpads and deliverables live in S3 under `board/siuTinDei/staff/{taskId}/` (in-memory fallback only when `ASSETS_BUCKET_NAME` is unset, for unit tests). Default-on seats: `support`, `provider-success`, `community-manager`, `business-analyst`. `maxRunningTasksDefault` is 3. Other seats stay off until the owner flips them (runbook in `docs/deployment/admin-website.md`).
- **Executive Board holds (WP2):** act-level writes with a non-zero `settings.boundaries.holds` class are scheduled (`held`) instead of executed. The owner vetoes from **Approvals → Scheduled**. Hold 0 and propose-level calls stay on today's path. When staff is on, `always_propose` publish ops become 24 h holds; `code_production` stays an Approval. Tick sweep evaluates breakers, then `expire_stale`, then `execute_due`. Hold execution re-checks level, `act_guard`, breakers and the tools kill-switch. Approvals and holds stay separate lists.
- **Executive Board triage (WP3):** inbound mail, Meta events and new store reviews create staff tasks when both staff flags are on. Default-on seats: `support`, `provider-success`, `community-manager`. Reply policy is an `act_guard` (Approvals); quiet hours schedule a hold until 08:00 HKT instead of refusing. Escalations are `needs_owner` plus the `ack_escalation` template (enqueued to `AdminApiFn` via `invoke_async`). Bulk/`Auto-Submitted` mail is skipped.
- **Executive Board review (WP4):** Daily review page + 07:15 compile / 07:30 digest (`board@siutindei.com` → `settings.review.digestTo`). Breakers (`class:`, `channel:`, `budget`, `tool:`) evaluate on the staff tick. Lessons from veto / return / “this was wrong” are confirmed into seat prompts. `business-analyst` is active by default; `maxRunningTasks` default is 3.
- **Executive Board market (WP5):** Watchlist crawl 03:00 HKT and Monday 04:00 HKT discovery + market-analyst brief (`board_intel.py`). Changes become notes; the brief JSON writes `intel:gaps` and CPO `later` actions. **Market** section on the board tab. `market-analyst` starts inactive. Crawl refuses private/link-local hosts; `intel_fetch_page` is watchlist-only.
- **Executive Board outreach (WP6):** Prospects, sequences and cold-outreach holds. Dual staff flags still required. Places (Enterprise SKUs) + FEHD/EDB open data. Sends from `partnerships@{OutreachSendingDomain}` with HTTPS-only List-Unsubscribe; public `GET/POST /public/outreach/unsubscribe/{token}` has no JWT. SES IAM includes both configuration-set ARNs. Config set → SNS → SQS `lxsoftware-admin-siutindei-outreach-events`. Daily 08:00 HKT `…-board-targets`. **Pipeline** section. `prospector` starts inactive. Owner DNS/Places key/SES verify stay owner tasks.
- **Executive Board content (WP7):** Calendar + Pillow cards (`backend/lambda/admin/fonts/` Regular files only, `brand/`). `content_publish` holds until `max(slotAt, now+classHours)`. Sunday 18:00 HKT plan and Monday 09:00 HKT readout. `AdminApiFn` memory is 1536 MB; `requirements.txt` pins Pillow (Docker arm64 bundling; any workflow that runs `cdk deploy`/`cdk diff` on x86-64 must register QEMU via `docker/setup-qemu-action` first, or set `CDK_SKIP_PYTHON_PIP=1` for template-only synth). **Content** section. `content-marketer` and `growth-specialist` start inactive.
- **Executive Board newsletter (WP8):** Double opt-in `POST /public/newsletter/subscribe` plus confirm/unsubscribe tokens (no JWT). Issues send via SES `SendBulkEmail` after a `publish:newsletter` hold, from `news@{SiutindeiBoardMailDomain}`. Config set `lxsoftware-admin-siutindei-newsletter` shares the WP6 SQS path (routed by tag; `reportBatchItemFailures`). Public site `NewsletterForm` needs `VITE_PUBLIC_API_URL` (CI reads `vars.ADMIN_API_BASE_URL`) and stack parameter `PublicSiteOrigins`. Subscriber key is `{list}#{digest}`.
- **Executive Board duties (WP9):** `accountant`, `data-analyst` and `security-analyst` start inactive. Seat `duties[]` (HKT cron) run from the staff tick when `settings.staff.dutiesEnabled` is on. Hourly cache refresh diffs CloudWatch ALARM names and new security/GitHub alert ids into architect/CTO and security-analyst tasks. Dunning creates an accountant task instead of a reminder Approval when staff is on. Stand-up `boundarySuggestions` land on the daily review.
- **Executive Board engineering (WP10):** Tool `code` (`board_code.py`) dispatches siutindei Actions workflows. `code_merge_staging` stays `always_propose` until Appendix A workflows exist; then it is a 12 h `code_staging` hold after CI + architect accept (`headSha`) + path/size guards. `code_promote` is `code_production` (always an Approval). Architect / engineer-1 / engineer-2 / product-dev start inactive. GitHub token needs `actions: write`. Workflows themselves live in the siutindei repo (appendix A).
- **`AdminApiFn` invoke permissions (CDK):** the HTTP API uses `SharedPermissionLambdaIntegration` plus a single API-wide `AdminApiInvoke` permission; do not switch back to `HttpLambdaIntegration` per-route permissions or add `events.Rule` Lambda targets to `AdminApiFn` — the function's resource-based policy is capped at 20 KB and per-route/per-rule statements exceeded it. Use EventBridge Scheduler (IAM-role target) for new schedules.
- **Executive Board tools:** board members can call tools (GitHub, board records, mail, research, AWS, security, product, meta, finance, stores, web) through OpenRouter function calling (`backend/lambda/admin/board_tools.py`). Access is `off`/`read`/`propose`/`act` per tool per member, capped by a global mode; `propose` writes land in **Executive Board → Approvals**. Add a tool by registering `ToolOp`s in `board_tools.py`, adding the tool to `contracts/board-tools.json` (then run the contract sync), and covering it in `test_board_tools.py` / `test_board_t2.py` / `test_board_t4.py` / `test_board_t5.py` / `test_board_t6.py` / `test_board_t7.py` / `test_board_t8.py` (mail in `test_board_mail.py`) with a fake behind the `HostRouter` or `board_data_api.set_executor_for_tests`. Cheap AWS/security/stores/web reads refresh hourly (`internal: board_cache_refresh`). Receivables mirror nightly and dunning daily (`internal: board_receivables_mirror` / `board_dunning`). Kill switch: `SiutindeiBoardToolsEnabled` stack parameter. Default global mode is `propose`; `act` is owner-gated by the allow-list (email / `@domain` / E.164 phone) and Meta ads spend caps (`settings.tools.spendCaps`). Details in `docs/architecture/executive-board-tools-plan.md`.
- **Executive Board stores:** App Store Connect JWT (ES256) and Google Play service-account token live in CDK-created Secrets Manager secrets (`lxsoftware-admin-siutindei-board-app-store-connect-key`, `lxsoftware-admin-siutindei-board-google-play-sa`; replace the dummy values in the console). CMO may **act** on `stores_reply_review`; `stores_draft_release_notes` always proposes. Daily metrics cache 20 h and refresh on the hourly `board_cache_refresh` schedule.
- **Executive Board web:** GA4 Data API + GTM live version (`board_web.py`). Dedicated service account (`lxsoftware-admin-siutindei-board-google-analytics-sa`), not the Play key. Several properties (`SiutindeiBoardGa4PropertyIds` CSV) and containers (`SiutindeiBoardGtmContainers` as `account:container`). Cached 20 h on the hourly refresh. Google Ads is T8b; GTM publish is T8c (always Approvals).
- **Executive Board Meta webhook:** `GET/POST /webhooks/meta/siutindei` is the canonical **non-JWT** route (`/webhooks/meta` stays for an already-subscribed app). GET is the Meta verify handshake (`SiutindeiBoardMetaVerifyToken`); POST is checked with `X-Hub-Signature-256` (`lxsoftware-admin-siutindei-board-meta-app-secret`). Payloads are masked into `BOARD#…#meta#` rows; no LLM work in that path. Enable WhatsApp **coexistence** so the owner's phone keeps the number. WhatsApp `act` is only inside the 24-hour window and only to the allow-list. Meta ads `act` (`create_ad_set`, `boost_post`) is only while recorded commitment plus Graph month-to-date spend fits the owner-set daily / monthly caps.
- **Executive Board receivables:** listing plans/subscriptions/invoices/payments live in siutindei Aurora (`scripts/siutindei/receivables.sql`, apply in that repo). `AdminApiFn` reaches them via the RDS Data API (`SiutindeiClusterArn` + `SiutindeiDbSecretArn`). Product tools SELECT `v_catalog_health` / `v_funnel_daily` / `v_provider_pipeline` only. Issued invoices and matched payments are mirrored into the Siu Tin Dei statement book with stable `recv-inv-*` / `recv-pay-*` ids. Bank ingest is T4b (HK account not opened).
- **Executive Board mail:** every `siutindei.com` mailbox is copied by `scripts/cloudflare/siutindei-mail-fanout.js` to `siutindei-board@<InboundMailDomain>`; SES stores MIME under `inbound-raw/siutindei/` and `inbound_email_handler` branches that prefix to `board_mail.ingest_raw_object`. Personas see `contact#N` / `phone#N` aliases (`board_pii.py`); the owner always sees real addresses in **Executive Board → Mail**. Outbound send is off until `SiutindeiBoardMailSendingEnabled=true` plus DKIM/SPF/DMARC; recipients outside the allow-list always require approval. **SES IAM:** every send grant is `Resource: *` + `ses:FromAddress *@<domain>` (`sesSendFromDomainStatement` in the stack) — SES authorizes `SendRawEmail` against the *mailbox* identity, so identity-ARN resource lists pass CDK tests and deny in production. Verify sending with **Mail → Send test email** (`POST /siu-tin-dei/board/mail/selftest`, SES health badges from `GetEmailIdentity`/`GetAccount`) before debugging via persona approvals. Setup in `docs/deployment/admin-website.md` → “Board mail”.
- **Shared inbound SES:** one active receipt rule set per region. `lxsoftware-inbound-mail` hosts hillmarton, morrison, LX Software `billing@inbound.lx-software.com` (iCloud-forward `billing@lx-software.com` here; parses as `lxSoftware` expenses), `siutindei-board`, and Evolve Sprouts `invoices@inbound.evolvesprouts.com`. The `lxsoftware` stack activates that set on deploy. The evolvesprouts stack must allow the shared-set SourceArn and must not call `SetActiveReceiptRuleSet` on its own set.
- **Statement PDF import:** the admin SPA polls parse jobs for up to eight minutes (`useParseStatement.ts`), aligned with the `lxsoftware` stack Lambda timeout (300s), `OPENROUTER_TIMEOUT_SECONDS` (210s), and `PARSE_JOB_STUCK_SECONDS` (420s) on `AdminApiFn`. Change those together if you extend OCR-heavy parsing.
