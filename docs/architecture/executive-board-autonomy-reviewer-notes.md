# Executive Board autonomy — reviewer notes

Uncertainties and intentional deviations found while implementing the
specification in `executive-board-autonomy-implementation.md`. Pick these
up in review; do not treat them as product decisions unless you confirm.

The senior review of the finished branch, with numbered findings (`R-nn`),
gates and an ordered execution plan, is in
`executive-board-autonomy-remediation-plan.md`. Every `R-nn` is closed
below (fixed with a named test, or an owner decision recorded from plan §6).

## Remediation close-out (R-01–R-38)

Owner decisions from plan §6, applied as specified:

1. **R-24.** Keep the fifteen-seat roster. Default **on**: `support`,
   `provider-success`, `community-manager`, `business-analyst`. All other
   seats `isActiveDefault: false`. `maxRunningTasksDefault` is 3. Flip
   remaining seats on per the §6 runbook in
   `docs/deployment/admin-website.md`.
2. **R-37.** Keep `always_propose` publish ops as 24 h holds when staff
   is on. Exempt by action class `code_production` only (not by op name).
3. **R-12.** CORS via `PublicSiteOrigins` CSV. The form stays on the LX
   Software public site until the owner names another origin.
4. **R-25.** HTTPS-only `List-Unsubscribe` (RFC 8058); no `mailto:`.
5. **R-01 / R-22.** `code_merge_staging` stays `always_propose` until
   siutindei Appendix A workflows exist.

