# Executive Board — tools and connectors

Status: **approved; T1–T8 shipped** (tool loop, `github` / `board` /
`mail` / `research` / `aws` / `security` / `product` / `meta` / `finance` /
`stores` / `web` tools, permission matrix, approvals queue, email ingest, Mail view,
receivables + Data API, Meta webhook, App Store Connect + Google Play,
GA4 + GTM reads, hourly cache refresh, nightly statement-book mirror, daily dunning, `act`
allow-lists and ads caps — see
§10). T4b, T8b and T8c remain proposals. This
document extends [`executive-board-plan.md`](./executive-board-plan.md) (the
board itself, shipped) with the ability for each board member to **seek
information and take action through tools** instead of relying only on the
context pack.

Where T1 lives in the code:

| Piece | Location |
|-------|----------|
| Contract (tool ids, levels, default matrix, loop limits) | `contracts/board-tools.json` → `contract_constants.py`, `src/lib/contracts/generated.ts` |
| Function calling in the OpenRouter client | `backend/lambda/admin/openrouter_client.py` (`tools`, `tool_choice`, `ToolCall`, `extract_tool_calls`) |
| Registry, levels, loop, audit rows, approvals | `backend/lambda/admin/board_tools.py` |
| GitHub operations (7 read, 3 write) | `backend/lambda/admin/board_github.py` (`op_*`) |
| Persistence (`BOARD#APPROVAL#`, `BOARD#TOOLCALL#`, `settings.tools`) | `backend/lambda/admin/board_store.py` |
| Routes `/board/tools`, `/board/tools/calls`, `/board/approvals[/{id}/approve\|reject]` | `backend/lambda/admin/board_routes.py`, `lxsoftware-stack.ts` |
| Kill switch | `BoardToolsEnabled` stack parameter → `BOARD_TOOLS_ENABLED` on `AdminApiFn` |
| SPA | `BoardToolsCard`, `BoardApprovalsList`, `BoardToolCallList`, `BoardMailView`, `BoardReceivablesView`; hooks `useBoardTools`, `useBoardApprovals`, `useBoardMail`, `useBoardReceivables` |
| Mail ingest, SES send, PII aliases | `backend/lambda/admin/board_mail.py`, `board_pii.py`; S3 prefix `inbound-raw/siutindei/` |
| Cloudflare fan-out | `scripts/cloudflare/siutindei-mail-fanout.js` |
| Tests | `backend/lambda/admin/test_board_tools.py`, `test_board_mail.py`, `test_board_t2.py`, `test_board_t4.py`, `test_board_t5.py`, `test_board_t6.py`, `test_board_t7.py`, `test_board_t8.py` |
| T2 reads | `board_research.py`, `board_aws.py`, `board_security.py`, `board_cache.py`; `BOARD#…#cache`; `SiutindeiBoardCacheRefreshSchedule` |
| T4 receivables | `board_data_api.py`, `board_receivables.py`, `board_product.py`; `scripts/siutindei/receivables.sql`; `SiutindeiBoardReceivablesMirrorSchedule`, `SiutindeiBoardDunningSchedule` |
| T5 Meta | `board_meta.py`; unauthenticated `GET/POST /webhooks/meta/siutindei` (legacy `/webhooks/meta`); `BOARD#…#meta#` rows; `MetaBoardToken` / app secret |
| T6 stores | `board_stores.py`; App Store Connect JWT + Play service account; review replies; hourly `stores:*` cache |
| T8 web | `board_web.py`; dedicated Analytics SA; multi-property GA4 + multi-container GTM live version; hourly `web:*` cache |

## 1. Decisions already taken by the owner

| Topic | Decision |
|-------|----------|
| Permission model | Three levels per tool per role: **Read**, **Propose** (drafts an action the owner approves), **Act** (executes directly, within caps). Read-only stays available as a global switch. |
| Repository | `lx-software-ltd/siutindei` is public by design; reads need no token, writes do. |
| Market | Hong Kong only. Physical **stores/venues** are first-class, not just online listings. |
| Tool interaction | **Rich**: live tool calls inside chat replies and meeting phases, not a pre-computed snapshot. |
| Budget | Daily OpenRouter cap rises to pay for tool loops (see §7). |
| Email | **All `siutindei.com` mailboxes** are visible to the board. |
| Meta / WhatsApp | The board **owns the existing WhatsApp number** through the WhatsApp Cloud API, plus the Facebook Page and Instagram account. |
| Receivables | Live in the **siutindei Aurora database** (new tables) and are **mirrored into the Siu Tin Dei statement book** in this admin app. |
| Bank feed | The business account will be at a **Hong Kong bank** (not opened yet; FPS receipts are expected) → see §5.6 for why Enable Banking does not apply and what replaces it. |
| Mail hosting | `siutindei.com` MX records point at Cloudflare Email Routing (confirmed via DNS); no DMARC record exists yet. |
| AWS account | siutindei runs in the **same AWS account** as the `lxsoftware` stack; no cross-account roles. |
| Meta | A Business Manager grouping the Page, Instagram and the WhatsApp number will be set up by the owner. |
| App stores | App Store Connect API key and Google Play service account **already exist**. |
| Listing prices | Not decided yet; `listing_plans` starts empty and the CFO's first task is a pricing proposal (§5.5). |

