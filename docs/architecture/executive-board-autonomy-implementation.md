# Executive Board autonomy — implementation plan for the developer

Status: **implementation specification, not yet started.** This document turns
[`executive-board-staff-plan.md`](./executive-board-staff-plan.md) (the
proposal) into build instructions. Every decision the proposal left open is
taken here (§1). The developer follows the work packages in §4 in order,
one pull request per work package, and does not need to make product or
architecture decisions; where something is genuinely unknown at build time,
the package says exactly what to do.

Read first, in this order: [`executive-board-plan.md`](./executive-board-plan.md)
(how the board works), [`executive-board-tools-plan.md`](./executive-board-tools-plan.md)
(tool loop, levels, approvals), the proposal, then this document.
`AGENTS.md` gotchas apply throughout, in particular: no per-route Lambda
permissions, no `events.Rule` targets on `AdminApiFn` (use EventBridge
Scheduler), contracts are synced with `scripts/sync-contracts.py`.

## 0. How to use this document

- **Work packages (WP)** are in build order. Each lists: goal, files to
  create or change, data written, functions with signatures, routes, CDK,
  SPA, tests, acceptance checks, and *potential issues* with the required
  handling. Do not start a WP before the previous one is merged, except
  where §4 says two can run in parallel.
- **"Decided"** means do exactly that. **"Verify"** means check the stated
  fact in the environment and stop and report if it is false; do not pick an
  alternative silently.
- Names in backticks are exact: file names, function names, DynamoDB keys,
  settings paths, environment variables, contract keys.
- Every WP ships behind `BoardStaffEnabled` (stack parameter, default
  `false` until WP4 is live) **and** `settings.staff.enabled` (default
  `false`). With both off, nothing in this document runs and the existing
  board behaves exactly as today.

## 1. Decisions taken