| Id | Status | Proof / note |
|---|---|---|
| R-01 | Fixed | Hold actor re-derives level, `act_guard`, breakers, tools kill-switch; tick evaluates breakers before `execute_due`; `headSha` + `merge_guard` inside merge; ads snapshot includes scheduled spend holds; `code_merge_staging` remains `always_propose`. Tests: `test_hold_fails_when_breaker_tripped`, `test_hold_fails_when_persona_downgraded`, `test_merge_refuses_when_ci_flips_after_accept`, `test_merge_refuses_new_head_sha_after_accept`, `test_two_spend_holds_second_fails_cap`. |
| R-02 | Fixed | Breaker / hold exceptions fail closed to Approval. Tests: `test_maybe_hold_exception_downgrades_to_approval`, `test_breaker_check_exception_downgrades_to_approval`. |
| R-03 | Fixed | Shared env loop on `AdminApiFn` and inbound-mail Lambda; `env_enabled()` is `"1"/"true"/"yes"/"on"` only; `run_step` / `run_review` / finish-review gated; triage ack via `invoke_async`. Tests: CDK shared-env assertion; `test_env_enabled_false_when_unset`; `test_run_step_noops_when_env_disabled`; `test_injury_is_needs_owner_and_sends_ack`. |
| R-04 | Fixed | Usage applied to the re-read task; dead `_finished` guard removed. Test: `test_task_usage_accumulates_and_budget_stops_third_step`. |
| R-05 | Fixed | Personal email → `contactRejected="personal"`; type rewrite only when `source="owner"`; send re-checks business address. Tests: `test_personal_email_not_promoted_to_contact`, `test_type_rewrite_refused_unless_owner`, `test_personal_address_refused_at_send`. |
| R-06 | Fixed | `send()` refuses when `BOARD_MAIL_SENDING_ENABLED` is off. Test: `test_sending_disabled_refuses`. |
| R-07 | Fixed | Contact domain indexed only when it equals the website registrable domain and is not a public mailbox; lookups try the exact address first. Tests: `test_personal_email_not_promoted_to_contact` (no `gmail.com` key); `test_gmail_parent_not_matched_to_gmail_prospect`. |
| R-08 | Fixed | Quoted text and own footer stripped before UNSUB match. Test: `test_quoted_footer_does_not_suppress`. |
| R-09 | Fixed | Triage masks via `pseudonymizer.mask_text` before classifier / digest / brief / scratchpad; Meta uses `textMasked` / `lastTextMasked`. Test: `test_classifier_receives_masked_phone_and_email`. |
| R-10 | Fixed | Crawl refuses loopback / link-local / RFC1918 / CGNAT / multicast and follows ≤ 3 hops; `intel_fetch_page` is watchlist-only. Test: `test_link_local_and_redirect_refused`, `test_fetch_page_requires_watchlist`. |
| R-11 | Fixed | Outreach and board-mail IAM include both configuration-set ARNs and `ses:SendBulkEmail`; templates scoped to `template/lxsoftware-admin-siutindei-*`. Test: CDK `configuration-set` assertions. |
| R-12 | Fixed | `PublicSiteOrigins` CSV appended to HTTP API CORS. Test: CDK CORS parameter assertion. Owner: set the CSV to the live public-site origin(s). |
| R-13 | Fixed | `claim_task_step` sets `stepClaimed`; step 1 is claimed. Test: `test_claim_task_step_mutual_exclusion`. |
| R-14 | Fixed | `save_settings` is version-conditional; owner routes 409; boundaries merge only card fields and echo `version`; SPA resyncs and refetches on 409. Tests: `test_settings_conflict_then_retry`; Vitest `useBoardBoundaries.test.ts`, `BoardBoundariesCard.test.tsx`. |
| R-15 | Fixed | `add_staff_usage_day` is a single `ADD`. Test: `test_staff_usage_day_adds_atomically`. |
| R-16 | Fixed | Reserve slot with `ADD sent` + `sent < :cap`; provisional touch before SES. Test: `test_two_sends_at_cap_minus_one`. |
| R-17 | Fixed | Claim `draft → sending`; `sentThrough`; refuse when `sent`; `DefaultEmailTags` `issueId`; count SUCCESS only; paginate. Tests: `test_second_send_is_noop_and_tags_issue`, `test_failed_bulk_entry_not_counted`, `test_batch_send_and_hold_class`. |
| R-18 | Fixed | Subscriber key `{list}#{digest}`; never reset `confirmedAt`; per-digest confirm cooldown max 3/day; opt-out is `unsubscribedAt` on the row. Tests: `test_cross_list_keeps_first_confirmed`, `test_fourth_confirm_not_sent`, `test_resubscribe_after_unsubscribe`. **Migration:** no live newsletter rows existed; new key shape only. |
| R-19 | Fixed | SES records routed by configuration-set / `issueId`; SQS `reportBatchItemFailures`. Test: `test_newsletter_complaint_leaves_outreach_day_unchanged`. |
| R-20 | Fixed | Immediate act writes call `record_ramp`; sample-wrong counts as veto; `ramp-index` state. Test: `test_promoted_class_records_ramp_and_wrong_demotes`. |
| R-21 | Fixed | Unparsable review verdict is `return`. Tests: `test_review_unparsable_verdict_returns`, `test_review_empty_completion_returns`. |
| R-22 | Fixed | `_pr_files` paginates and refuses a `changed_files` mismatch. Test: `test_pr_files_paginates_and_refuses_protected_on_later_page`. |
| R-23 | Fixed | `list_for_api` returns `{prospects, nextCursor}`; duplicates only on the detail route; SPA infinite query. Test: `test_prospect_list_paginates_a_stage`. |
| R-24 | Fixed + owner | See §6 decision 1. Contract synced. Tests that need other seats call `save_staff_override`. |
| R-25 | Fixed + owner | HTTPS-only List-Unsubscribe. Test: `test_list_unsubscribe_is_https_only`. |
| R-26 | Fixed | Budget breaker disables only on the trip transition; `seniorPaused` / `disabledReason` clear when not tripped; `staffusage#` keyed by HKT; Settings card surfaces `disabledReason`. Covered by breaker unit tests. |
| R-27 | Fixed | `STEP#` / `REVIEW#` stamp `expiresAt`. |
| R-28 | Fixed | Tool calls GSI `tasks#{taskId}#calls`; `list_tool_calls_for_task`. |
| R-29 | Fixed | `returned` removed from `taskStatuses`; `expire_stale` when overdue or staff off; outreach veto sets `vetoedAt` and `nextTouchAt` +30 days. |
| R-30 | Fixed | `claim_duty_marker` before `create_task`. Duty idempotency tests. |
| R-31 | Fixed | `execute_at = max(slotAt, now+hours)` while class hold > 0. |
| R-32 | Fixed | Specific tokens (including North Point) before generic `North`; unmapped → `"unknown"`. Test: `test_unmapped_district_is_unknown`. |
| R-33 | Fixed | `outreach_send` `act_guard` uses `board_policy.PROMISE_RE`. |
| R-34 | Fixed | Unsubscribe token is `pid + mac` (no `.`); parse `raw[:-16]` / `raw[-16:]`. Test: `test_unsubscribe_token_round_trip_and_tamper`. |
| R-35 | Fixed | Duplicate Bold binaries removed (`NotoSans-Bold.ttf`, `NotoSansTC-Bold.otf`); both weights use Regular / variable `wght`. Remaining: `NotoSans-Regular.ttf`, `NotoSansTC-Regular.otf`, `OFL.txt`. |
| R-36 | Fixed | `_origin_from_ctx` returns `"task"`; contract `taskOrigins` includes `task`. |
| R-37 | Fixed + owner | See §6 decision 2. `action_class_exempt` checks `action_class == "code_production"`. |
| R-38 | Fixed | Rate limiters use `bump_cache_count` `ADD`. |