## 2. Permission model and guardrails

### 2.1 Levels

| Level | Meaning | Examples |
|-------|---------|----------|
| `read` | Fetch and summarise. No side effects, no cost beyond tokens. | List open GitHub issues, read yesterday's WhatsApp threads, pull App Store crash counts |
| `propose` | The tool call produces a **pending action** in the owner's approval queue. Nothing leaves the system until the owner clicks Approve. | Draft a reply to a parent, draft an invoice, draft a GitHub issue, draft an Instagram post |
| `act` | Executes immediately, logged, subject to per-tool caps and allow-lists. | Reply inside an open WhatsApp window, comment on a GitHub issue, send a dunning reminder to a provider already on the allow-list |

Rules that hold for every tool:

- Levels are set **per role per tool** in the Executive Board settings card.
  Defaults are in §6; the owner can lower any of them at any time.
- A **global mode** switch (`readOnly` / `propose` / `act`) caps every role.
  Shipping default is `propose`; `readOnly` is one click.
- **Spend** is a separate cap, not a level: any tool that moves money (ads,
  paid API quota, SES volume) has a **daily and monthly USD ceiling** the LLM
  cannot see or change; hitting it degrades the tool to `propose`.
- **Allow-lists** for outbound messaging: email and WhatsApp `act` are only
  honoured for recipients the owner has marked as approved (providers,
  vendors). Anyone else is always `propose`.
- **Never** available to any role, at any level: pushing code, merging PRs,
  changing IAM/DNS/Cognito, initiating bank payments, deleting data,
  altering the board's own permissions or budgets.
- Every call is written to an **audit log** (`BOARD#TOOLCALL#`) with role,
  meeting/chat id, arguments, result digest, cost, level, and — for
  `propose`/`act` — the pending action id or outcome.
- **Kill switch**: `BOARD_TOOLS_ENABLED=false` on `AdminApiFn` or the
  settings toggle stops all tool calls without a deploy.

### 2.2 Approval queue (frontend)

A new **Approvals** section on the Executive Board tab lists pending
`propose` actions: who proposed it, why (linked transcript turn), the exact
payload (email body, message text, invoice lines, issue title/body), and
Approve / Edit / Reject buttons. Approving runs the action with the owner's
identity recorded on the audit row. Rejections are fed back into the next
meeting's context pack so the board learns what was refused.

### 2.3 PII handling

Parent conversations (WhatsApp, email) contain names and phone numbers.
Before any text reaches OpenRouter the tool layer masks phone numbers and
email addresses to stable pseudonyms (`parent#17`) and un-masks them only in
the approval payload rendered to the owner. OpenRouter data-collection
denial from the existing client stays on. Message bodies are stored with a
90-day TTL; aggregates (counts, response times) are kept.

## 3. How tool calling works

- **Protocol**: OpenRouter function calling (`tools` / `tool_calls` on the
  chat completions API). `openrouter_client.py` grows a `tools=` parameter
  and returns parsed tool calls; the parser regression tests are extended.
- **Loop**: `board_tools.py` runs up to `maxToolRoundsPerTurn` (contract,
  default 4) rounds per persona turn: model → tool calls → results → model.
  Each round is capped in tokens; results are truncated to
  `toolResultMaxChars` before re-entering the prompt.
- **In meetings**: during the *positions* and *debate* phases each persona
  may call tools. The phase timeout in `board-timeouts.json` rises to allow
  it, and the meeting engine records tool calls as transcript entries of a
  new type `tool` so the owner can see who looked at what.
- **In chat**: the reply job runs the same loop; the offcanvas shows a
  "Looking at GitHub issues…" line per tool call while polling.
- **Registry**: each tool declares `name`, JSON schema, `level` required,
  `roles` allowed, `costUsd` estimate, and an executor. Tool availability is
  filtered by role and by the current permission matrix **before** the
  schemas are sent to the model, so a role never sees tools it cannot use.