| # | Topic | Decision |
|---|-------|----------|
| 1 | Control model | Boundaries plus **hold windows** (default-approve with veto). The existing Approvals queue stays for actions no boundary covers. |
| 2 | Fit rubric | Ships with the default text in §3.3. Prospect types enabled for outreach in v1: `provider`, `venue`, `community`, `school`. `restaurant` and `media` are **discovered and scored but never contacted** until the owner enables them (see #3). |
| 3 | Restaurants | The product has no places listing type. Restaurants enter the pipeline in stage `parked`. `market-analyst`'s first brief includes a sizing of a "child-friendly places" listing type; enabling `restaurant` outreach is a one-line settings change once the product ships it. No product work in this repo. |
| 4 | Outreach mechanics | Sending subdomain `partners.siutindei.com`, from address `partnerships@partners.siutindei.com`, MAIL FROM `mail.partners.siutindei.com`. Business addresses only (`info@`, `hello@`, `enquiry@`, contact-form addresses, addresses published on a business page); **named personal addresses are never used** in v1. Cap starts at 20 sends/day and rises by 20 every 7 days to 100 if the complaint rate stays under 0.1 %. Web forms off. Cadence D+0, D+4, D+10. |
| 5 | Intelligence | Watchlist starts empty with an owner-facing "add" form plus discovery rules (§4 WP5). A siutindei address `market@siutindei.com` may subscribe to competitor newsletters (owner does the sign-ups by hand; agents read the mailbox). Crawl: watchlist URLs plus homepage of discovered domains only. |
| 6 | Creatives | Template PNG cards rendered in Lambda with Pillow, Noto Sans + Noto Sans TC. No generated images, no provider photos in v1. Brand assets are placeholders until the owner drops real ones into `backend/lambda/admin/brand/`. |
| 7 | Channels | Facebook Page and Instagram feed/stories autonomous through holds. Newsletter in WP8. Assisted packs for Xiaohongshu and Facebook groups. Google Business Profile, WhatsApp broadcast, Threads, LinkedIn: **out of scope**. |
| 8 | Engineering runner | Option B: `workflow_dispatch` runner in the siutindei repo running the Cursor CLI headless; `staging` branch owned by agents; owner promotes to `main`. Requires a staging deploy in siutindei (appendix A). |
| 9 | Budgets | `staffDailyBudgetUsd` 20; per-task `desk` 1.0, `senior` 3.0, hard 10; `maxRunningTasks` 3 (WP1) → 6 (after WP4); Places USD 20/month; SES outreach cap per #4. |
| 10 | Targets | 50 qualified prospects/week; first touches/day = current cap; 100 % sequence completion; 7 FB posts + 7 IG posts + 7 stories per week; 2 SEO articles/week (WP10); newsletter fortnightly (WP8). |
| 11 | Trust ramp | Promote a class (per prospect type or channel) when ≥ 30 actions in the trailing 14 days and veto rate ≤ 2 %. Demote when veto rate > 10 % over the trailing 20 actions or any breaker fires. Promotion is proposed on the review page and confirmed by the owner; demotion is automatic. |
| 12 | Retention | Tasks, steps, holds, lessons, crawl digests, review snapshots: 90 days TTL. Content rows: 180 days. Prospects, suppression list, watchlist: no TTL. |
| 13 | Models | `desk` = `board_budget.model_for("standup")`, `senior` = `board_budget.model_for("deepDive")`. No new model parameters. |
| 14 | Times (HKT) | Tick every 5 minutes; daily review compiled 07:15 and emailed 07:30; target check 08:00; crawl 03:00; content windows 10:00 and 20:00; quiet hours 22:00–08:00 for all outbound. |
| 15 | Review recipient | `settings.review.digestTo` (one address, owner-set); digest is sent from `board@siutindei.com` via the existing SES identity; not sent while `BoardMailSendingEnabled` is `false`. |
| 16 | Roster in v1 | Seats arrive per WP: none (WP1), `support` `provider-success` `community-manager` (WP3), `business-analyst` (WP4), `market-analyst` (WP5), `prospector` (WP6), `content-marketer` `growth-specialist` (WP7), `accountant` `data-analyst` `security-analyst` (WP9), `architect` `engineer-1` `engineer-2` `product-dev` (WP10). All sixteen are in the contract from WP1; unused ones are `isActive=false` by default. |

## 2. Conventions the developer must follow

- **One PR per WP**, titled `board: WPn <name>`. Each PR includes tests and
  the doc updates listed in the WP. CI (`npm run test` in `apps/admin_web`,
  `check-contracts.py`, lint, CDK build) must be green.
- **Python** (`backend/lambda/admin/`): modules are flat, `from __future__
  import annotations`, type hints, `_log_event(level, tag=..., **fields)`
  for logs, `_json_response(status, body)` for HTTP, `_audit(user_sub,
  ACTION, target, event)` for owner actions. Never `print`. Never store
  unmasked personal data in a prompt path: use `board_pii.Pseudonymizer`.
- **DynamoDB**: single table; every board item has `pk` starting with
  `BOARD#siuTinDei#` (use `board_store.board_pk(suffix)`), `sk`, optional
  `gsi1pk`/`gsi1sk`, optional `expiresAt` (epoch seconds) for TTL. Add
  read/write helpers to `board_store.py` next to the existing ones; do not
  call `table.put_item` from feature modules.
- **Contracts**: new file `contracts/board-staff.json`. Register it in
  `scripts/sync-contracts.py` (copy list, `_load`, constants) so it lands in
  `contract_constants.py`, `apps/admin_web/src/lib/contracts/generated.ts`
  and `backend/infrastructure/lib/shared-contracts.ts`. Run
  `python3 scripts/sync-contracts.py && python3 scripts/check-contracts.py`.
- **Routes**: add branches to `board_routes.handle_board_route` following
  the existing `head == "..."` pattern, and add the path to the route list in
  `lxsoftware-stack.ts` (search for `"/siu-tin-dei/board/approvals"`). Routes
  are admin-JWT unless this document says **public**.
- **Internal events**: add `if event.get("internal") == "<name>"` branches
  in `dispatch.lambda_handler` next to `board_cache_refresh`. Every handler
  first checks `board_store.event_targets_this_board(event)`.
- **Schedules**: use the `siutindeiBoardSchedule(...)` helper in
  `lxsoftware-stack.ts`. Never `events.Rule` on `adminFn`.
- **Async work**: `board_async.invoke_async(payload, fallback=...)`; the
  fallback runs inline so unit tests are deterministic.
- **Tool ops**: register `ToolOp`s in `board_tools.py` in the existing
  `_register_*` style; add the tool to `contracts/board-tools.json` with a
  `defaults` row for all eight personas; the loop, levels, audit and
  approvals then work without further wiring.
- **Tests**: `unittest`, `FakeTable` from `test_board.py`, fakes for every
  external API (no network). New files named in each WP.
- **SPA** (`apps/admin_web`): types in `src/lib/boardModel.ts`, hooks in
  `src/hooks/useBoard*.ts` (TanStack Query, key under `BOARD_QUERY_KEY`),
  components in `src/components/board/`, fixtures in
  `src/lib/mock/fixtures.ts` and route handling in
  `src/lib/mock/mockAdminApi.ts` so `npm run dev:mock` shows every new view.
  Bootstrap 5 utilities; patterns in `apps/admin_web/docs/UI_COMPONENTS.md`.
  Each new section is a tab in `ExecutiveBoardTab.tsx` (`sectionTabs`).
- **Docs**: each WP updates `docs/deployment/admin-website.md` (setup
  steps), `AGENTS.md` (one gotcha line) and `UI_COMPONENTS.md` (new
  components).

## 3. Shared foundations (built in WP1, extended later)

### 3.1 `contracts/board-staff.json`

```json
{
  "seats": [
    {
      "id": "support", "reportsTo": "coo", "title": "Parent Support",
      "modelTier": "desk", "isActiveDefault": false,
      "tools": {"mail": "act", "meta": "act"},
      "brief": "You answer parents who write to Siu Tin Dei by email or WhatsApp. …"
    }
  ],
  "modelTiers": ["desk", "senior"],
  "taskStatuses": ["queued", "running", "review", "returned", "delivered", "needs_owner", "failed", "cancelled"],
  "taskOrigins": ["event", "duty", "target", "minutes", "chat", "owner"],
  "deliverableTypes": ["markdown", "csv", "json", "messages", "issues", "pr", "creatives", "prospects"],
  "holdStatuses": ["scheduled", "executed", "vetoed", "failed", "expired"],
  "actionClasses": ["internal", "inbound_reply", "outbound_known", "cold_outreach", "publish", "spend", "code_staging", "code_production", "never"],
  "prospectTypes": ["provider", "venue", "community", "school", "restaurant", "media"],
  "prospectStages": ["discovered", "qualified", "parked", "contacted", "replied", "onboarding", "listed", "declined", "unresponsive", "suppressed"],
  "watchKinds": ["competitor", "directory", "media", "analogue", "event-source"],
  "contentChannels": ["facebook", "instagram", "instagram_story", "newsletter", "seo", "assisted_xiaohongshu", "assisted_fb_group"],
  "contentStatuses": ["idea", "drafted", "creative", "scheduled", "published", "vetoed", "failed"],
  "limits": {
    "staffStepMaxSeconds": 150, "maxStepsPerTask": 12, "maxRevisions": 2,
    "maxRunningTasksDefault": 3, "staffTaskStuckSeconds": 900,
    "taskBudgetDeskUsd": 1.0, "taskBudgetSeniorUsd": 3.0, "taskBudgetMaxUsd": 10.0,
    "staffDailyBudgetDefaultUsd": 20, "staffDailyBudgetMaxUsd": 100,
    "scratchpadMaxChars": 24000, "deliverableMaxBytes": 2000000,
    "holdDefaultHours": 24, "holdCodeStagingHours": 12, "holdSweepMinutes": 5,
    "tickIntervalMinutes": 5,
    "rampMinActions": 30, "rampPromoteMaxVetoRate": 0.02, "rampDemoteVetoRate": 0.10, "rampWindowDays": 14, "rampDemoteWindowActions": 20,
    "reviewSampleSize": 8,
    "outreachDailyCapStart": 20, "outreachDailyCapStep": 20, "outreachDailyCapMax": 100, "outreachCapStepDays": 7,
    "outreachSequenceDays": [0, 4, 10], "outreachMaxTouches": 3,
    "bounceRateBreaker": 0.05, "complaintRateBreaker": 0.001,
    "placesMonthlyCapUsd": 20, "crawlRequestsPerHostPerSecond": 1, "crawlMaxBytes": 1500000, "crawlMaxPagesPerRun": 200,
    "igPublishesPerDay": 25, "postsPerChannelPerDay": 2,
    "retentionDaysDefault": 90, "retentionDaysContent": 180,
    "lessonsPerSeatInPrompt": 12
  }
}
```

All sixteen seats from the proposal §4 go in `seats[]` with the tool
levels from that table (a level per tool id; tools not listed are `off`).
The developer writes each `brief` from the proposal's "Produces" column in
three to six sentences, in the second person, ending with the sentence
"Report facts you verified with tools; say clearly what you could not
verify."

Constants generated into `contract_constants.py` are prefixed
`BOARD_STAFF_` (for example `BOARD_STAFF_SEATS`, `BOARD_STAFF_MAX_STEPS_PER_TASK`).

### 3.2 DynamoDB keys (all under `BOARD#siuTinDei#…`)

| Suffix (`board_pk(...)`) | sk | gsi1pk / gsi1sk | TTL | Notes |
|---|---|---|---|---|
| `staff#{seatId}` | `STATE` | — | no | Owner overrides: `displayName`, `brief`, `isActive`, `modelTier` |
| `task#{taskId}` | `META` | `BOARD#siuTinDei#tasks#{status}` / `{slaAt}#{taskId}` | 90 d after terminal | Task document (§4 WP1) |
| `task#{taskId}` | `STEP#{seq:03d}` | — | with task | Step log |
| `task#{taskId}` | `REVIEW#{seq:02d}` | — | with task | Manager review |
| `hold#{holdId}` | `META` | `BOARD#siuTinDei#holds#{status}` / `{executeAt}#{holdId}` | 90 d after terminal | Held action |
| `staffusage#{yyyy-mm-dd}` | `STATE` | — | 400 d | `cost`, `calls`, per-seat map |
| `lesson#{lessonId}` | `META` | `BOARD#siuTinDei#lessons#{seatOrPersona}` / `{createdAt}` | 90 d unless `confirmed` | Learning loop |
| `ramp#{classKey}` | `STATE` | — | no | Trailing action/veto counters per class key (for example `cold_outreach:venue`, `publish:instagram`) |
| `breaker#{name}` | `STATE` | — | no | `tripped`, `reason`, `trippedAt`, `resetBy` |
| `review#{yyyy-mm-dd}` | `STATE` | — | 90 d | Compiled daily review snapshot |
| `prospect#{prospectId}` | `META` | `BOARD#siuTinDei#prospects#{stage}` / `{nextTouchAt or updatedAt}#{prospectId}` | no | Pipeline row |
| `prospectkey#{dedupeKey}` | `META` | — | no | Dedupe pointer → `prospectId` |
| `suppress#{digest}` | `META` | — | no | Suppression: sha256 of normalised address/domain, `reason`, `at` |
| `sequence#{sequenceId}` | `STATE` | — | no | Owner-approved sequence templates per prospect type |
| `watch#{watchId}` | `META` | `BOARD#siuTinDei#watch#{kind}` / `{name}` | no | Watchlist row |
| `watch#{watchId}` | `PAGE#{urlDigest}` | — | no | Per-URL `lastHash`, `lastFetchedAt`, `lastDigestKey` |
| `change#{yyyy-mm-dd}#{id}` | `META` | `BOARD#siuTinDei#changes` / `{createdAt}` | 90 d | Detected change note |
| `content#{contentId}` | `META` | `BOARD#siuTinDei#content#{status}` / `{slotAt}#{contentId}` | 180 d | Calendar item |
| `newsletter#sub#{digest}` | `META` | `BOARD#siuTinDei#newsletter#{list}` / `{confirmedAt}` | no | Subscriber (WP8) |
| `outreachday#{yyyy-mm-dd}` | `STATE` | — | 400 d | Sends, bounces, complaints per day |

All are excluded from `/records` scans by the existing filter
`NOT begins_with(pk, :board)` in `dispatch.py`, so no change is needed
there.

### 3.3 Settings additions (`settings` document via `board_store.load_settings`)

Add `normalize_staff_config(raw)` and `normalize_boundaries(raw)` in
`board_store.py`, called from `normalize_tools_config`'s sibling position in
`load_settings`/`save_settings`, so unknown keys are dropped and defaults
filled. Defaults:

```json
"staff": {
  "enabled": false,
  "maxRunningTasks": 3,
  "dailyBudgetUsd": 20,
  "dutiesEnabled": false
},
"review": { "digestTo": "", "digestHourHkt": 7, "sampleSize": 8 },
"boundaries": {
  "reply": {
    "languages": ["en", "zh-HK"],
    "tone": "Warm, plain, brief. Never promise refunds, legal positions, or availability the catalog does not show.",
    "quietHoursHkt": [22, 8],
    "maxOutboundPerChannelPerDay": {"mail": 60, "whatsapp": 60, "meta": 100},
    "maxMessagesPerThreadPerDay": 3,
    "sensitiveTemplatesOnly": ["payment_dispute", "cancellation", "safeguarding", "data_request"]
  },
  "escalation": {
    "keywords": ["refund", "lawyer", "legal", "police", "injury", "hurt", "abuse", "complaint", "media", "journalist", "PDPO", "delete my data", "unsubscribe me from everything"],
    "refundThresholdHkd": 0,
    "ackTemplateId": "ack_escalation"
  },
  "holds": {
    "internal": 0, "inbound_reply": 0, "outbound_known": 0,
    "cold_outreach": 24, "publish": 24, "spend": 24, "code_staging": 12
  },
  "outreach": {
    "fitRubric": "<default text below>",
    "typesEnabled": ["provider", "venue", "community", "school"],
    "districtsFirst": ["Sha Tin", "Tai Po", "Kwun Tong", "Tsuen Wan", "Tseung Kwan O", "Yuen Long"],
    "dailyCap": 20, "capRaisedAt": "",
    "targets": {"qualifiedPerWeek": 50},
    "personalAddressesAllowed": false,
    "webFormsAllowed": false
  },
  "content": {
    "pillars": ["activity spotlight", "district guide", "seasonal guide", "parenting tip", "provider story", "product news"],
    "voice": "Helpful neighbour, not a brand. Specific places, dates and prices. No superlatives.",
    "languages": ["en", "zh-HK"],
    "perWeek": {"facebook": 7, "instagram": 7, "instagram_story": 7, "seo": 2},
    "windowsHkt": [10, 20],
    "assistedChannels": ["assisted_xiaohongshu", "assisted_fb_group"]
  },
  "intel": { "newsletterMailbox": "market@siutindei.com" }
}
```

Default `fitRubric` (ship verbatim, owner edits later):

> Score 0–100. Start at 50. +20 if the organisation runs or hosts activities
> for children aged 0–12 in Hong Kong. +10 if it has a physical venue
> parents can visit. +10 if it publishes prices or a schedule. +10 if it is
> in one of the priority districts. −30 if it is adults-only, a tutoring
> centre focused on exams, or a franchise HQ with no local venue. −50 if the
> website or listing is dead or the business appears closed. Restaurants:
> +15 if they advertise a kids' menu, high chairs or a play corner;
> otherwise −20. Never score above 70 without a working website or a
> Google rating with at least 10 reviews.

### 3.4 Environment and CDK parameters

| Parameter / env | Default | Used by |
|---|---|---|
| `BoardStaffEnabled` → `BOARD_STAFF_ENABLED` | `false` | every staff path (`board_staff.env_enabled()`) |
| `OutreachSendingDomain` → `OUTREACH_SENDING_DOMAIN` | `partners.siutindei.com` | WP6 |
| `OutreachFromLocalPart` → `OUTREACH_FROM_LOCAL_PART` | `partnerships` | WP6 |
| `PublicApiBaseUrl` → `PUBLIC_API_BASE_URL` | existing HTTP API URL | unsubscribe links (WP6), newsletter confirm (WP8) |
| Secret `lxsoftware-admin-siutindei-board-google-places-key` → `GOOGLE_PLACES_KEY_SECRET_ARN` | dummy | WP6 |
| Secret `lxsoftware-admin-siutindei-board-link-signing-key` → `BOARD_LINK_SIGNING_SECRET_ARN` (32 random bytes, generated by CDK `SecretValue`/`generateSecretString`) | generated | WP6, WP8 |
| `BOARD_UNSUB_TABLE`… not needed; same records table | | |

## 4. Work packages

### WP1 — Task engine, `staff` tool, Staff tab

**Goal.** A background task can be created for an executive (seats exist in
the contract but stay inactive), runs as checkpointed steps, produces a
deliverable in S3, is reviewed by the chair, and is visible in the SPA.

**Backend files.**

- `contracts/board-staff.json` (§3.1), sync script changes.
- `board_staff.py` (new): seats, tasks, steps, review.
- `board_store.py`: helpers `put_task`, `get_task`, `list_tasks(status=None,
  limit)`, `claim_task_step(table, task_id, expected_step) -> bool`
  (conditional update, mirrors `claim_meeting_phase`), `put_task_step`,
  `list_task_steps`, `put_task_review`, `load_staff_overrides`,
  `save_staff_override`, `delete_staff_override`, `load_staff_usage_day`,
  `add_staff_usage_day(table, seat_or_persona, usage)`.
- `board_tools.py`: new tool `staff` (ops below); new internal tool `task`
  (ops `task_note`, `task_finish`) available only in `ctx.kind == "task"`
  at level `act` regardless of the matrix (implement in `available_ops`:
  `if op.tool_id == "task": level = "act" if context == "task" else "off"`).
  `ToolContext` gains `task_id: str = ""` and `seat_id: str = ""` (when a
  seat is working, `persona_id` is the **manager** persona for level
  derivation and `seat_id` identifies the worker); `ToolContext.public()`
  includes both. `add_tool_call` rows gain `taskId`/`seatId`.
- `board_personas.py`: `render_seat_prompt(seat, manager_profile, charter,
  lessons: list[str]) -> str` (structure in proposal §4) and
  `render_task_frame(task, scratchpad) -> str` (the user-message that
  starts each step: brief, deliverable type, budget left, steps left,
  scratchpad, and the instruction "Either call task_note to record
  progress and continue, or call task_finish when done. Do not call
  task_finish without evidence tool calls unless the brief needs none.").
- `dispatch.py`: `internal == "board_staff_step"` → `board_staff.run_step`,
  `internal == "board_staff_review"` → `board_staff.run_review`,
  `internal == "board_staff_tick"` → `board_staff.handle_tick` (WP1: queue
  drain and stuck sweep only; WP2 adds holds).
- `board_routes.py`: routes below.

**Task document** (`task#{taskId}` / `META`):

```
taskId, status, assignee (persona id or seat id), assigneeKind ("persona"|"seat"),
managerId (persona id), origin, eventRef {kind, id} | null, actionId | null,
meetingId | null, brief (≤ 4000 chars), deliverableType, budgetUsd, slaAt,
step (int, 0 = not started), stepsUsed, revisions, usage {promptTokens,
completionTokens, cost, calls}, scratchpadKey (S3) | "", scratchpadChars,
deliverableKey | "", deliverableBytes, summary, evidence [callIds],
openQuestions [], actions [holdId|approvalId], confidence, reviews (count),
lastReview {verdict, notes, at} | null, createdAt, createdBy (sub|"schedule"|persona),
updatedAt, startedAt, finishedAt, failureReason, expiresAt (set on terminal)
```

**Functions (`board_staff.py`).**

- `env_enabled() -> bool` (`BOARD_STAFF_ENABLED` not in false-set) and
  `enabled(settings) -> bool` (env and `settings.staff.enabled`).
- `seats(table) -> list[dict]`: contract seats merged with overrides;
  each gets `effectiveLevels` = for every tool id
  `min(rank(seat.tools[tool] or "off"), rank(effective_level(settings,
  tool, seat.reportsTo)), rank(global_cap))`. Expose `seat_level(settings,
  seats_by_id, seat_id, tool_id) -> str` and make `board_tools.
  effective_level` accept a `seat_id` keyword that applies this rule.
- `create_task(table, settings, *, assignee, origin, brief,
  deliverable_type, budget_usd=None, sla_hours=24, event_ref=None,
  action_id=None, meeting_id=None, created_by) -> dict`: validates
  assignee (persona id or active seat id), caps `budget_usd` to
  `taskBudgetMaxUsd` and defaults it by tier, writes the row with
  `status="queued"`, then calls `drain_queue(table, settings)`.
- `drain_queue(table, settings)`: counts `running` + `review` tasks; while
  below `settings.staff.maxRunningTasks`, takes the earliest `slaAt` queued
  task, sets `running` via `claim_task_step(task_id, expected_step=0)` and
  `invoke_async({"internal": "board_staff_step", "boardKey": "siuTinDei",
  "taskId": ..., "step": 1}, fallback=run_step)`.
- `run_step(payload)`: 
  1. Load task; return if status not `running` or `payload.step != task.step + 1`
     (idempotency; a duplicate async delivery is a no-op).
  2. Check `board_budget.check_budget` **and** staff daily budget
     (`load_staff_usage_day().cost < settings.staff.dailyBudgetUsd`) and
     `task.usage.cost < task.budgetUsd`; on any failure call
     `_finish_incomplete(reason)`.
  3. Load scratchpad from S3 (`board/siuTinDei/staff/{taskId}/scratchpad.md`,
     empty if none). Build messages: system = seat or persona prompt; user =
     `render_task_frame`.
  4. `ctx = ToolContext(kind="task", persona_id=managerId if seat else
     assignee, seat_id=..., task_id=..., display_name=...)`; call
     `run_tool_loop(ctx=ctx, messages=..., model=tier model,
     max_seconds=BOARD_STAFF_STEP_MAX_SECONDS, ...)`.
  5. The loop returns text plus recorded calls. If `task_finish` was
     called, `_on_finish` (below). Else append the model's text to the
     scratchpad (cap `scratchpadMaxChars`, keep the tail), write it, record
     `STEP#{seq}` with `plan` (model text ≤ 2000 chars), `callIds`,
     `usage`, `add_staff_usage_day`, increment `task.step`, and if
     `task.step >= maxStepsPerTask` → `_finish_incomplete("step limit")`
     else `invoke_async` for `step + 1`.
- `op task_note(text)`: appends to the scratchpad; returns `{ok: true,
  chars}`. `op task_finish(summary, deliverableType, deliverable (string,
  ≤ deliverableMaxBytes when UTF-8 encoded), evidence[], openQuestions[],
  confidence)`: validates `evidence` ⊆ call ids recorded in this task; if
  empty and `confidence == "high"`, sets `confidence = "medium"` and
  `flags += ["no_evidence"]`; writes the deliverable to
  `board/siuTinDei/staff/{taskId}/deliverable.{md|csv|json}`; sets task to
  `review`; `invoke_async({"internal": "board_staff_review", ...})`.
- `run_review(payload)`: manager persona (the chair when the assignee is a
  persona — the CEO by default — otherwise `seat.reportsTo`), JSON mode,
  prompt: brief, deliverable (≤ 12 000 chars, rest summarised as "[…
  truncated]"), evidence summaries from `list_tool_calls` filtered by
  `taskId`, instruction to return `{"verdict": "accept"|"return", "notes":
  "…"}`. `accept` → `delivered`, `finishedAt`, `expiresAt`; if `actionId`
  and `deliverableType` in (`markdown`, `csv`, `json`, `issues`, `pr`) →
  append a note to the action and set `status="done"`,
  `closedBy="staff:{taskId}"`. `return` → if `revisions <
  maxRevisions`: `revisions += 1`, status `running`, scratchpad gets
  "MANAGER NOTES: …", next step invoked; else `delivered` with
  `lastReview.verdict="return"` kept.
- `handle_tick(event)`: `drain_queue`; stuck sweep: tasks `running` whose
  `updatedAt` is older than `staffTaskStuckSeconds` are `_finish_incomplete
  ("stuck")`; tasks in `review` older than the same → re-invoke review once,
  then `needs_owner`.
- `cancel_task(table, task_id, by_sub)`; `owner_review(table, task_id,
  verdict, notes, by_sub)` (overrides).
- Context pack: `board_context.build_context_pack` gets a new capped source
  `staffDelivered` (last 10 delivered summaries since the last meeting) and
  `staffInFlight` (count and titles), rendered under "STAFF WORK".
- Minutes: `board_meeting.normalize_action_proposal` accepts `assignee`
  (persona or active seat id; anything else dropped). In `_phase_persist`,
  for each created action with `assignee`, when `enabled(settings)` and the
  chair's `staff` level allows: call `staff_assign` through `execute_call`
  with a chair `ToolContext` (so `propose` yields an Approval and `act`
  creates the task).

**`staff` tool ops** (all `contexts=("chat","meeting","task")`):

| op | kind | args | behaviour |
|---|---|---|---|
| `staff_assign` | write | `assignee`, `brief`, `deliverableType`, `slaHours` (1–168), `budgetUsd?`, `actionId?` | `create_task`; summary "Assigned {assignee}: {brief[:80]}". `act_guard`: returns a reason when `running+review >= maxRunningTasks*2` ("queue full") so it downgrades to approval |
| `staff_list_tasks` | read | `status?`, `limit?` | own tasks for seats; all for personas |
| `staff_get_deliverable` | read | `taskId` | summary + first 6 000 chars of the deliverable |
| `staff_request_revision` | write | `taskId`, `notes` | manager only (persona == task.managerId) |
| `staff_cancel_task` | write | `taskId`, `reason` | manager or owner |

Contract row in `board-tools.json`: `{"id":"staff","label":"Staff","maxLevel":"act","defaults":{"ceo":"propose","cfo":"propose","coo":"propose","cpo":"propose","cto":"propose","cio":"propose","ciso":"propose","cmo":"propose"}}`.

**Routes** (add to `board_routes.py` and the CDK route list):

| Method | Path | Handler |
|---|---|---|
| GET | `/siu-tin-dei/board/staff` | seats with effective levels, overrides, counts by status |
| PUT | `/siu-tin-dei/board/staff/{seatId}` | override `displayName`, `brief` (≤ 2000), `isActive`, `modelTier`; audit `BOARD_STAFF_PUT` |
| DELETE | `/siu-tin-dei/board/staff/{seatId}` | reset; audit `BOARD_STAFF_RESET` |
| GET | `/siu-tin-dei/board/tasks?status=&assignee=&limit=` | list (gsi1 by status; default all non-terminal + last 50 terminal) |
| POST | `/siu-tin-dei/board/tasks` | owner creates a task `{assignee, brief, deliverableType, slaHours, budgetUsd?}`; audit `BOARD_TASK_CREATE` |
| GET | `/siu-tin-dei/board/tasks/{taskId}` | task + steps + reviews + presigned deliverable URL (15 min) |
| POST | `/siu-tin-dei/board/tasks/{taskId}/cancel` | audit `BOARD_TASK_CANCEL` |
| POST | `/siu-tin-dei/board/tasks/{taskId}/review` | `{verdict, notes}` owner override; audit `BOARD_TASK_REVIEW` |

**CDK.** `BoardStaffEnabled` parameter → env; `SiutindeiBoardStaffTickSchedule`
(`lxsoftware-admin-siutindei-board-staff-tick`, `rate(5 minutes)`, input
`{internal: "board_staff_tick"}`, retry 0); `adminFn` needs
`s3:PutObject/GetObject` on `board/siuTinDei/staff/*` of the assets bucket
(verify the existing grant covers the `board/` prefix; if it is
bucket-wide already, do nothing).

**SPA.** `boardModel.ts`: `BoardSeat`, `BoardTask`, `BoardTaskStep`,
`BoardTaskReview`, `BoardTaskStatus`. Hooks `useBoardStaff` (seats, override
mutations) and `useBoardTasks` (list with 10 s polling while any task is
`running`/`review`; detail query; cancel/review/create mutations).
Components: `BoardStaffSection.tsx` (org chart grouped by manager: seat
card with active toggle, tier select, brief editor via `AdminEditorSection`;
task board as five columns `Queued / Running / Review / Needs owner /
Delivered` with cost per card; "New task" form), `BoardTaskDrawer.tsx`
(`BoardOffcanvas` with brief, step log with collapsible tool calls reusing
`BoardToolCallList` rows, deliverable preview via `BoardMarkdown` or a
CSV table, review verdict, Accept / Return / Cancel). New section id
`staff` in `ExecutiveBoardTab`, count badge = tasks in `needs_owner`.
Fixtures: three seats, five tasks across statuses.

**Tests.** `test_board_staff.py`: seat level derivation (seat ≤ manager ≤
global cap; benched manager → `off`); `create_task` validation and budget
defaults; `drain_queue` respects `maxRunningTasks`; `run_step` idempotency
(duplicate payload no-op), scratchpad tail cap, step limit → incomplete;
`task_finish` evidence rule; review accept closes action; return → revision
→ second return → delivered; stuck sweep; routes (200/400/404) with
`FakeTable` and a `FakeOpenRouter` that returns scripted tool calls.
Vitest: `useBoardTasks` polling predicate. Playwright: Staff tab renders in
`dev:mock`.

**Acceptance.** With both flags on, `POST /tasks` for `cfo` with brief
"List our three biggest monthly costs from AWS and finance" produces a
delivered Markdown deliverable whose `evidence` lists `aws_monthly_cost`
and `finance_*` calls, and the CEO review row exists. With `BOARD_STAFF_ENABLED=false`
the same POST returns 409 `{"message": "Staff is disabled"}`.

**Potential issues.**

- *Duplicate async invocations.* Lambda `Event` invokes retry twice on
  failure. Every step must be idempotent through `claim_task_step`; never
  write the step row before the claim succeeds.
- *Scratchpad and 400 KB items.* Keep the scratchpad in S3, never in the
  item; only `scratchpadChars` in DynamoDB.
- *Tool loop assumes chat/meeting.* `run_tool_loop` builds a final answer
  without tools; for tasks the final text is the step note. Do not change
  the loop's contract; wrap it.
- *`task_finish` called with a huge deliverable.* Reject above
  `deliverableMaxBytes` with a structured error so the model splits it.
- *Budget accounting.* `board_budget.board_completion` records into the
  board's `usage#` row. Add a `usage_sink` hook (callable) so task calls
  are recorded in **both** the board day row (global cap still applies) and
  `staffusage#`.
- *Chair review of its own task.* When the CEO is the assignee, the
  reviewer is the CFO (fixed fallback) to keep producer ≠ reviewer.

### WP2 — Hold windows, action classes, veto

**Goal.** Every write op is classified; classes with a non-zero hold are
scheduled instead of executed; a sweep executes due holds; the owner can
veto. Nothing changes for classes with hold 0 or for `propose`-level calls.

**Backend.**

- `board_holds.py` (new): `classify(op, ctx, args, settings) -> tuple[str,
  str]` returns `(actionClass, classKey)`. Rules, in order:
  1. `op.tool_id in ("board", "staff", "task")`, GitHub issue/comment/label
     ops, `product_flag_listing`, `security_open_remediation`,
     `aws_propose_budget_alert`, `finance_draft_invoice`,
     `finance_propose_price_change`, `finance_record_manual_payment`,
     `finance_match_payment` → `internal`.
  2. `mail_reply`, `meta_reply_comment`, `meta_reply_dm`,
     `meta_reply_whatsapp`, `stores_reply_review` → `inbound_reply`
     (classKey `inbound_reply:{channel}`).
  3. `mail_send` / `mail_forward` / `finance_send_invoice` /
     `finance_send_reminder` / `meta_relay_lead` where every recipient is
     allow-listed (`board_mail.recipient_allowed`) or is a prospect in stage
     `replied`+ → `outbound_known`; otherwise `cold_outreach:{prospectType
     or "unknown"}`.
  4. `meta_propose_post`, `meta_propose_story`, `stores_draft_release_notes`,
     `content_publish` (WP7), `newsletter_send` (WP8) → `publish:{channel}`.
  5. `meta_create_ad_set`, `meta_boost_post` → `spend:meta`.
  6. `code_merge_staging` (WP10) → `code_staging`. Anything else that is a
     write → `internal`.
- `hold_hours(settings, action_class, class_key) -> int`:
  `settings.boundaries.holds[class]`, overridden by
  `settings.boundaries.holdOverrides[classKey]` when present (the trust ramp
  writes there), and forced to the class default when
  `breaker#{class}` is tripped.
- Integration in `board_tools.execute_call`: after level checks decide the
  call would **execute** (level `act`, no `act_guard` reason, not
  `always_propose`), and when `ctx.actor != "hold"`: compute class; if hours
  > 0 → `create_hold(...)` and return `ToolOutcome(status="held",
  result={"holdId":..., "executeAt":...}, summary="Scheduled … (executes
  {executeAt} unless vetoed)")`. New status `held` is added to
  `BoardToolCallStatus` in the SPA and to the audit row. The model is told
  in `tools_preamble` that "held" means it will happen automatically
  unless the founder vetoes; it must say "I have scheduled …".
- Hold document (`hold#{holdId}`/`META`): `holdId, status, actionClass,
  classKey, personaId, seatId, taskId, op, toolId, arguments (masked as
  stored on approvals), preview (owner-facing, via `render_preview`),
  summary, createdAt, executeAt, executedAt, vetoedAt, vetoBy, vetoReason,
  result {callId|error}, expiresAt`.
- `execute_due(table, settings, now_iso, limit=25)`: query gsi1
  `holds#scheduled` with `gsi1sk <= now`; for each, `claim_hold(hold_id,
  "scheduled" → "executing")` then `execute_call` with a reconstructed
  `ToolContext(actor="hold", persona_id, seat_id, ...)`; on success
  `executed`; on exception `failed` with the error (no retry — the review
  page shows failures). Quiet hours: if `executeAt` falls inside
  `boundaries.reply.quietHoursHkt`, `create_hold` moves it to the next
  08:00 HKT.
- `veto(table, hold_id, by_sub, reason)`; `veto_class_today(table,
  class_key, by_sub)`.
- `board_staff.handle_tick` calls `board_holds.execute_due` first.
- Ramp counters: on `executed` → `ramp#{classKey}.actions += 1` with a
  rolling 14-day daily map; on `vetoed` → `.vetoes += 1`. `ramp_state(table,
  class_key) -> {actions, vetoes, rate, eligibleForPromotion, shouldDemote}`
  using §1 #11 thresholds. Demotion applies immediately by deleting the
  `holdOverrides[classKey]` entry and logging `board_ramp_demoted`.

**Routes.**

| Method | Path | Purpose |
|---|---|---|
| GET | `/siu-tin-dei/board/holds?status=&limit=` | list (default `scheduled`, soonest first) |
| POST | `/siu-tin-dei/board/holds/{holdId}/veto` | `{reason}`; audit `BOARD_HOLD_VETO` |
| POST | `/siu-tin-dei/board/holds/veto-class` | `{classKey}`; vetoes every scheduled hold of that key due in the next 24 h; audit `BOARD_HOLD_VETO_CLASS` |
| PUT | `/siu-tin-dei/board/boundaries` | full `boundaries` document, normalised; audit `BOARD_BOUNDARIES_PUT` |
| GET | `/siu-tin-dei/board/ramp` | ramp state per class key |

**SPA.** `BoardHoldsList.tsx` (grouped by class, countdown to `executeAt`,
preview via the existing approval preview components, Veto button, "Veto
all of this class today"); shown inside the Approvals section as a second
block titled "Scheduled (veto to stop)". `BoardBoundariesCard.tsx` in
Settings: holds table (hours per class), reply policy fields, escalation
keywords editor. Hook `useBoardHolds`, `useBoardBoundaries`.

**Tests.** `test_board_holds.py`: classification table (one assertion per
op), hold creation from `execute_call` at `act`, quiet-hours shift,
`execute_due` claims and executes through the real `execute_call` with a
fake mail sender, veto prevents execution, veto-class, ramp counters and
thresholds, breaker forces default hold.

**Acceptance.** With CMO at `act` on `meta` and `holds.publish = 24`, a
`meta_propose_post` call in chat returns `held`, appears under Scheduled,
executes 24 h later in the tick (test with a clock override), and a veto in
between leaves it `vetoed` with no Graph call.

**Potential issues.**

- *Approvals vs holds confusion.* Keep them separate lists and separate
  statuses; an Approval is "the owner must say yes", a hold is "the owner
  may say no". Never convert one into the other.
- *Hold executes with stale data.* Replies scheduled hours later may be
  answered by the human in between. For `inbound_reply` class the hold is 0
  by default so this rarely matters; for `mail_reply` executed from a hold,
  re-check that the thread has no newer inbound message than when the hold
  was created (`arguments.threadLastMessageAt`); if it does → `failed:
  "thread changed"`.
- *Tick overlap.* Two ticks may run concurrently after a slow one;
  `claim_hold` conditional updates make double execution impossible.
- *Clock.* All comparisons in UTC ISO strings; HKT only for quiet hours and
  display.

### WP3 — Triage, reply policy, escalation, first seats

**Goal.** Inbound mail, Meta events and store reviews create tasks for
`support`, `provider-success` and `community-manager`; replies happen under
the reply policy; escalations go to `needs_owner`.

**Backend.**

- `board_triage.py` (new): `on_mail_ingested(table, settings, thread,
  message)` called at the end of `board_mail.ingest_bytes` (only when
  `board_staff.enabled(settings)` and the message is inbound and not from
  an own domain); `on_meta_event(table, settings, thread, msg)` called from
  `board_meta._store_inbound`; `on_store_reviews(table, settings,
  new_reviews)` called from `board_stores.refresh_caches` when it detects
  review ids not seen before (keep a `cache` entry `stores:seen_review_ids`).
- `classify_text(table, settings, text, *, channel) -> dict` with keys
  `audience` (`parent`|`provider`|`vendor`|`unknown`), `intent`
  (`question`|`booking`|`complaint`|`billing`|`partnership`|`spam`|`other`),
  `escalate: bool`, `reason`. Implementation: (1) keyword pass using
  `boundaries.escalation.keywords` (case-insensitive, both scripts) →
  `escalate=True`; (2) if the sender is a prospect (`prospectkey#` lookup by
  domain) → `provider`; (3) otherwise one `desk` model call in JSON mode
  with the fixed label set and a 12 s timeout, cached by text digest for 7
  days. On model failure → `audience="unknown"`, `escalate=True`.
- Routing table (proposal §6) → `create_task(origin="event",
  event_ref={kind:"mail"|"meta"|"review", id}, assignee=..., brief=
  render_event_brief(...), deliverableType="messages", slaHours=...)`.
  Escalations create the task with `status="needs_owner"` directly and
  send the acknowledgement template through the normal write path
  (`mail_reply`/`meta_reply_*` with `templateId="ack_escalation"`, class
  `inbound_reply`).
- Dedupe: one open task per thread (`eventRef.id`); a new message on a
  thread with an open task appends "NEW MESSAGE: …" to that task's
  scratchpad instead of creating another.
- Reply policy enforcement lives in the write ops, not in the prompt only:
  `board_policy.py` (new) `check_reply(settings, ctx, op, args, thread) ->
  str | None` returns a reason when: quiet hours (→ hold to 08:00 rather than
  refuse), per-thread daily count reached, per-channel daily count reached,
  body contains a forbidden promise pattern (regexes for refund amounts,
  "guarantee", "we will hold the place"), body contains a phone number or
  email that is not the recipient's own, or the intent is in
  `sensitiveTemplatesOnly` and `templateId` is missing. Wire it as an
  `act_guard` on the reply ops so a violation becomes an Approval with the
  reason.
- Templates: `board_templates.py` with a dict of template ids → text in
  `en` and `zh-HK` with `{placeholders}`; `ack_escalation`, and one per
  `sensitiveTemplatesOnly` entry. Owner-editable later; hard-coded in WP3.
- Seats `support`, `provider-success`, `community-manager` set
  `isActiveDefault: true` in the contract (the only three that default on).
- Rate counters: `outreachday#` is WP6; for replies use
  `board_store.add_external_usage_day(table, f"reply:{channel}")` and a
  per-thread counter on the thread row (`repliesToday`, `repliesDate`).

**Routes.** None new. `GET /siu-tin-dei/board/tasks` already shows them.

**SPA.** Task cards show the event source (mail subject, review stars,
channel icon). `BoardTaskDrawer` renders `messages` deliverables as the
list of sent/held/proposed messages with links to the mail thread.

**Tests.** `test_board_triage.py`: keyword escalation in both scripts,
prospect-domain routing, model-classification fake, one-task-per-thread,
ack template sent through `execute_call`, policy guard cases (quiet hours →
hold, per-thread cap, forbidden promise → approval), review-detection
dedupe.

**Acceptance.** In `dev`, ingest a fixture MIME from a parent asking about
swimming in Sha Tin → a `support` task exists within one tick, a
`mail_reply` executes (hold 0), the thread shows the outbound copy, the
task is `delivered` after the COO's review. Ingest a MIME containing "my
son was injured" → task `needs_owner`, ack sent, no other reply.

**Potential issues.**

- *Ingest path runs inside the S3 event Lambda with its own timeout.*
  Triage must only write the task row and call `drain_queue` (async);
  never run a model call inside ingest except `classify_text`, which is
  bounded to 12 s and skipped when fewer than 20 s remain
  (`context.get_remaining_time_in_millis` is not available in the ingest
  function today; pass a `deadline` from `inbound_email_handler`).
- *Own outbound copies re-triggering triage.* `ingest_bytes` indexes
  outbound copies too; check `direction == "inbound"`.
- *Chinese keyword matching.* No word boundaries in Chinese; match
  substrings for zh keywords and whole words for Latin ones.
- *Classifier cost.* Cache by text digest; at expected volumes this is
  under USD 0.50/day.
- *Replying to auto-responders and newsletters.* Skip triage when headers
  contain `Auto-Submitted`, `List-Unsubscribe`, or `Precedence: bulk`.

### WP4 — Daily review, digest, breakers, lessons, ramp UI

**Goal.** The owner has one page and one email; breakers protect the
system; corrections become lessons; the ramp is visible.

**Backend.**

- `board_review.py` (new): `compile(table, settings, date_hkt) -> dict`
  writes `review#{date}` with sections: `headline` (task counts, messages
  by channel from tool-call rows, holds executed/vetoed, spend from
  `usage#` and `staffusage#`, later: pipeline, content, market), `holdsDue`
  (next 24 h), `escalations` (tasks `needs_owner` with suggested reply =
  first held/proposed message in the task, if any), `sample` (random
  `reviewSampleSize` executed actions of hold-0 classes from yesterday,
  with `callId`, summary, preview), `breakers` (tripped), `suggestions`
  (ramp promotions eligible, from `ramp_state`), `assisted` (WP7), `market`
  (WP5), `promotion` (WP10). `business-analyst` (active from WP4) gets a
  duty task at 07:00 HKT: "Write the three-sentence headline for today's
  review from this JSON" — the deliverable is stored as `review.narrative`.
  If the task has not delivered by 07:25, the digest goes out without it.
- `send_digest(table, settings, review)`: HTML + text email through
  `board_mail.send_plan` (from `board@siutindei.com`, to
  `settings.review.digestTo`), one link per section to the SPA
  (`https://<adminWebDomain>/siu-tin-dei?tab=board&section=review#…`).
  Skipped with a log line when `digestTo` is empty or sending is disabled.
- `dispatch.py`: `internal == "board_review_compile"` and
  `"board_review_send"`.
- `board_breakers.py` (new): `trip(table, name, reason)`, `reset(table,
  name, by_sub)`, `is_tripped(table, name)`, and `evaluate(table,
  settings)` run every tick with rules: `class:{classKey}` (ramp demote →
  hold restored, not a full stop), `channel:{channel}` (a reply or post
  whose thread later triggers escalation keywords within 24 h), `budget`
  (staff spend ≥ 80 % before 12:00 HKT → set `settings.staff.
  seniorPaused=true`; ≥ 100 % → `settings.staff.enabled=false` with reason
  stored), `tool:{toolId}` (≥ 10 errors in the last hour from tool-call
  rows), and later `outreach` (WP6). Every write op checks
  `is_tripped("channel:…")`/`("tool:…")` in `execute_call` and returns a
  structured error. Tripping writes an `update` row ("BREAKER …") so the
  next stand-up sees it.
- `board_lessons.py` (new): `create_from_veto(hold)`,
  `create_from_correction(call_id, note)`, `create_from_return(task)`;
  each writes `lesson#` with `subject` (seat or persona), `classKey`,
  `what`, `instruction` (one sentence, drafted by a `desk` call given the
  action preview and the owner's note; ≤ 200 chars), `confirmed=false`.
  `confirm`, `dismiss`. `render_seat_prompt`/`render_system_prompt`
  include the last `lessonsPerSeatInPrompt` confirmed lessons for that
  subject under "STANDING INSTRUCTIONS FROM THE FOUNDER".

**Routes.**

| Method | Path | Purpose |
|---|---|---|
| GET | `/siu-tin-dei/board/review?date=` | today's (or given) snapshot; compiles on demand if missing |
| POST | `/siu-tin-dei/board/review/sample/{callId}/wrong` | `{note}` → lesson draft; audit `BOARD_REVIEW_WRONG` |
| GET | `/siu-tin-dei/board/lessons` | list |
| POST | `/siu-tin-dei/board/lessons/{id}/confirm` and `/dismiss` | `{instruction?}` edited text on confirm |
| GET | `/siu-tin-dei/board/breakers` | state |
| POST | `/siu-tin-dei/board/breakers/{name}/reset` | audit `BOARD_BREAKER_RESET` |
| POST | `/siu-tin-dei/board/ramp/{classKey}/promote` | sets `holdOverrides[classKey]=0`; audit `BOARD_RAMP_PROMOTE` |

**CDK.** Schedules `…-board-review-compile` (07:15 HKT) and
`…-board-review-send` (07:30 HKT).

**SPA.** `BoardReviewSection.tsx` — the page in proposal §9 order; each
sample row has "This was wrong" opening a small form; each suggestion has
Accept (promote) / Later; breakers with Reset; `BoardLessonsList.tsx` in
Settings. Section `review` becomes the **default** section of the tab when
staff is enabled. Digest email preview link.

**Tests.** `test_board_review.py`: compile with fixtures for every section,
sample is deterministic under a seeded RNG, digest HTML contains every
section link, skip when `digestTo` empty; `test_board_breakers.py`: each
rule, execute_call refuses when tripped, reset; `test_board_lessons.py`:
lesson drafting fake, confirm renders into prompt.

**Acceptance.** Owner receives the 07:30 email; vetoing a hold from the
page creates a lesson draft; confirming it changes the next task's system
prompt (assert in test); budget breaker flips `settings.staff.enabled`.

**Potential issues.**

- *Digest before compile finishes.* Two schedules 15 min apart; the send
  handler compiles if the snapshot is missing.
- *Email HTML.* Use table-based, inline-styled HTML; no external CSS.
- *Sampling privacy.* Sample rows show owner-facing previews (unmasked) —
  this is the owner's page, same as Approvals.
- *Breakers vs settings writes.* Breakers mutate `settings`; use
  `save_settings` with a fresh load to avoid clobbering concurrent owner
  edits (read-modify-write with a `version` attribute; add one if
  `save_settings` lacks it).

### WP5 — Market and competitor intelligence

**Goal.** A watchlist is crawled daily, changes become notes, a weekly brief
is produced, gaps feed prospecting (WP6 consumes them), ideas become actions
or issues.

**Backend.**

- `board_crawl.py` (new): `fetch(url, *, max_bytes, timeout=10) ->
  FetchResult(status, final_url, content_type, text, hash)` using
  `urllib.request` with a fixed UA `SiuTinDeiBoardBot/1.0 (+https://siutindei.com/bot)`;
  `robots_allows(url)` via `urllib.robotparser` cached 24 h in `cache`;
  per-host pacing with a `cache` row `crawl:host:{host}` storing
  `lastFetchAt` (sleep to respect 1 rps within a run; across runs it is
  naturally spaced); `html_to_text` = `board_mail.html_to_text` plus
  removal of `<script>`, `<style>`, `<nav>`, `<footer>`; `normalise(text)`
  strips digits-only tokens longer than 6, ISO dates, times, and
  whitespace before hashing so counters and timestamps do not create false
  changes; `digest(text)` = first 6 000 chars stored to S3
  `board/siuTinDei/intel/{watchId}/{urlDigest}/{yyyy-mm-dd}.txt`.
- `board_opendata.py` (new): `fehd_licensed_premises() -> list[dict]`
  (download the FEHD "Licensed Restaurants" dataset from data.gov.hk; the
  format is CSV/XML with Chinese and English names and addresses — **verify
  the current dataset URL and columns at build time, record them in the
  module docstring**, parse both languages, map address to district by a
  fixed district keyword table `HK_DISTRICTS` in `board_hk.py`);
  `edb_schools() -> list[dict]` (EDB school list, same approach);
  `lcsd_programmes()` (WP6 uses it). All cached 7 days in S3 with a
  `cache` pointer; each function returns at most 5 000 rows and a
  `fetchedAt`.
- `board_watch.py` (new): watchlist CRUD; `discover(table, settings)`
  weekly: runs `research_search` for the 20 fixed target queries in
  `TARGET_QUERIES` (developer writes them: "kids activities Hong Kong",
  "children classes booking Hong Kong", "兒童活動 香港", "親子活動 預約"… 10
  EN, 10 ZH), collects result domains not in the watchlist and not in
  `IGNORED_DOMAINS` (google, facebook, instagram, youtube, wikipedia,
  gov.hk), and inserts them as `kind="candidate"` with the homepage URL;
  a candidate seen in two different weekly runs is promoted to
  `competitor` automatically; candidates never seen again expire after 60 d.
- `board_intel.py` (new): `daily_crawl(table, settings)`: for each watch
  row and each page, fetch, hash, compare; on change write `change#` with
  `watchId, url, kind ("pricing"|"features"|"categories"|"other" by URL
  tag), before/after digest keys, and a one-line summary from a `desk`
  call given the two digests (≤ 200 chars)`. `public_store_data(app_id,
  platform)` via the iTunes lookup API and the App Store customer-reviews
  RSS for `hk`, and the public Play store page for the Android id (text
  only). `weekly_brief(table, settings)` creates a `senior` task for
  `market-analyst` with a brief that lists: all changes this week, the
  competitors' latest review texts (≤ 40), `product_catalog_health`
  output, the seasonal calendar (EDB holidays), and asks for the
  deliverable structure in proposal §7.2 as Markdown with a final
  fenced JSON block `{"gaps":[{"category","district","competitorCount"}],
  "ideas":[{"title","why","effort"}],"prospects":[{"name","type","url"}]}`.
  `on_brief_delivered(task)`: parse the JSON block; `gaps` → `cache`
  `intel:gaps` (WP6 reads it); `ideas` → `board_add_action` as CPO with
  priority `later` (dedupe by `find_similar_open_action`); `prospects` →
  WP6 `upsert_prospect(source="intel")` when WP6 exists, else stored in
  `cache` `intel:prospects`.
- Tool ops for `market-analyst` (tool id `intel`, read-only, maxLevel
  `read`, defaults `read` for CEO/CPO/CMO/COO, `off` others):
  `intel_list_watchlist`, `intel_get_changes(days)`, `intel_fetch_page(url)`
  (crawl a single allowed URL on demand, robots-checked),
  `intel_competitor_reviews(watchId)`, `intel_search_rank(query)`.
- `dispatch.py`: `internal == "board_intel_crawl"` (daily) and
  `"board_intel_weekly"`.

**Routes.**

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/siu-tin-dei/board/watchlist` | list; add `{name, kind, urls[], appIds{ios,android}, socialHandles[]}` |
| PUT/DELETE | `/siu-tin-dei/board/watchlist/{watchId}` | edit; remove |
| GET | `/siu-tin-dei/board/changes?days=7` | change notes with digest links |

**CDK.** Schedules `…-board-intel-crawl` (03:00 HKT daily) and
`…-board-intel-weekly` (Monday 04:00 HKT). Assets bucket prefix
`board/siuTinDei/intel/*`. Outbound HTTP from the Lambda is already
unrestricted (verify no VPC).

**SPA.** `BoardMarketSection.tsx`: watchlist table with add/edit,
candidates with Promote/Ignore, change notes timeline with before/after
digest view, latest brief link (opens the task drawer). Section `market`.

**Tests.** `test_board_intel.py`: robots denial, pacing, normalisation
removes counters, change detection, candidate promotion after two runs,
brief JSON extraction and idea dedupe, FEHD parser on a saved fixture
file (`test_fixtures/fehd_sample.csv`).

**Acceptance.** Add one competitor with a pricing URL; change the fixture
served by a local fake; the next crawl writes a `change#` row and the
Market section shows it. Weekly brief task delivers and creates at least
one `later` action.

**Potential issues.**

- *Lambda time.* 200 pages × up to 10 s is too slow for one invocation.
  `daily_crawl` processes at most 40 pages per invocation and self-invokes
  with a cursor (`{"internal":"board_intel_crawl","cursor":...}`) until
  done; total pages per run capped by `crawlMaxPagesPerRun`.
- *JavaScript-rendered sites.* Plain fetch may return an empty shell. Store
  `emptyBody=true` on the page row after two empty fetches and stop
  fetching it; show "not readable" in the UI. No headless browser.
- *Bot blocking (403/429).* Back off that host for 7 days; never rotate UAs
  or use proxies.
- *Copyright.* Store digests (≤ 6 000 chars) and quotes, never whole
  pages.
- *data.gov.hk changes.* Datasets move; the module logs
  `board_opendata_schema_changed` when required columns are missing and
  returns the last cached copy.
- *App Store RSS deprecation.* If the RSS endpoint returns 404, fall back to
  the lookup API only and log once per day.

### WP6 — Prospecting and outreach

**Goal.** Prospects are discovered, scored, deduplicated and sequenced;
first touches are cold-outreach holds (later no-hold per type); replies
route to `provider-success`; suppression and compliance are enforced in
code; the pipeline stays above target.

**Prerequisites (owner tasks before enabling, listed in the deployment doc).**
DNS for `partners.siutindei.com` (SES DKIM CNAMEs, MAIL FROM MX+TXT, DMARC
TXT `v=DMARC1; p=quarantine; rua=mailto:dmarc@siutindei.com`); a Google
Cloud project with Places API (New) enabled, billing, a key restricted to
Places API, stored in the secret; SES production access (verify the
account is out of the sandbox — it already sends invoices, so likely yes).

**Backend.**

- `board_places.py` (new): `text_search(query, *, region="hk", limit=20)`
  and `details(place_id)` against Places API (New) with the field mask
  `id,displayName,formattedAddress,websiteUri,nationalPhoneNumber,rating,
  userRatingCount,regularOpeningHours,businessStatus,types`; cost tracking
  in `external_usage_day` field `places` and a monthly counter
  `cache` `places:month:{yyyy-mm}` with `placesMonthlyCapUsd` (USD 0.032 per
  text search, 0.017 per details — **verify current prices** and put them
  in constants); refuse with a structured error when over cap. Cache
  results 30 days keyed by query (Google allows caching most fields up to
  30 days; place ids indefinitely — store `placeId` on the prospect,
  refresh other fields after 30 days).
- `board_prospects.py` (new): `dedupe_key(website, phone, place_id) ->
  str` (prefer registrable domain, else E.164 phone, else place id);
  `upsert(table, *, name, type, district, source, website, phone, email,
  place_id, raw) -> (prospect, created)`; `score(table, settings,
  prospect) -> (score, note)` via one `desk` call with the rubric, the
  prospect's public data and the homepage digest (`board_crawl.fetch`
  once); `qualify(...)` sets `qualified` when `score >= 60` and the type is
  in `typesEnabled`, `parked` when the type is not enabled, else
  `discovered`; `find_contact(prospect)`: only addresses found on the
  prospect's site (contact page, footer, `mailto:`) or in Places data,
  filtered to business local parts (`info`, `hello`, `enquiry`, `enquiries`,
  `contact`, `booking`, `bookings`, `admin`, `office`, `partnerships`,
  `marketing`, `hi`, `team`) unless `personalAddressesAllowed`; if none →
  stage stays `qualified` with `contact=null` and appears in the review
  page's "needs a contact" list for the owner (max 20/day).
- `board_sequences.py` (new): sequence templates per type
  (`sequence#{type}`) with `steps[]` of `{dayOffset, subjectEn, subjectZh,
  bodyEn, bodyZh}`; ship defaults written by the developer following this
  structure — who we are (two sentences), why we wrote to *them*
  (placeholder `{fitNote}`), what we offer (free listing at launch; no
  prices), one clear ask (reply or a link to the provider sign-up page
  `{signupUrl}`), signature, and the mandatory footer:
  `You are receiving this because {name} is publicly listed as a children's
  activity provider in Hong Kong. Reply "unsubscribe" or use {unsubscribeUrl}
  and we will not write again.` `start(table, prospect)` sets
  `contacted`, `nextTouchAt = now`; `due(table, now) -> list[prospect]`
  (gsi1 on `prospects#contacted` by `nextTouchAt`); `touch(prospect)`
  builds the mail through a new write op `outreach_send(prospectId,
  stepIndex, personalisation)` on tool `outreach` (below); after the last
  step → `unresponsive`.
- `outreach` tool (maxLevel `act`; defaults `coo: act`, `cmo: propose`,
  `ceo: read`, others `off`): ops `outreach_search_places(query, district)`,
  `outreach_open_data(kind, district)`, `outreach_list_prospects(stage,
  type, limit)`, `outreach_get_prospect(id)`, `outreach_upsert_prospect(...)`
  (write, class `internal`), `outreach_score_prospect(id)` (read; costs a
  model call), `outreach_start_sequence(id)` (write, internal),
  `outreach_send(prospectId, stepIndex, personalisation)` (write; class
  `cold_outreach:{type}` for step 0, `outbound_known` for later steps of a
  prospect that replied — which never happens since replies stop the
  sequence — so steps 1–2 are also `cold_outreach:{type}`),
  `outreach_suppress(id, reason)` (write, internal).
- `outreach_send` execution (`board_outreach.py`, new):
  1. Refuse when `breaker outreach` tripped, quiet hours (→ hold shift),
     `outreachday#{today}.sent >= boundaries.outreach.dailyCap`, prospect
     stage not `qualified`/`contacted`, type not enabled, no contact,
     `suppress#{digest(email)}` or `suppress#{digest(domain)}` exists,
     touches ≥ `outreachMaxTouches`.
  2. Render template in the prospect's language (zh-HK when the name is
     Chinese-only, else EN; both if unsure — EN first then ZH below);
     inject `personalisation` (≤ 400 chars, produced by the prospector from
     the fit note); build `unsubscribeUrl` = `{PUBLIC_API_BASE_URL}/public/
     outreach/unsubscribe/{token}` where token = base64url(prospectId +
     "." + HMAC-SHA256(secret, prospectId)[:16]).
  3. Send via SES v2 `SendEmail` with `FromEmailAddress =
     partnerships@{OUTREACH_SENDING_DOMAIN}`, `ConfigurationSetName =
     lxsoftware-admin-siutindei-outreach`, headers `List-Unsubscribe:
     <{unsubscribeUrl}>, <mailto:unsubscribe@{domain}?subject={token}>` and
     `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, `Reply-To:
     partnerships@siutindei.com` (a real mailbox on the main domain so
     replies flow into the existing ingest and triage). Record the
     outbound copy through `board_mail.ingest_bytes(direction="outbound")`
     so the thread exists for the reply.
  4. Update prospect (`touches.append`, `nextTouchAt` = next step day at
     10:00 HKT, or `unresponsive` after the last), `outreachday#.sent += 1`.
- **Public routes** (no JWT, like the Meta webhook): `GET /public/outreach/
  unsubscribe/{token}` → validates HMAC, writes `suppress#` for the address
  and stage `suppressed`, returns a plain HTML page "You will not hear from
  us again"; `POST` same path (RFC 8058 one-click) → same effect, 200 empty.
  Rate-limit by IP using a `cache` counter (100/hour) to blunt enumeration;
  tokens are unguessable anyway.
- Bounces and complaints: CDK creates SES configuration set
  `lxsoftware-admin-siutindei-outreach` with an event destination for
  `BOUNCE`, `COMPLAINT`, `REJECT` to an SNS topic → SQS queue
  `lxsoftware-admin-siutindei-outreach-events` → `adminFn` **event source
  mapping** (IAM role, no resource-policy statement). `dispatch.
  lambda_handler` branches on `Records[0].eventSource == "aws:sqs"` →
  `board_outreach.handle_ses_events(records)`: hard bounce or complaint →
  `suppress#` + prospect `suppressed` + `outreachday#.bounces/complaints`.
  `board_breakers.evaluate` trips `outreach` when the trailing 7-day
  bounce rate > 5 % or complaint rate > 0.1 % over ≥ 50 sends.
- Replies: triage (WP3) recognises the sender domain via `prospectkey#`
  and the `Reply-To` mailbox → prospect stage `replied`, task for
  `provider-success` with the prospect attached; the word "unsubscribe" in
  a reply (EN or 取消/不要再/退訂) → `suppress` and stage `suppressed`, no
  task.
- Targets: `board_targets.py` (new) `check(table, settings)` daily 08:00
  HKT: qualified this ISO week (Mon–Sun HKT) vs `targets.qualifiedPerWeek`
  prorated by day; shortfall → task for `prospector` with brief "Find and
  qualify {n} prospects of types {typesEnabled} in districts {districtsFirst}
  using gaps {intel:gaps}; use open data first, Places second, search
  third", `deliverableType="prospects"` (the deliverable is the list of
  `outreach_upsert_prospect` results). Contacted prospects due today →
  one `prospector` task "Send due touches" with the list; the task calls
  `outreach_send` per prospect (each becomes a hold or a send). Cap
  raising: on the target check, if `capRaisedAt` is older than 7 days and
  the 7-day complaint rate < 0.1 % and bounce rate < 5 %, `dailyCap += 20`
  up to `outreachDailyCapMax`.
- Seat `prospector` `isActiveDefault: true` from WP6.

**Routes.**

| Method | Path | Purpose |
|---|---|---|
| GET | `/siu-tin-dei/board/prospects?stage=&type=&district=&limit=` | pipeline list |
| GET | `/siu-tin-dei/board/prospects/{id}` | detail with touches and thread link |
| PUT | `/siu-tin-dei/board/prospects/{id}` | owner edits: `stage` (only to `suppressed`, `declined`, `qualified`, `parked`), `contact`, `type`, `note`; audit `BOARD_PROSPECT_PUT` |
| POST | `/siu-tin-dei/board/prospects/import` | CSV `name,type,district,website,email` (≤ 500 rows) → upsert as `source="owner"` |
| GET/PUT | `/siu-tin-dei/board/sequences/{type}` | templates |
| GET | `/siu-tin-dei/board/outreach/stats?days=28` | sends, bounces, complaints, replies, cap history |
| public GET/POST | `/public/outreach/unsubscribe/{token}` | see above |

**CDK.** Parameters and secret from §3.4; `ses.EmailIdentity` for the
sending subdomain with `mailFromDomain`; `ses.ConfigurationSet` + event
destination; SNS topic; SQS queue (visibility 60 s, DLQ after 5 receives);
`adminFn.addEventSource(new SqsEventSource(queue, {batchSize: 10}))`;
`ses:SendEmail` on the new identity ARN; schedule `…-board-targets`
(08:00 HKT). Add the two public routes without an authorizer, following
the Meta webhook route block.

**SPA.** `BoardPipelineSection.tsx`: funnel bar (counts per stage this
week vs target), table with filters (stage, type, district, score),
prospect drawer (public data, fit note, touches with previews, thread
link, actions: Suppress / Mark declined / Park / Edit contact), "Needs a
contact" list, CSV import, sequences editor (per type, per step, EN/ZH),
outreach stats card (sends/day, bounce and complaint rates, cap, breaker
state). Section `pipeline`.

**Tests.** `test_board_prospects.py`: dedupe keys (www./trailing slash/
phone formats), scoring fake, qualification by type, business-address
filter; `test_board_outreach.py`: every refusal reason, template rendering
in both languages, unsubscribe token round trip and tamper rejection,
SES send fake asserting headers, outbound copy indexed, SQS bounce →
suppression, breaker trip thresholds, cap raise logic, reply →
`replied` + task, "unsubscribe" reply → suppressed; `test_board_places.py`
cap and cache; routes.

**Acceptance.** With a fake Places response and a fake SES, a target
shortfall creates a prospector task that upserts ≥ 10 prospects, of which
those with `score ≥ 60` and a business address are `qualified`; the next
tick's "Send due touches" task produces `cold_outreach:venue` holds; after
promotion of that class, the same task sends immediately and the
`outreachday#` counter increments; a GET on the unsubscribe URL suppresses
the prospect and the following touch is refused with `suppressed`.

**Potential issues.**

- *SES identity verification takes time and DNS is owner-side.* Ship the
  code with the identity pending; `outreach_send` returns a structured
  error "sending identity not verified" until `GetEmailIdentity.
  VerifiedForSendingStatus` is true (cache the check 1 h).
- *Warm-up.* A brand-new subdomain sending 100/day immediately will be
  filtered. The cap ramp (20 → 100 over 4 weeks) is the warm-up; do not
  allow the owner to set a cap above `outreachDailyCapMax`.
- *Reply-To on a different domain than From.* Fine for deliverability;
  DMARC alignment is evaluated on From. Keep `Reply-To` on the main domain
  so replies enter the existing pipeline.
- *Places field mask errors.* Places API (New) rejects unknown fields with
  400; keep the field mask in one constant and test it against a recorded
  response.
- *Chinese-only names and addresses.* District mapping needs both scripts;
  `HK_DISTRICTS` must include 沙田, 大埔, 觀塘, 荃灣, 將軍澳, 元朗 … with
  EN equivalents. Unmapped → `district="unknown"` (still allowed).
- *Duplicate businesses across sources.* FEHD and Places name the same
  place differently; dedupe by domain/phone, and show possible duplicates
  (same normalised name + district) in the drawer for the owner to merge
  (`POST /prospects/{id}/merge {into}` — include it).
- *Prospect contact data in prompts.* Pass prospects to the model with
  emails and phones masked by `Pseudonymizer`; `outreach_send` unmasks on
  execution, like mail today.
- *A reply arrives while a follow-up hold is scheduled.* `outreach_send`
  re-checks the stage at execution; `replied` → refuse "prospect replied".
- *Restaurants.* `typesEnabled` excludes them; they still get discovered
  from FEHD and scored so the owner sees the size of the opportunity.

### WP7 — Marketing front line

**Goal.** A content calendar fills itself; creatives are rendered; posts
go out through `publish:{channel}` holds; assisted packs are produced for
channels without an API; performance feeds back weekly.

**Backend.**

- `board_creative.py` (new): `render_card(template, fields, *, lang) ->
  bytes (PNG 1080×1080)` and `render_story(...)` (1080×1920) with Pillow;
  templates `spotlight`, `guide`, `seasonal`, `quote`, `news`; fonts
  `NotoSans-Regular/Bold.ttf`, `NotoSansTC-Regular/Bold.otf` vendored under
  `backend/lambda/admin/fonts/` (OFL licence file included); brand tokens
  in `backend/lambda/admin/brand/brand.json` (`primary`, `accent`, `text`,
  `background`, `logoPath`) with a placeholder logo PNG. Text wrapping
  uses `ImageFont.getbbox`; CJK wraps per character; Latin per word; cap 6
  lines; overflow → smaller font down to 28 px, then truncate with "…".
  Output stored `board/siuTinDei/content/{contentId}/{n}.png`;
  `presigned_url(key, 3600)` for Meta.
- `board_content.py` (new): calendar CRUD; `plan_week(table, settings)`
  (Sunday 18:00 HKT duty for `content-marketer`, `senior` model): brief
  includes pillars, per-week counts, windows, last week's per-item
  performance, upcoming EDB holidays, `product_catalog_health` highlights,
  the latest market brief; deliverable `json` with `items[]` of `{slotAt,
  channel, pillar, copyEn, copyZh, hashtags[], template, fields{}, linkPath}`;
  `on_plan_delivered` upserts `content#` rows at `drafted` and enqueues a
  `creative` step per item (`render_card`; status `creative` →
  `scheduled`). At `scheduled`, `content_publish(contentId)` is called
  through `execute_call` as the CMO with class `publish:{channel}`, so it
  becomes a hold with `executeAt = slotAt` (override: `create_hold` accepts
  an explicit `execute_at`). Copy per channel: FB gets EN + ZH in one
  post separated by a line; IG gets EN, ZH, then hashtags (≤ 20); story
  gets the card plus a link sticker is **not** available via API — stories
  are image-only.
- `content_publish` op (write, tool `content`, maxLevel `act`, defaults
  `cmo: act`, `ceo: read`, others `off`): on execute, for `facebook` →
  Graph `POST /{pageId}/photos` with `url` (presigned) and `message`; for
  `instagram` → the existing container + `media_publish` flow in
  `board_meta` (`image_url` presigned, `caption`); for `instagram_story` →
  container with `media_type=STORIES`. Respect `igPublishesPerDay` via
  `external_usage_day` field `ig_publish`. Store `platformPostId`; status
  `published`; `utm` = `utm_source={channel}&utm_medium=social&utm_campaign=
  {pillar}-{yyyyww}&utm_content={contentId}` appended to `linkPath`.
- Assisted channels: items with `channel in assistedChannels` skip
  publish; at `slotAt` they appear in `review.assisted` with copy (ZH
  first for Xiaohongshu), the card, and a "Mark posted" button →
  `published` with `platformPostId="manual"`.
- `weekly_readout(table, settings)` (Monday 09:00 HKT duty for
  `growth-specialist`): pulls `meta_page_insights`, `meta_ig_insights`,
  post-level metrics for last week's `platformPostId`s (Graph
  `/{id}/insights` for IG, `/{id}?fields=insights.metric(post_impressions,
  post_clicks)` for FB), `web_sessions` filtered by `utm_campaign`; writes
  `performance` on each content row and a Markdown deliverable; the brief
  asks for "repeat / adapt / retire" per pillar and channel, which
  `plan_week` reads next Sunday. Boosting: the readout may call
  `meta_boost_post` for the best post (existing caps and `spend:meta`
  hold).
- Seats `content-marketer`, `growth-specialist`, `community-manager`
  active from WP7 (the latter already from WP3).

**Routes.**

| Method | Path | Purpose |
|---|---|---|
| GET | `/siu-tin-dei/board/content?from=&to=&status=` | calendar |
| POST | `/siu-tin-dei/board/content` | owner adds an item (same shape as plan items) |
| PUT | `/siu-tin-dei/board/content/{id}` | edit copy/slot; `status` only to `vetoed` or `published` (manual) |
| POST | `/siu-tin-dei/board/content/{id}/render` | re-render creative |
| GET | `/siu-tin-dei/board/content/{id}/creative/{n}` | presigned URL |

**CDK.** Schedules `…-board-content-plan` (Sunday 18:00 HKT) and
`…-board-content-readout` (Monday 09:00 HKT). Packaging: add a pinned
`Pillow` line to `backend/lambda/admin/requirements.txt` (today it holds
only a comment). `createPythonLambda` (`lib/constructs/python-lambda.ts`)
then switches from local copy to **Docker bundling** with pip inside the
Python 3.12 `arm64` image, so the `aarch64` manylinux wheel is used and no
compilation happens. Verify Docker is available in the deploy workflow
runner (GitHub-hosted Ubuntu runners have it) and that the first
`cdk synth` after this change succeeds in CI, since this is the first
third-party Python dependency in `AdminApiFn`. Bundle grows by ~25 MB
(Pillow plus two font families); well under the 250 MB unzipped limit.

**SPA.** `BoardContentSection.tsx`: two-week calendar grid (days ×
channels), item drawer (copy EN/ZH editable, creative preview, slot, hold
link, performance), assisted packs list with copy buttons and "Mark
posted", readout link. Section `content`.

**Tests.** `test_board_creative.py`: renders every template in both
languages without exception, output dimensions, wrapping of a 200-char
Chinese string; `test_board_content.py`: plan JSON → rows, hold with
`executeAt=slotAt`, publish fakes for FB/IG/story, IG daily cap, assisted
routing, readout writes performance and calls boost within caps.

**Acceptance.** `plan_week` produces 21 items for the week; each has a
PNG; at the slot time the tick publishes to the fake Graph and the
calendar shows `published`; vetoing one from the review page leaves it
`vetoed` with a lesson draft.

**Potential issues.**

- *Instagram requires a publicly fetchable image URL.* Presigned S3 URLs
  work (Meta fetches at container creation); expiry 1 h is enough. If the
  bucket enforces `aws:SecureTransport` only, presigned HTTPS is fine.
- *Aspect ratios.* IG feed accepts 1:1; stories 9:16. Do not reuse the
  square card for stories.
- *Pillow in Lambda.* Import errors mean a wrong wheel platform; the
  packaging note above is the fix, not a code change.
- *CJK line breaking and punctuation.* Break per character; avoid starting
  a line with `，。！？」）` by pulling the punctuation up.
- *Meta App Review.* `pages_manage_posts` and `instagram_content_publish`
  must be approved for the app (tools plan §5.3); until then publishing
  works only for the owner's own accounts as app admin — which is our
  case.
- *Link in IG captions is not clickable.* Use "link in bio" wording and
  keep UTM links for FB and the newsletter; measure IG via profile clicks.
- *Duplicate posts after a failed publish.* Store `platformPostId` before
  marking published; on Graph timeout, query the page feed for a post with
  the same caption hash within 10 min before retrying.

### WP8 — Newsletter

**Goal.** Parents and providers can opt in on the public site; fortnightly
issues are drafted, held, sent, measured; unsubscribe is one click.

**Backend.** `board_newsletter.py` (new): lists `parents`, `providers`;
public routes `POST /public/newsletter/subscribe {list, email, lang}`
(rate-limited, sends a confirm email with a signed token from
`news@siutindei.com`), `GET /public/newsletter/confirm/{token}`, `GET|POST
/public/newsletter/unsubscribe/{token}`; subscriber rows with
`confirmedAt`, `lang`, `source`; `newsletter_draft_issue` op (write,
internal) for `content-marketer` producing Markdown + HTML (simple
template, inline CSS) from the last fortnight's content and catalog
highlights; `newsletter_send(issueId, list)` op (class
`publish:newsletter`), sending in batches of 50 via SES `SendBulkEmail`
with per-recipient unsubscribe links, from `news@siutindei.com`, a
configuration set `…-newsletter` sharing the SQS bounce path (WP6);
metrics from SES open/click events (add `OPEN`, `CLICK` to the event
destination) written to the issue row.

**Public site.** `apps/public_www`: a `NewsletterForm` component posting
to the public route (the API base URL is already configured for the
public site's other calls — verify; otherwise add `VITE_PUBLIC_API_URL`).

**Tests.** Token round trips, double opt-in required before any send,
batch sending fake, unsubscribe honoured, bounce suppression shared.

**Potential issues.** Double opt-in is not legally required in HK but
prevents list poisoning; keep it. PDPO: the confirm email states the
purpose and the unsubscribe path. SES bulk templates must be created
(`CreateEmailTemplate`) — do it at deploy time in a small CDK custom
resource or lazily in code on first send.

### WP9 — Remaining desk seats, duties, GitHub/AWS/receivables triage

**Goal.** `accountant`, `data-analyst`, `security-analyst` active; duties
run on Scheduler; CI, alarms and overdue invoices create tasks; the
stand-up proposes boundary changes.

**Backend.** `duties[]` per seat in the contract: `{id, cron (HKT),
brief, deliverableType, tier}`; `board_duties.py` `run_due(table,
settings, now)` called from the tick (compare the cron against the last
run stored in `cache` `duty:{seatId}:{dutyId}`), gated by
`settings.staff.dutiesEnabled`. Duties: `business-analyst` weekly KPI pack
(Mon 08:00), `accountant` month-end memo (1st 09:00) and weekly aging
(Thu 09:00), `security-analyst` weekly triage (Tue 09:00), `data-analyst`
weekly attribution (Mon 10:00). Triage additions in `board_cache.
refresh_all`: after `aws` and `security` refresh, diff alarms in ALARM and
new alert ids against `cache` `seen:*` and create tasks for `architect`
(if active, else CTO) and `security-analyst`; `board_receivables.
handle_dunning_trigger` creates an `accountant` task instead of proposing
reminders directly when staff is enabled. Stand-up: `board_meeting`
synthesis prompt gains an optional `boundarySuggestions[]` (`{classKey,
change, evidence}`) validated against ramp state; persisted into
`review.suggestions`.

**Tests.** Cron matching across HKT/UTC and DST-free arithmetic, duty
idempotency, alarm diff, dunning hand-off.

**Potential issues.** Cron evaluation in a 5-minute tick must tolerate a
missed tick (treat "due if the last run is before the most recent
scheduled time"). Month-end in HKT, not UTC.

### WP10 — Engineering runner and staging autonomy

**Goal.** Engineering seats write specs and issues, dispatch the runner to
open draft PRs on `board/*`, review them, and merge to `staging` under
policy; the owner promotes to `main` from the review page. SEO articles
use the same path.

**This repo.**

- `board_code.py` (new) and tool `code` (maxLevel `act`, defaults `cto:
  act`, `cpo: propose`, others `off`; seats `engineer-*`, `product-dev`,
  `content-marketer` (SEO only) via their manager): ops
  `code_run_task(issueNumber, brief, kind="feature"|"fix"|"content")`
  (write; class `internal` because it only opens a draft PR; dispatches
  `board-agent.yml` with inputs `task_id`, `issue`, `brief`, `kind`),
  `code_get_run(taskId)` (read; polls Actions runs by `task_id` in the run
  name and the PR by branch `board/{taskId}`), `code_review_pr(prNumber)`
  (read; returns diff stats, changed paths, CI status, and the diff text
  capped at 30 000 chars for the architect's review), `code_merge_staging
  (prNumber)` (write; class `code_staging`; `act_guard` refuses unless: CI
  success, `architect` review task delivered with `verdict=accept` for
  this PR, `changedLines <= 400`, no path matches `PROTECTED_PATHS`
  (`**/auth/**`, `**/payments/**`, `**/migrations/**`, `infra/**`, `.github/**`),
  base is `staging`; on execute dispatches `board-merge-staging.yml`),
  `code_promote(kind="production")` (write; `always_propose=True` — an
  Approval whose approve action dispatches `board-promote.yml`; shown as
  the "Promote" button on the review page with the staging diff summary).
  The board GitHub token needs `actions: write` (deployment doc).
- Engineering flow as tasks: architect duty "groom backlog" (weekly) →
  issues with acceptance criteria labelled `board-ready`; `engineer-*`
  target check: if fewer than 2 open `board/*` PRs, take the oldest
  `board-ready` issue → `code_run_task`; when a run finishes, a task for
  `architect` "review PR #n" → `code_review_pr`, deliverable `markdown` with
  a final JSON `{"verdict":"accept"|"changes","notes":[…]}`; `changes` →
  `code_run_task` again with the notes (max 2 rounds), `accept` → the
  engineer calls `code_merge_staging`.
- SEO articles (WP7 hand-off): `content-marketer` produces Markdown; a
  `code_run_task(kind="content")` places it under the site's content path;
  path rule `content/**` only → `changedLines` limit 2 000 for `content`
  kind.

**siutindei repo (appendix A — hand this to whoever owns that repo).**

1. Branch `staging` created from `main`, protected: no force push; allow
   merges by the Actions bot; require status checks. `main` protected:
   PRs only, owner approval.
2. Workflow `.github/workflows/board-agent.yml`: `on: workflow_dispatch`
   with inputs `task_id`, `issue`, `brief`, `kind`; `permissions: contents:
   write, pull-requests: write`; steps: checkout `staging`; create branch
   `board/${{ inputs.task_id }}`; install Cursor CLI; run
   `cursor-agent -p "$(cat brief.txt)" --model <fixed model> --yolo` with
   `CURSOR_API_KEY` from repo secrets and a repo-level `AGENTS.md` that
   states the acceptance criteria discipline and forbids touching
   protected paths; run the repo's tests; commit; `gh pr create --draft
   --base staging --title "board: #<issue> <first line of brief>" --body
   "<brief>\n\nTask: <task_id>"`. Job name includes `task_id`.
3. Workflow `board-merge-staging.yml`: `workflow_dispatch` input
   `pr_number`; verifies again (CI green, base `staging`, branch prefix
   `board/`, no protected paths, size) and `gh pr merge --squash`.
4. Workflow `board-promote.yml`: `workflow_dispatch`; opens (or updates) a
   PR `staging → main` titled "Promote staging YYYY-MM-DD"; the **owner
   merges it in GitHub** (the board never merges to `main`).
5. Deploy workflow: on push to `staging` deploy to a staging stack/URL
   and run a smoke test; on push to `main` deploy production (existing).

**Tests (this repo).** `test_board_code.py`: guard matrix for
`code_merge_staging`, dispatch payloads, run polling fake, review JSON
parsing, promote is always an approval.

**Acceptance.** A `board-ready` issue in a test repo results in a draft PR
on `board/<taskId>`, an architect review task, and (after accept and CI)
a `code_staging` hold that merges on execution; the review page shows a
Promote button listing the staging commits.

**Potential issues.**

- *Runner cost and runaway agents.* Cap the workflow with
  `timeout-minutes: 30`; the CLI run gets a token/turn budget flag if the
  CLI supports one at build time (verify); otherwise rely on the timeout.
- *Secrets in the runner.* Only `CURSOR_API_KEY` and `GITHUB_TOKEN`; no AWS
  credentials in `board-agent.yml`.
- *Protected paths bypass via renames.* Evaluate both old and new paths
  from the PR files API.
- *Two engineers on one issue.* `code_run_task` refuses when an open
  `board/*` PR references the same issue number.
- *Staging drift.* `board-promote.yml` refuses when `staging` is behind
  `main`; the architect gets a task "rebase staging" (manual, `needs_owner`
  in v1).

## 5. Cross-cutting issues (read before WP1)

- **Lambda limits.** 300 s timeout, 1024 MB memory today. Every
  long-running path in this plan is chunked (steps, crawl cursor, batch
  sends). If a WP needs more memory (Pillow rendering of 21 cards in one
  tick), raise `memorySize` for `AdminApiFn` to 1536 in that WP's PR and
  say so in the PR description.
- **Concurrency.** The tick, meetings, chat and ingest can run at once.
  Every multi-writer document uses conditional updates (`claim_*`), and
  `settings` writes use a version attribute (add in WP2 if missing).
- **DynamoDB gsi1 partition shape.** `tasks#{status}` and
  `holds#{status}` partitions stay small (hundreds); `prospects#{stage}`
  can reach tens of thousands — acceptable for on-demand capacity; list
  routes must paginate with `Limit` and `ExclusiveStartKey` (add `cursor`
  query params on the prospect list route).
- **Costs to watch.** OpenRouter (two budgets), Places, SES, Actions
  minutes, Cursor CLI usage. Every external call increments an
  `external_usage_day` field; the Settings card already renders that map —
  extend the labels.
- **Secrets.** All new secrets are CDK-created with dummy values, replaced
  in the console, named `lxsoftware-admin-siutindei-board-*`. Never read
  them at import time; read lazily and cache like `board_research._brave_key`.
- **Time zones.** Store UTC; compute HKT with a fixed `+08:00` (no DST);
  put the helper in `board_hk.py` and use it everywhere.
- **PII.** Prospect contacts are business data but still masked in
  prompts; parent data follows the existing masking; the review page and
  drawers show real values to the owner only.
- **Kill switches, in order of reach.** `settings.staff.enabled` (UI),
  `BoardStaffEnabled` (deploy), `BoardToolsEnabled` (all tools),
  `BoardMailSendingEnabled` (all email). Document this ladder in
  `admin-website.md`.
- **Playwright and mocks.** Every new section must render from fixtures in
  `dev:mock`; the viewport smoke test must include `staff`, `review`,
  `pipeline`, `market`, `content`.

## 6. Rollout runbook (owner steps interleaved)

1. Deploy WP1 with `BoardStaffEnabled=false`. Owner: nothing.
2. Deploy WP2–WP4. Owner: set `review.digestTo`, read one digest, set
   `BoardStaffEnabled=true` and `settings.staff.enabled=true`; all holds
   at defaults; `maxRunningTasks=3`. Seats already on: `support`,
   `provider-success`, `community-manager`, `business-analyst`.
3. Deploy WP5. Owner: activate `market-analyst`; add five watchlist
   entries; read the first weekly brief.
4. Owner: DNS records for `partners.siutindei.com`; Google Cloud key into
   the secret; create mailboxes `partnerships@siutindei.com`,
   `market@siutindei.com`, `news@siutindei.com`, `dmarc@siutindei.com` on
   Cloudflare (they fan out to the board automatically). Deploy WP6.
   Activate `prospector`. Verify identity status in the Pipeline section;
   approve the default sequences; first sends are 24 h holds.
5. Deploy WP7. Owner: activate `content-marketer` and `growth-specialist`;
   drop logo and colours into `brand/`; confirm Meta app permissions;
   first posts are 24 h holds; raise `maxRunningTasks` to 6.
6. Deploy WP8, WP9. Owner: set `PublicSiteOrigins`; activate `accountant`,
   `data-analyst`, `security-analyst`; then enable duties.
7. siutindei repo: appendix A. Then deploy WP10. Owner: activate
   `architect`, `engineer-1`, `engineer-2`, `product-dev`; token scope
   `actions: write`. Keep `code_merge_staging` as `always_propose` until
   those workflows exist; then first merges to staging are 12 h holds.
8. After two weeks: act on ramp promotions from the review page.

## 7. Definition of done (every WP)

- Tests listed in the WP pass locally and in CI; no network in tests.
- `npm run build` in `apps/admin_web` and `backend/infrastructure` pass;
  `check-contracts.py` passes.
- `dev:mock` shows the new section with fixtures; Playwright smoke updated.
- `docs/deployment/admin-website.md` has the setup steps and the kill
  switches; `AGENTS.md` has one gotcha line; `UI_COMPONENTS.md` lists new
  components.
- The feature is inert with `BoardStaffEnabled=false`.
- PR description lists every new route, schedule, secret, parameter and
  IAM grant.