## WP1

- **S3 in unit tests.** When `ASSETS_BUCKET_NAME` is unset, `board_staff`
  stores scratchpads and deliverables in a process-local `_MEMORY_BLOBS`
  map. Production always has the env var. This is test-only.
- **`env_enabled()` when the variable is missing (R-03).** Fail-closed:
  only `"1"`, `"true"`, `"yes"` or `"on"` enable staff. CDK still defaults
  the parameter to `false`. Combined with `settings.staff.enabled`
  defaulting to `false`, the feature stays inert.
- **Seat `tools` in the contract name tools that do not exist yet**
  (`places`, `code`, later outreach/content). Those ids stay `off` in
  `effectiveLevels` until the tool is registered. Not a WP1 bug.
- **`returned` task status (R-29).** Removed from the contract. Manager
  return still sets the task back to `running`; the SPA column is "Running".
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

- **Usage day vs HKT date (R-26).** Board `usage#` remains UTC.
  `staffusage#` is keyed by HKT date so the 80 % / 100 % budget breaker
  sees the same window as the 07:15 HKT compile.
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
- **`maxRunningTasksDefault` is 3** (R-24). Existing saved settings keep
  whatever `maxRunningTasks` was stored until the owner saves again.
  Raise to 6 only after WP7 content is live (runbook step 5).
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
  (`test_fixtures/fehd_sample.csv`) via `parse_fehd_csv`. Semgrep flagged
  stdlib `xml.etree`; parse uses `defusedxml.ElementTree` (`requirements.txt`).
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
  `SiutindeiBoardMailSendingEnabled`). `outreach_send` still refuses with
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
- **Token encoding (R-34)** is `base64url(prospectId + HMAC-SHA256(secret,
  prospectId)[:16])` with the first 16 **raw digest bytes**, not hex, and
  no `.` separator. Parse is `raw[:-16]` / `raw[-16:]`.
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

- **Fonts (R-35).** One Regular file per family
  (`NotoSans-Regular.ttf`, `NotoSansTC-Regular.otf`); both weights use
  that file and `board_creative` sets the `wght` axis to 400 or 700.
  Duplicate Bold binaries were deleted on this branch so they do not
  enter `main` as extra paths (the blob is the Regular file). OFL text
  is in `fonts/OFL.txt`.
- **Brand tokens** (`#FF6B35` / `#2EC4B6` / `#1A1A1A` / `#FFF8F0`) and the
  placeholder logo were chosen by the implementer; confirm with the owner.
- **`AdminApiFn` memory is 1536 MB** (spec §5). Inbound statement Lambda
  stays at 1024.
- **`create_hold(..., execute_at=)`** is used so `content_publish` waits
  for `slotAt` even when the publish class has been promoted to 0 hours.
- **Plan deliverable read limit** is 200_000 characters so a 21-item JSON
  week is not truncated by the default 6_000-char `read_deliverable`.
- **Python-lambda Docker bundling** was already in `python-lambda.ts`;
  adding Pillow (and `defusedxml`) to `requirements.txt` disables the
  local no-pip copy path. Checkov CI sets `CDK_SKIP_PYTHON_PIP=1` so
  synth copies sources without Docker (GitHub runners cannot execute
  the arm64 SAM bundling image). Deploy still bundles with pip.
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
- **Confirm/issue send require `SiutindeiBoardMailSendingEnabled`.** That is the
  spec kill-switch for all email. Subscribe still stores a pending row
  when sending is off.
- **SES template is created lazily** (`CreateEmailTemplate` on first
  send), not as a CDK custom resource.
- **`NewsletterForm` is on the LX Software public footer**
  (`apps/public_www`). The Siu Tin Dei product site may live in another
  repo; owner should confirm the form's production home.
- **Token payload** is `{c|u}:{list}:{emailDigest}` using the WP6 HMAC
  helper. Digest is SHA-256 of the normalised email. Rows are keyed
  `{list}#{digest}` (R-18) so one address can sit on more than one list.
  No live subscriber rows existed at the key change.

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
- **Seat defaults (R-24).** Fifteen-seat roster. Default on:
  `support`, `provider-success`, `community-manager`, `business-analyst`.
  Tests that need other seats call `save_staff_override(..., {"isActive": True})`.
- **Mock Approvals list is in-memory.** `POST /code/promote` prepends a
  pending `code_promote` row so Daily review → Promote → Approvals matches
  the live API. A static fixture would leave only the mail_send sample.