- **Execution**: tool executors run inside `AdminApiFn` with short
  timeouts (`toolCallTimeoutSeconds` 10 s default; `toolCallTimeoutSlowSeconds`
  25 s for GitHub search / file / security alerts and Meta insights,
  comments, ad spend and WhatsApp templates). Slow or failing tools return
  a structured error the model can reason about.
- **Wall-clock budget**: a persona turn is bounded by `chatToolLoopMaxSeconds`
  (120 s) or `meetingToolLoopMaxSeconds` (60 s). Every model call inside the
  loop is capped at the smaller of the OpenRouter timeout and the seconds
  left; ops late in the turn are clamped the same way; calls requested after
  the deadline are answered with a structured "time budget exhausted" error;
  the final answer call gets at least 45 s. A chat turn therefore ends within
  ~165 s (below `chatPollDeadlineMs` 270 s and the 300 s Lambda) and a
  meeting member within ~105 s. The daily budget is re-checked before every
  tool round, not only before the turn.

## 4. Connector inventory

| Id | Source | Read | Propose | Act | Notes |
|----|--------|------|---------|-----|-------|
| `github` | `lx-software-ltd/siutindei` | issues, PRs, commits, Actions runs, releases, file/tree, Dependabot + code-scanning alerts, discussions | new issue, issue comment, label change | issue comment, label change | Token in Secrets Manager (already provisioned as `GITHUB_READ_TOKEN_SECRET_ARN`; needs `issues:write` for `act`) |
| `product` | siutindei Aurora (read replica or Data API) | catalog counts by district/category/age, providers and **stores** with completeness score, search and view analytics, booking/lead funnel, provider sign-ups | flag listing for review | — | Read via RDS Data API with IAM auth (same AWS account) |
| `stores` | App Store Connect API, Google Play Developer API | downloads, installs, crashes, ratings, review text, review status | reply to review, release notes draft | reply to review | Two key pairs in Secrets Manager; App Store Connect JWT signed in Lambda |
| `web` | GA4 Data API + GTM (several properties / containers) | sessions, top pages, referrers, conversions, live container version | GTM publish (T8c) | — | Dedicated service account; see §5.8 |
| `ads` | Google Ads (T8b) | spend, campaigns | new campaign | campaign within USD 50 / month cap | Developer token + OAuth; not the Analytics SA |
| `mail` | All `siutindei.com` mailboxes | thread list, thread body, attachment names (PDF text not extracted), sender history | reply, new email, forward to provider | reply/new email to allow-listed recipients | Design in §5.2 |
| `meta` | Facebook Page, Instagram, WhatsApp Cloud API | Page/IG insights, comments, DMs, WhatsApp threads, template status, ad account spend and results | post, story, reply to comment/DM, WhatsApp reply outside 24-h window (template), new ad set | reply inside open WhatsApp window, reply to comments, boost within cap | Design in §5.3 |
| `finance` | This admin app's Siu Tin Dei finance sheets + receivables | balances, cash-flow, subscriptions, invoices, overdue list, unit economics | create invoice, send invoice, dunning reminder, price change proposal | send dunning reminder to allow-listed provider | Design in §5.4–5.6 |
| `research` | Web search API (Brave Search or OpenRouter `:online` models) | competitor pages, HK market news, EDB/holiday calendars, venue listings | — | — | Read-only; results cached 24 h |
| `aws` | Cost Explorer, CloudWatch, Health for the siutindei stack(s) | monthly cost by service, alarms in ALARM, error rates, Lambda durations | budget alert proposal | — | Read-only IAM policy scoped to the siutindei stack tags |
| `security` | GitHub security tab, AWS Security Hub / IAM Access Analyzer, Cognito | open alerts, findings by severity, MFA adoption, failed sign-ins, exposed secrets scan | open GitHub issue with remediation | — | Read-only; remediations always via `propose` |
| `board` | The board's own records | actions, minutes, charters, previous tool results | new action item, reprioritise | update own action status | Already partly present as context pack; becomes callable |

## 5. Connector designs

### 5.1 GitHub

Reuses `board_github.py`. The snapshot stays as the cheap always-on view;
tools add on-demand `search_issues`, `get_issue`, `list_pull_requests`,
`get_workflow_runs`, `get_file`, `list_security_alerts`. Writes use one
fine-grained token restricted to the `siutindei` repo with `issues: write`,
`pull_requests: read`, `contents: read`, `security_events: read`. The
CDK-owned `lxsoftware-admin-siutindei-board-github-token` secret **is** the
board token (dummy value on first deploy; replace it in Secrets Manager).
`lxsoftware-admin-github-read-token` is reserved for a future LX Software
board. There is no separate `GitHubBoardToken` parameter.

