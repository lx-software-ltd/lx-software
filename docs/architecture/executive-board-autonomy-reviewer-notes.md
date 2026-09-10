# Executive Board autonomy — reviewer notes

Uncertainties and intentional deviations found while implementing the
specification in `executive-board-autonomy-implementation.md`. Pick these
up in review; do not treat them as product decisions unless you confirm.

## WP1

- **S3 in unit tests.** When `ASSETS_BUCKET_NAME` is unset, `board_staff`
  stores scratchpads and deliverables in a process-local `_MEMORY_BLOBS`
  map. Production always has the env var. This is test-only.
- **`env_enabled()` when the variable is missing.** Follows the spec
  ("not in the false-set"), so an unset `BOARD_STAFF_ENABLED` is treated
  as on. CDK still defaults the parameter to `false`. Combined with
  `settings.staff.enabled` defaulting to `false`, the feature stays inert.
- **Seat `tools` in the contract name tools that do not exist yet**
  (`places`, `code`, later outreach/content). Those ids stay `off` in
  `effectiveLevels` until the tool is registered. Not a WP1 bug.
- **`returned` task status** is in the contract. Manager return sets the
  task back to `running` (as the spec's `run_review` text says), so
  `returned` is unused as a persisted status. The SPA column is "Running".
- **GET `/staff` and GET `/tasks`** return 409 only when
  `BOARD_STAFF_ENABLED` is in the false-set. Writes that create or advance
  work also require `settings.staff.enabled`. Seat PUT/DELETE work whenever
  the env flag is on so the owner can prepare the roster before enabling
  tasks. The spec only mandated 409 on `POST /tasks`.
- **One PR for the whole solution.** The spec asked for one PR per WP.
  This branch implements the solution on a single branch; commits are
  still split per WP when possible.
- **`usage_sink`** records each LLM completion into `staffusage#` in
  addition to the existing board `usage#` row. The end-of-step aggregate
  `add_staff_usage_day` was removed to avoid double-counting.
- **Seat count.** The proposal and spec say "sixteen seats". The roster
  table lists fifteen distinct ids (`engineer-1` and `engineer-2` are two
  of them; the "sixteen" count treated that row as two plus an extra).
  The contract matches the table: 15 seats. Confirm whether a sixteenth
  seat was omitted.
- **`shared-contracts.ts`** still only emits timeouts (same as before this
  WP). Staff constants live in `contract_constants.py` and
  `apps/admin_web/src/lib/contracts/generated.ts`. CDK does not need the
  staff roster at synth time.
- **Staff enable toggle** is not on the Staff tab. Enable via
  `PUT /siu-tin-dei/board/settings` `{ "staff": { "enabled": true } }`
  after the stack flag is on. A settings checkbox can land in WP4 with
  the review card.

## WP2

- **`always_propose` vs publish holds.** The WP2 integration paragraph said
  to hold only when the call would otherwise execute (`not always_propose`).
  Acceptance requires CMO `act` + `holds.publish = 24` + `meta_propose_post`
  → `held`. Publish is a covered boundary, so when staff is enabled, the
  level is `act`, there is no guard, and hours > 0, the write is held even
  if `always_propose` is set. With staff off or hours 0, today's Approval
  path is unchanged.
- **Owner actor never holds.** Spec said `ctx.actor != "hold"`. Owner
  executions (approval decide) stay immediate; only `persona` writes enter
  a hold window. The owner is the vetoer.
- **Hold arguments are stored unmasked**, same as Approvals (the spec said
  "masked as stored on approvals"; approvals store the raw args so
  `execute_due` can run the op).
- **`hold_hours` takes `(table, settings, action_class, class_key)`** so it
  can read `breaker#` rows. The spec's `(settings, …)` signature cannot see
  breakers.
- **`execute_due` filters `executeAt <= now` in Python** after
  `list_holds(..., "scheduled")`. FakeTable (and the current query helper)
  cannot express `gsi1sk <= now`.
- **Ramp discovery** for `GET /ramp` walks recent holds' `classKey`s. A
  ramp row with no surviving hold is not listed until another action in
  that class is recorded.
- **`get_mail_thread` via `_public_mail`** must keep `lastInboundAt` for
  the stale-reply check. If that field is stripped, the thread-changed
  rule cannot fire.

## WP3

- **Keyword hits skip the desk classifier.** Spec order is keyword →
  prospect → otherwise a model call. After a keyword escalation we do not
  spend a model call; audience stays `unknown` unless a prospect match
  already set `provider`, and intent is stored as `complaint`.
- **Inactive WP9 seats.** Routing still names `accountant` (finance@ /
  billing@) and `security-analyst` (intent `spam`). Those seats are
  inactive until WP9, so `_open_or_append` falls back to `support` and
  forces `needs_owner`.
- **`add_external_usage_day` field names.** Spec used `reply:{channel}`.
  The helper now allows a colon in the Dynamo attribute name.
- **Inbound remaining time.** `inbound_email_handler` now passes
  `context.get_remaining_time_in_millis` into `ingest_raw_object` as a
  monotonic deadline so `classify_text` can skip the model when fewer
  than 20 s remain.
- **Store review fetch** runs inside `refresh_caches` (not only the
  ratings cache) so new review ids can be detected. Failed review fetches
  are logged and do not fail metrics refresh.

## WP4

- **Usage day vs HKT date.** Board `usage#` and `staffusage#` keys are UTC
  dates. The 07:15 HKT compile runs at 23:15 UTC the previous calendar day,
  so headline spend reads the current UTC day (yesterday evening UTC /
  this morning HKT).
- **`create_from_veto(table, hold)`** (and the other lesson constructors)
  take `table` first. The spec omitted it; store helpers need the FakeTable
  in tests.
- **Class breaker name** is `class:{classKey}`. `hold_hours` still honours
  a legacy breaker stored under the bare `action_class` / `class_key` so
  the WP2 test that trips `publish` keeps working.
- **Channel breaker** fires when an escalation lands on a thread that
  already had a reply/post tool-call in the last 24 h
  (`note_escalation_after_reply` from triage). It does not count raw
  volume.
- **Owner writes are not held or breaker-blocked.** `execute_call` checks
  channel/tool breakers only for `actor=="persona"` so the founder can
  still approve or send.
- **Promote resets `class:{classKey}`** as well as setting
  `holdOverrides[classKey]=0`, otherwise a demote breaker would keep the
  default hold and Accept would do nothing.
- **Breaker index** is a `breaker-index` state doc listing names. Breakers
  have distinct `pk`s (`breaker#{name}`), so they cannot be queried with
  `begins_with` on a single partition.
- **`get_tool_call`** scans the newest 500 tool-call rows. Fine for the
  owner's "this was wrong" action.
- **Digest HTML** is an optional `html` field on `board_mail.send_plan`
  (`EmailMessage.add_alternative`). Existing text-only sends are unchanged.
- **Headline duty** is created on the 07:00–07:14 HKT ticks even when
  `settings.staff.dutiesEnabled` is still false (WP9 owns the general duty
  system). `business-analyst` must be active (now the contract default).
- **`maxRunningTasksDefault` is now 6** in the contract. Existing saved
  settings keep whatever `maxRunningTasks` was stored until the owner
  saves again.
- **Staff enable + digestTo** are on the Settings card (called out in WP1
  reviewer notes).
- **Default section** is Daily review when `settings.staff.enabled` is
  true. Digest deep-links use `?tab=board&section=review#…`.
- **One PR for the whole solution** still applies (see WP1).

## WP5

- **FEHD is XML, not CSV.** Verified 2026-09-10: Licensed Restaurants on
  data.gov.hk publishes English and Traditional Chinese XML
  (`LP_Restaurants_EN.XML` / `LP_Restaurants_TC.XML`). The module parses
  XML in production and still accepts the spec's CSV fixture
  (`test_fixtures/fehd_sample.csv`) via `parse_fehd_csv`.
- **`candidate` was added to `watchKinds`.** The spec's discover path
  writes `kind="candidate"`; the contract list omitted it. CRUD accepts
  it even if a future sync drops it from the JSON.
- **EDB download URL.** Recorded as
  `https://www.edb.gov.hk/attachment/en/student-parents/sch-info/sch-search/sch-location-info/SCH_LOC_EDB.csv`
  (portal dataset `hk-edb-schinfo-school-location-and-information`). If
  that attachment 404s, the loader returns the last 7-day cache and logs
  `board_opendata_fetch_failed`.
- **LCSD programmes** stay an empty stub until WP6 (`lcsd_programmes`).
- **iTunes RSS 404** falls back to the lookup payload only and logs
  `board_intel_appstore_rss_missing` (once per failed fetch; the crawl
  does not add a separate daily lock).
- **Intel tool is hidden from `available_ops` when staff is off** so the
  existing board does not see a new tool. The contract still lists it.
- **Weekly brief ignores `dutiesEnabled`.** Same as the WP4 headline
  duty; WP9 owns the general duty system.
- **Digest storage** reuses `board_staff._blob_put` (in-memory when
  `ASSETS_BUCKET_NAME` is unset).
- **Open-data cache** uses Dynamo `cache` rows (`opendata:fehd` /
  `opendata:edb`), not a separate S3 pointer besides the crawl digests.
- **`discover` must see an already-known host to increment `seenWeeks`.**
  Skipping known hosts before the match check would prevent promotion.
- **Same-day recrawl.** Digest keys are
  `{watchId}/{urlDigest}/{yyyy-mm-dd}.txt`, so a second fetch the same HKT
  day overwrites the object. `daily_crawl` reads the previous digest
  *before* `put_digest` so the change note still has a before/after pair.

## WP6

- **Places prices.** The spec quoted Pro SKUs (USD 0.032 text search /
  0.017 details). The required field mask includes website, phone, rating
  and hours, which are Enterprise fields. Constants are **USD 0.035**
  (Text Search Enterprise) and **USD 0.020** (Place Details Enterprise),
  verified 2026-09-10 against Google Maps Platform pricing pages.
- **LCSD** remains an empty open-data stub. No stable public file was
  verified; FEHD and EDB are live. `outreach_open_data(kind=lcsd)`
  returns the last cache or `[]`.
- **`PROVIDER_SIGNUP_URL`** is not a CDK parameter. Templates default to
  `https://siutindei.com` unless that env is set. Confirm the real
  provider sign-up path with the owner.
- **Unsubscribe is unauthenticated** on
  `GET/POST /public/outreach/unsubscribe/{token}` (HMAC in the token,
  IP rate-limit 100/hour). It is not behind the API-key public
  authorizer. Staff flags are not required so a person can still opt out
  after the feature is switched off.
- **Outreach SES identity is always created** (not gated on
  `BoardMailSendingEnabled`). `outreach_send` still refuses with
  `sending identity not verified` until
  `GetEmailIdentity.VerifiedForSendingStatus` is true (cached 1 h). Tests
  can set `OUTREACH_IDENTITY_VERIFIED=true`.
- **`ingest_bytes(direction="outbound")`** is accepted as an alias of
  `out` so the outbound copy is indexed and triage still skips it.
- **Daily cap owner writes** are clamped to `outreachDailyCapMax` (100),
  not 200. Empty `capRaisedAt` is initialised on the first target check
  without raising, so warm-up does not jump on day one.
- **Places monthly USD** is stored on cache `places:month:{yyyy-mm}`
  using the HKT month. Per-call counts also increment
  `external_usage_day` field `places`.
- **Prospector tools** gained `"outreach": "act"` so the seat can send.
  That id was not on the WP1 seat tools object.
- **Token encoding** is `base64url(prospectId + "." + HMAC-SHA256(secret,
  prospectId)[:16])` with the first 16 **raw digest bytes**, not hex.
- **Email suppress does not write a domain suppress.** Unsubscribing
  `info@gmail.com` must not block every other Gmail prospect. Domain
  suppress is only written when `suppress(..., domain=)` is explicit.
  `is_suppressed` still honours an existing domain digest.
- **`OUTREACH_SENDING_DOMAIN` is an own-mail domain.** Without that,
  outbound copies From `partnerships@partners.siutindei.com` would be
  treated as external and would not thread to replies on
  `partnerships@siutindei.com` when `In-Reply-To` is missing.
- **SES → KMS-encrypted SNS.** The shared CMK now allows
  `ses.amazonaws.com` `kms:Decrypt` / `kms:GenerateDataKey*` so bounce
  and complaint events can publish. SNS already allowed `sns:Publish`.
- **Prospect replies** attach `eventRef.prospectId` and force
  `audience=provider` even on a cached triage classification so the
  task lands on `provider-success`.
- **Score model** uses `board_budget.model_for("standup")`, the same
  mapping staff desks already use (desk tier → standup model). Not a
  separate `desk` kind.
- **Intel brief prospects** pass `url` (WP5 JSON shape). `upsert_prospect`
  maps `url` → `website`. After WP6 the row is stored as a prospect, not
  only on `intel:prospects` cache.
- **`OUTREACH_IDENTITY_VERIFIED=false`** forces the SES check off so
  tests can exercise the unverified refusal without a live identity.

## WP7

- **Fonts are variable-font files** saved under the spec names
  (`NotoSans-Regular.ttf` / `NotoSans-Bold.ttf` are the same wdth+wght
  variable file; `NotoSansTC-*.otf` is the Google Fonts TC variable TTF).
  `board_creative` sets the `wght` axis to 400 or 700. OFL text is in
  `fonts/OFL.txt`.
- **Brand tokens** (`#FF6B35` / `#2EC4B6` / `#1A1A1A` / `#FFF8F0`) and the
  placeholder logo were chosen by the implementer; confirm with the owner.
- **`AdminApiFn` memory is 1536 MB** (spec §5). Inbound statement Lambda
  stays at 1024.
- **`create_hold(..., execute_at=)`** is used so `content_publish` waits
  for `slotAt` even when the publish class has been promoted to 0 hours.
- **Plan deliverable read limit** is 200_000 characters so a 21-item JSON
  week is not truncated by the default 6_000-char `read_deliverable`.
- **Python-lambda Docker bundling** was already in `python-lambda.ts`;
  adding Pillow to `requirements.txt` disables the local no-pip copy path.
- **Creatives render inline** in `on_plan_delivered` rather than as a
  separate staff-task step. Same Pillow path, one Lambda invoke.
- **Default `perWeek` includes `seo: 2`.** Acceptance still treats the
  social week as 21 items (7+7+7); SEO rows are extra and unused until
  a later publishing path.
- **`web_sessions` campaign filter** uses GA4 `sessionCampaignName`
  (`board_web.campaign_sessions`) against `{pillar}-{yyyyww}` labels.
  Missing GA4 config is logged and does not fail the readout.
- **`add_external_usage_day` now allows `_`** so the spec field
  `ig_publish` is a legal counter name (colons were already allowed for
  `reply:{channel}`).

## WP8

- **No fortnightly Scheduler** in this WP. Drafting is the
  `newsletter_draft_issue` op (content-marketer). A duty can be added in
  WP9. The WP9 duty list did not add one; drafting stays an op.
- **No new admin tab.** Sends appear as `publish:newsletter` holds on
  Approvals. Subscriber counts are not yet an owner UI.
- **Confirm/issue send require `BoardMailSendingEnabled`.** That is the
  spec kill-switch for all email. Subscribe still stores a pending row
  when sending is off.
- **SES template is created lazily** (`CreateEmailTemplate` on first
  send), not as a CDK custom resource.
- **`NewsletterForm` is on the LX Software public footer**
  (`apps/public_www`). The Siu Tin Dei product site may live in another
  repo; owner should confirm the form's production home.
- **Token payload** is `{c|u}:{list}:{emailDigest}` using the WP6 HMAC
  helper. Digest is SHA-256 of the normalised email (one row per email).

## WP9

- **First enable of `dutiesEnabled` catch-up.** `is_due` treats an empty
  last-run cache as before the most recent scheduled time, so the first
  tick after the owner turns duties on creates a task for every duty
  whose last cron fire is in the past 40 days (including last week's KPI
  pack and this month's month-end memo). That matches the spec's
  missed-tick rule. Confirm if the owner would rather wait for the next
  wall-clock fire.
- **No newsletter duty.** WP8 noted a fortnightly draft could land here.
  The WP9 duty list is explicit (BA KPI, accountant month-end + aging,
  security triage, data-analyst attribution) and does not include a
  newsletter cron.
- **Architect was inactive in WP9.** Alarm tasks went to the CTO until
  WP10 activated `architect`. Security alerts go to `security-analyst`.
- **Dunning still falls back to Approvals** when `create_task` raises
  `StaffError` (cap, inactive seat) or when staff is off. Existing
  receivables tests stay on the Approval path because they do not enable
  staff.
- **Cron language** is five HKT fields. Named `MON`–`SUN` and UNIX
  `0`/`7` = Sunday are accepted. When both DOM and DOW are restricted,
  match is OR (standard cron). Minute `*` steps in 5 minutes to match
  the tick.
- **GitHub Dependabot rows have `summary`, not `title`.** Triage brief
  falls back to `summary` / `description` / `secretType`.
- **`BoardStaffSeatDefault` gained optional `duties`.** Sync-contracts
  emits the duty objects onto the seats that define them.
- **CI workflow failures are not hourly tasks.** The WP9 backend paragraph
  diffs CloudWatch ALARMs and Hub/Analyzer/GitHub alert ids. Dependabot /
  code-scanning are covered. Actions failures on `main` only appear in the
  meeting repo snapshot (last five default-branch runs). WP10 reviews CI on
  `board/*` PRs.

## WP10

- **siutindei workflows are a hand-off.** This repo dispatches
  `board-agent.yml`, `board-merge-staging.yml` and `board-promote.yml`.
  Exact YAML is in
  `docs/architecture/executive-board-autonomy-siutindei-appendix-a.md`.
  Without those files in siutindei, dispatches return GitHub 404.
- **CMO stays `off` on the `code` tool** (spec defaults: cto act, cpo
  propose, others off). `content-marketer` has seat-level `code: act` for
  SEO, but the manager cap keeps it off until the owner raises CMO.
- **Architect duty cron is Monday 11:00 HKT** (`groom-backlog`). The spec
  said weekly and did not name a clock time.
- **Promote from the review page queues an Approval** (`POST /code/promote`
  → `code_promote`, `always_propose`). Approving it dispatches
  `board-promote.yml`; the owner still merges the GitHub PR to `main`.
- **`board_github._request` returns raw text** for
  `Accept: application/vnd.github.diff` so `code_review_pr` can cap the
  diff at 30 000 characters.
- **GitHub PAT description** now asks for `Actions: write` (was read).
  Rotate/widen the existing fine-grained token.
- **All fifteen seats are now `isActiveDefault: true`.** Inactive-seat
  tests deactivate `architect` via override.