### 5.2 Email — every `siutindei.com` mailbox

Goal: the board reads every mailbox; nothing about the owner's own mail
client changes.

1. **Ingest**: `siutindei.com` mail is handled by **Cloudflare Email
   Routing** (MX `route1/2/3.mx.cloudflare.net`, SPF
   `include:_spf.mx.cloudflare.net`). Plain routing rules deliver to one
   destination each, so the copy is made by a small **Email Worker** bound
   to the catch-all: it forwards every message to the owner's existing
   destination inbox *and* to `siutindei-board@inbound.lx-software.com`,
   preserving the original `To:` so the mailbox is known downstream.
   Cloudflare requires destination addresses to be verified; the
   verification mail lands in the SES S3 bucket, where the owner reads the
   link once. `inbound.lx-software.com` already has MX → SES in the stack
   region and the `lxsoftware-inbound-mail` receipt rule set; a new
   receipt rule for `siutindei-board@…` stores raw MIME under
   `inbound-raw/siutindei/`. No DNS change on `siutindei.com` is needed
   for reading.
2. **Index**: a new S3 event branch in `inbound_email_handler.py`
   (`board_mail.py`) parses headers, text body and `text/*` attachments (PDF
   attachments are listed by name only; their text is not extracted because
   no local PDF reader ships in the Lambda bundle — see §12), masks PII
   (§2.3) and writes
   `BOARD#MAIL#<threadId>` / `MSG#<ts>` rows plus a per-mailbox unread
   counter. Bank alert emails (§5.6) are routed from here to the receivables
   matcher.
3. **Send**: verify `siutindei.com` for **sending** in SES: three DKIM
   CNAMEs, SPF extended to
   `v=spf1 include:_spf.mx.cloudflare.net include:amazonses.com ~all`, and a
   new `_dmarc` TXT record (`p=quarantine`, reports to the board mailbox) —
   the domain has no DMARC today, which the CISO would flag on day one.
   Replies go out from the mailbox they were addressed to, with `Reply-To`
   unchanged so the owner's client keeps the thread. All outbound is BCC'd
   back into the index.
4. **Levels**: CEO/COO/CMO/CFO `propose` by default; `act` only to
   allow-listed providers and vendors. CISO reads only, and gets
   `mail_report_phishing` (available at mail **read**) that always queues
   to Approvals and, once approved, opens a now-priority action.

### 5.3 Meta — Facebook Page, Instagram, WhatsApp on the existing number

- **Meta app**: one Business-type app under the Siu Tin Dei Business
  Manager with `pages_read_engagement`, `pages_manage_posts`,
  `pages_messaging`, `instagram_basic`, `instagram_manage_comments`,
  `instagram_content_publish`, `instagram_manage_insights`,
  `whatsapp_business_messaging`, `whatsapp_business_management`,
  `ads_read`, `ads_management`. Publishing, messaging and ads permissions
  require **App Review** with screencasts; until approved the app works for
  admins of the Business only, which is enough for the owner. A System User
  long-lived token lives in Secrets Manager (`MetaBoardToken`).
- **WhatsApp number**: moving the number to the Cloud API means the phone
  app can no longer send from it unless Meta's *coexistence* mode is
  enabled for the account. Recommended: enable coexistence so the owner's
  phone keeps working while the board reads and replies through the API.
  If coexistence is unavailable for the account, the number moves fully to
  the API and the owner replies from the Approvals section.
- **Inbound**: unauthenticated HTTP routes `POST /webhooks/meta/siutindei`
  (canonical) and `POST /webhooks/meta` (already-subscribed apps) on the
  admin API, verified by `X-Hub-Signature-256` with the app secret,
  plus the `GET` verify handshake. Payloads are queued to `BOARD#META#`
  rows (masked) and acknowledged within the 20 s Meta limit; no LLM work in
  the webhook path. This is the first non-JWT route on the admin API and
  is documented as such in `admin-website.md`.
- **Lead flow**: the public site's WhatsApp CTA reaches Siu Tin Dei, not
  the provider. The COO tool `relay_lead` drafts the hand-off to the
  provider (email or WhatsApp template) and a confirmation to the parent;
  both are `propose` until the owner promotes them. Replies to a parent are
  `act` only inside the 24-hour customer-service window; outside it the
  tool switches to `propose` with a pre-approved template.
- **Spend**: `create_ad_set` and `boost_post` honour owner-set daily
  (`metaAdsDailyUsd`, default 10) and monthly (`metaAdsMonthlyUsd`, default
  50) caps on the Tools card. Hitting either (recorded board commitment plus
  Graph month-to-date spend) downgrades the call to `propose`. `act` runs
  when the global mode is `act` and the proposed budget still fits. This
  supersedes the "new ad set: propose" cell in §4: an ad set inside both caps
  may run at `act`; one that would breach a cap is always a proposal.

### 5.4 Receivables — paid listings, paid offline

Providers pay for listings but pay by bank transfer. The data model lives
in the **siutindei Aurora database** so the product can show billing state
to providers later; the admin app mirrors it into the finance book.

New tables (siutindei repo, its own migration):

| Table | Key columns |
|-------|-------------|
| `listing_plans` | `id`, `name`, `price_hkd`, `billing_period` (`monthly`/`annual`), `active` |
| `listing_subscriptions` | `id`, `organization_id`, `store_id` (nullable), `plan_id`, `starts_on`, `renews_on`, `status` (`trial`/`active`/`past_due`/`cancelled`), `payer_contact` |
| `invoices` | `id`, `subscription_id`, `number` (`STD-2026-0001`), `issued_on`, `due_on`, `amount_hkd`, `status` (`draft`/`sent`/`paid`/`overdue`/`void`), `fps_reference`, `pdf_key` |
| `payments` | `id`, `invoice_id` (nullable until matched), `received_on`, `amount_hkd`, `payer_name`, `bank_reference`, `source` (`alert_email`/`statement`/`manual`), `matched_by` |

Access from `AdminApiFn` is through the **RDS Data API** with IAM
authentication (no VPC attachment, no connection pooling). siutindei runs
in the same AWS account, so this is a direct `rds-data:*` policy on the
cluster ARN plus `secretsmanager:GetSecretValue` on its DB secret, both
imported into the `lxsoftware` stack as parameters. Writes are limited to
`invoices`, `payments`, and `listing_subscriptions.status`.

**Mirror**: a nightly Scheduler job (`board_receivables_mirror`) writes
issued invoices as receivable rows and matched payments as income rows into
the Siu Tin Dei finance sheet (`finance_store.py`). Idempotence is by line
id: invoice lines are `recv-inv-<invoiceId>`, payment lines
`recv-pay-<paymentId>`, every line carries `source: "receivables"`; each run
computes the full desired set, upserts by id and removes `recv-*` lines that
are no longer desired (a paid invoice keeps only its payment line). Manual
lines are never touched.

### 5.5 CFO / COO finance tools

| Tool | Level (default) | What it does |
|------|-----------------|--------------|
| `list_subscriptions`, `list_invoices`, `aging_report` | read | Standard receivables views incl. DSO, past-due by provider |
| `unit_economics` | read | Revenue per provider/store, cost per acquisition from `aws` + `meta` spend, gross margin |
| `draft_invoice` | propose | Creates a `draft` invoice with a unique FPS reference; PDF is rendered in `AdminApiFn` and stored under `board/siuTinDei/invoices/` on the assets bucket |
| `send_invoice` | propose → act for allow-listed payers | Emails the invoice from `billing@siutindei.com` |
| `send_reminder` | propose → act for allow-listed payers | Dunning at D+7 / D+21 / D+35, email or WhatsApp template |
| `match_payment` | act | Attaches a `payments` row to an invoice when reference and amount agree; otherwise `propose` with candidates |
| `propose_price_change` | propose | Writes a `listing_plans` change for approval. No prices exist yet, so the CFO's seeded first action is a pricing proposal (tiers, monthly vs annual, store add-on) built from `product` counts and `research` on HK competitors; approving it creates the first plan rows |
| `record_manual_payment` | propose | For cash or cheque handed over in person |

### 5.6 Bank feed for a Hong Kong account

**Enable Banking does not cover Hong Kong.** It aggregates PSD2 banks in
30 European countries; Hong Kong's HKMA Open API Framework is voluntary per
bank and has no third-party access regime, so no aggregator offers account
information for HSBC HK, Hang Seng, BOC HK, Standard Chartered HK or the
virtual banks. The existing Enable Banking sync stays for the UK accounts.

The HKD business account **has not been opened yet**; FPS receipts are
expected once it is. That makes the choice of bank part of this plan:

| Option | Feed | Effect on the board |
|--------|------|---------------------|
| **API-first business account** (Airwallex, Statrys, Aspire — all HKD, FPS-enabled, HK-licensed as SVF/MSO rather than banks) | Transactions and balances via REST API with webhooks | `payments` rows appear within minutes with no parsing; `match_payment` is fully automatic. Recommended if the account is only used for listing income. |
| **Traditional bank** (HSBC, Hang Seng, BOC HK, SCB, or a virtual bank such as ZA / Mox / livi) | Email alerts + monthly e-statement, see below | Works, but depends on the bank's alert template and needs a parser per bank. |

If the traditional route is chosen, the feed comes from the bank's own
outputs:

1. **Payment alert emails** (primary, near real time). Enable "incoming
   FPS / transfer" email alerts at the bank and address them to
   `finance@siutindei.com`. Since that mailbox is already ingested (§5.2),
   `board_mail.py` recognises the bank's alert template, extracts amount,
   reference, payer and timestamp, and creates a `payments` row with
   `source=alert_email`. `match_payment` runs immediately.
2. **Monthly e-statement** (source of truth). The bank's PDF or CSV
   statement, emailed or uploaded, goes through the existing OpenRouter
   statement parser into a Siu Tin Dei book. A reconciliation step compares
   parsed credits with `payments` rows, adds missing ones with
   `source=statement`, and lists discrepancies for the CFO's next stand-up.

Either way the `payments` table and `match_payment` tool are the same; only
the ingest adapter (`board_bank_api.py` vs the mail/statement path) differs,
so milestone T4 can ship with `record_manual_payment` only and gain the
adapter once the account exists. Choosing the account is itself a good
first agenda item for the CFO (`research` tool: fees, FPS support, API
availability, onboarding requirements for an HK-incorporated company).

No payment initiation of any kind is built; the board never moves money
out of the account.

### 5.7 Product analytics from siutindei

Read-only SQL views (created in the siutindei repo) expose what the board
needs without giving the LLM raw table access:

- `v_catalog_health`: activities, providers, stores by district with
  completeness (photos, price, schedule, address geocoded).
- `v_funnel_daily`: searches, listing views, CTA taps, leads relayed,
  bookings confirmed.
- `v_provider_pipeline`: sign-ups, onboarding step reached, days since last
  edit, subscription status.

The `product` tools call these views only; parameters are limited to date
ranges and district/category filters. The views are written against the
live siutindei Alembic schema (`organizations`, `activities`,
`locations` + `geographic_areas`, `activity_categories`, pricing and
schedule). There is no `stores` table — venues are `locations`. Funnel
rows live in `listing_events_daily` (created by the same SQL file) until
the product writes daily events.

### 5.8 Web — GA4, GTM, later Ads

Do **not** copy Meta. There is no Admin API webhook, and Google Ads auth is
a developer token plus OAuth — not one service account. Do **not** fold
Google into the `meta` tool.

- **`web` (this milestone):** GA4 sessions / conversions / top pages /
  referrers and GTM live-version **read**. Several properties and containers
  are first-class: `Ga4PropertyIds` is a CSV (`123,456` or
  `properties/123,properties/456`); `GtmContainers` is
  `account:container` pairs. CEO / CPO / CTO / CIO / CMO default to `read`.
  A **dedicated** service account lives in
  `lxsoftware-admin-siutindei-board-google-analytics-sa` (not the Play publisher key).
  Reads are cached 20 hours and refreshed by `SiutindeiBoardCacheRefreshSchedule`.
- **`ads` (T8b):** Google Ads spend and campaigns, plus propose a campaign.
  Monthly cap USD 50 (same shape as Meta ads caps). `act` only after T7-style
  spend tracking; until then writes stay `propose`.
- **T8c:** `gtm_propose_publish` is **always Approvals**, even if the CMO
  is at `act` on `web`.

## 6. Default permission matrix

`R` read, `P` propose, `A` act (within caps and allow-lists), `–` no access.

| Tool | CEO | CFO | COO | CPO | CTO | CIO | CISO | CMO |
|------|-----|-----|-----|-----|-----|-----|------|-----|
| `github` | R | – | – | R/P | R/P/A | R/P | R/P | – |
| `product` | R | R | R/P | R/P | R | R | – | R |
| `stores` | R | – | R | R/P | R | – | – | R/P/A |
| `web` | R | – | – | R | R | R | – | R |
| `mail` | R/P | R/P/A | R/P/A | R | R | R | R | R/P/A |
| `meta` | R | R | R/P/A | R | – | – | R | R/P/A |
| `finance` | R | R/P/A | R/P | – | – | – | – | R |
| `research` | R | R | R | R | R | R | R | R |
| `aws` | R | R | – | – | R/P | R/P | R | – |
| `security` | R | – | – | – | R | R | R/P | – |
| `board` | R/P/A | R/P/A | R/P/A | R/P/A | R/P/A | R/P/A | R/P/A | R/P/A |

`A` entries above are the **maximum** the owner can enable; the shipped
default global mode is `propose`, so nothing acts until the owner flips it.

## 7. Cost and budget

- Tool loops multiply tokens: a stand-up with 8 personas × up to 4 rounds
  on `gpt-4.1-mini` runs about USD 0.30–0.60; a deep dive on Sonnet with
  tools about USD 2–4. `defaultDailyBudgetUsd` in `board-timeouts.json`
  moves from 5 to **15**; the hard ceiling `maxDailyBudgetUsd` (100 in
  `contracts/executive-board.json`) stays. Tool results count toward the
  same daily cap.
- External API costs are tracked per tool in `BOARD#USAGE#` rows (Meta
  ads spend, search API quota) and shown on the settings card alongside
  OpenRouter spend.
- Cheap, cacheable reads (`product` views, `web`, `stores` daily metrics)
  are refreshed on a Scheduler cron and served from DynamoDB with a TTL so
  meetings do not hit third-party APIs eight times for the same number.

## 8. Backend changes

| Area | Change |
|------|--------|
| `backend/lambda/admin/` | New `board_tools.py` (registry, loop, level enforcement, audit), `board_mail.py`, `board_meta.py`, `board_receivables.py`, `board_product.py`, `board_stores.py`, `board_aws.py`, `board_research.py`; `board_github.py` gains write and search calls; `openrouter_client.py` gains tool-call support; `board_meeting.py` and `board_chat.py` call the loop |
| Routes | `GET /siu-tin-dei/board/approvals`, `POST …/approvals/{id}/approve|reject`, `GET …/board/tools` (matrix), `PUT …/board/tools` (matrix), `GET …/board/tools/calls` (audit log), `GET …/board/mail`, `GET …/board/mail/{threadId}`, `POST …/board/mail/{threadId}/read`, `GET …/board/receivables` (aging for the owner), `POST /webhooks/meta/siutindei` (no JWT, HMAC-verified, throttled; `/webhooks/meta` still accepted), `GET /webhooks/meta/siutindei` (verify). Proposals are created only by the tool loop, never by a `POST …/approvals` route. |
| DynamoDB | `BOARD#TOOLCALL#`, `BOARD#APPROVAL#`, `BOARD#MAIL#`, `BOARD#META#`, `BOARD#CACHE#`, `BOARD#USAGE#` prefixes; all covered by the existing `BOARD#` scan filter |
| Contracts | `contracts/board-tools.json`: tool ids, default matrix, `maxToolRoundsPerTurn`, `toolResultMaxChars`, cap names; synced to Python, TS and CDK |
| Secrets / params | CDK imports the existing Siu Tin Dei Secrets Manager secrets (`lxsoftware-admin-siutindei-board-*`) and grants `AdminApiFn` read. The earlier `lxsoftware-admin-{github-read-token,search-api-key,meta-board-token,meta-app-secret,app-store-connect-key,google-play-sa,google-analytics-sa}` set stays reserved for a future LX Software board. Ids stay as CfnParameters (`Ga4PropertyIds`, `GtmContainers`, `SiutindeiClusterArn`, `SiutindeiDbSecretArn`). OpenRouter stays the existing parameter. |
| SES | Receipt rule for `siutindei-board@inbound.lx-software.com` → S3 prefix `inbound-raw/siutindei/`; sending identity `siutindei.com` |
| Cloudflare (siutindei zone) | Email Worker on the catch-all that fans out to the owner's inbox and the SES address; DKIM/SPF/DMARC records for SES sending |
| Scheduler | `lxsoftware-admin-siutindei-board-*` (`SiutindeiBoardCacheRefreshSchedule` hourly, `SiutindeiBoardReceivablesMirrorSchedule` nightly, `SiutindeiBoardDunningSchedule` daily 09:00 HKT, plus morning/evening stand-ups). Each payload includes `boardKey: "siuTinDei"`. Role-based invokes, no Lambda resource-policy statements |
| IAM | Read-only Cost Explorer/CloudWatch/Security Hub policy on `AdminApiFn`; `rds-data:ExecuteStatement`/`BatchExecuteStatement` on the siutindei cluster; `ses:SendEmail` restricted to `siutindei.com` identities |
| siutindei repo | Migration for §5.4 tables, SQL views for §5.7, Data API enabled on the Aurora cluster if not already |

## 9. Frontend changes (`apps/admin_web`)

- **Approvals** section (queue, diff-style payload preview, approve/edit/
  reject), badge count on the tab.
- **Tools & permissions** card in settings: global mode switch, per-role
  matrix with the three levels, spend caps, recipient allow-list editor,
  kill switch state.
- **Transcript**: `tool` entries render as collapsible "CTO looked at
  GitHub: 3 open PRs, CI red on `main`" rows.
- **Chat offcanvas**: live tool-call status lines while polling.
- **Mail** and **Receivables** read-only views so the owner sees what the
  board sees (thread list with masking off for the owner; aging table).
- Hooks: `useBoardApprovals`, `useBoardTools`, `useBoardMail`,
  `useBoardReceivables`; shared components under
  `src/components/board/` documented in `UI_COMPONENTS.md`.

## 10. Delivery plan (one PR per milestone, each shippable alone)

| # | Scope | Depends on |
|---|-------|------------|
| T1 ✅ | Tool loop core: `openrouter_client` tools, `board_tools.py`, registry, level enforcement, audit rows, contracts, settings matrix API + card, `github` and `board` tools with read + propose, Approvals queue (backend + UI) | — |
| T2 ✅ | `research`, `aws`, `security` read tools; cache refresh Scheduler | T1 |
| T3 ✅ | Email ingest and index (§5.2) incl. sending identity, `mail` tools, Mail view | T1 |
| T4 ✅ | Receivables: siutindei migration and views (§5.4, §5.7), Data API access, `finance` and `product` tools, statement-book mirror, `record_manual_payment`, Receivables view, dunning Scheduler | T1 |
| T4b | Bank ingest adapter (§5.6): API client for an API-first account, or alert-mail parser + statement reconciliation for a traditional bank | T4, T3, account opened |
| T5 ✅ | Meta: app setup, webhook route, WhatsApp coexistence, `meta` read + propose tools, lead relay | T1, T3 |
| T6 ✅ | `stores` (App Store Connect, Google Play) tools and review replies | T1 |
| T7 ✅ | `act` level rollout: phone allow-list, owner ads caps, spend tracking, `boost_post` | T3–T6 |
| T8 ✅ | `web`: GA4 reads + GTM live version, multi-id lists, hourly cache | T1, T2 |
| T8b | `ads`: Google Ads spend / campaigns + propose campaign (USD 50 / month cap) | T7, T8 |
| T8c | `gtm_propose_publish` always Approvals | T8 |
| Follow-ups | Meeting action writes, Meta spend in unit economics, product views vs live schema, 25s timeouts, stable Meta PII, `mail_report_phishing`, invoice PDF, WhatsApp templates, owner-friendly approval edit | T1–T8 |

Each milestone ships behind the global mode switch and adds its own
Python unit tests (`test_board_tools.py`, fakes for every external API)
plus Vitest coverage for new hooks.

## 11. Remaining decisions

All six pre-start questions are answered (§1). Two items are deferred, not
blocking, and the board itself can work on them now that T1–T4 have shipped:

1. **Which HK account to open** — API-first (Airwallex/Statrys/Aspire) or a
   traditional bank; decides which T4b adapter is built. Suggested first CFO
   deep-dive topic.
2. **Listing prices** — decides the first `listing_plans` rows; suggested
   first CFO/CPO stand-up action, approved through the queue.

Next sign-off: **T8b** (Google Ads) when scheduled. T8c is GTM publish
(always Approvals). T4b waits on the HK account.

## 12. Known gaps

Shipped behaviour that is narrower than the connector table in §4; each tool
description says so to the model.

- **Stores metrics**: App Store Connect downloads come from the daily
  `salesReports` summary and Google Play crash rate from
  `crashRateMetricSet`; installs are not available from either API and are
  returned as `null`. Ratings, reviews and review replies are complete.
- **Mail attachments**: PDF attachment text is not extracted into threads
  (no local PDF text extractor in the Lambda bundle); PDFs are listed by name
  and size, and the statement-parser path handles bank statements separately.
- **Bank alerts**: the "hook bank alerts to receivables" flow waits on T4b
  (which HK account is chosen); until then payments are matched from FPS
  references in imported statements and manual records.
- **`listing_events_daily`** has no writer in the siutindei product yet, so
  `product_funnel` returns empty rows until that lands (tracked in
  `scripts/siutindei/receivables.sql`).
- **GitHub discussions**: not readable (GraphQL only); releases are.
- **Research quota**: search calls are counted per day in
  `BOARD#USAGE#external`; the OpenRouter `:online` fallback is billed to the
  daily budget. There is no hard cap on search calls yet, only visibility on
  the Settings card.
