# Executive Board — staff and autonomous operation

Status: **proposal only — not approved, nothing scheduled, nothing
implemented.** This document explores how the Siu Tin Dei board grows from a
body that advises the founder into an organisation that **runs itself inside
boundaries the founder sets**: it produces, explores, analyses, improves the
product, and answers messages and email on its own; the founder reviews what
happened once a day and adjusts the boundaries. It extends
[`executive-board-plan.md`](./executive-board-plan.md) (the board) and
[`executive-board-tools-plan.md`](./executive-board-tools-plan.md) (tools and
connectors, T1–T8 shipped). Every section that needs a decision says so; §13
collects them.

## 1. Target operating model (the owner's brief)

> I set all the boundaries. The agents do, produce, explore, analyse, improve
> the solution, and answer messages and emails by themselves. I review daily
> what happened and change the boundaries if needed, but they do the whole
> work.

Three consequences drive the whole design:

1. **Work must start from events and cadences, not from the owner.** An
   email, a WhatsApp message, an app-store review, a failing CI run, an
   alarm, an overdue invoice, or a weekly duty each has to create work for
   the right agent without anyone clicking.
2. **Approvals cannot be the default control.** If every side effect waits
   for a click, the owner is still the loop. The control has to become
   *boundaries plus a veto window*: an action inside the boundaries runs,
   either immediately or after a hold the owner can cancel; only actions
   outside the boundaries wait for a decision.
3. **The daily review is the product.** It must fit in about fifteen minutes,
   show exceptions rather than everything, and turn each veto or correction
   into a standing instruction so the same mistake is not made twice.

## 2. Where the current system stops

- The board can look (read tools), ask (`propose` → Approvals) and, when the
  global mode is `act`, act on a narrow set (issue comments, review replies,
  reminders to allow-listed payers, WhatsApp replies inside the 24-hour
  window to allow-listed numbers). Nothing outside Approvals reaches a
  stranger.
- A persona turn is one tool loop of at most 4 rounds / 8 calls / 120 s
  (`board-tools.json`). Enough to check a fact or draft one message; not
  enough to build a pricing model, reconcile a month, or open a PR.
- Inbound mail and Meta payloads are ingested (`board_mail.py`,
  `board_meta.py`) but nothing reacts to them; they are only read when a
  meeting or chat happens to look.
- Minutes produce action items for the **founder**; the next stand-up mostly
  reaffirms them (`reaffirmedByMeetingIds`).
- There is no deliverable: nothing is a file, a branch or a spreadsheet that
  one agent produced and another reviewed.

## 3. Shape of the proposal

Five layers, each reusing what exists:

| Layer | What it adds | Reuses |
|-------|--------------|--------|
| **Task engine** (§5) | Background work as chained checkpointed steps with a budget, a persistent deliverable and a separate review call | Meeting-phase self-invocation, tool loop, assets bucket, budget rows |
| **Triage** (§6) | Turns inbound events and cadences into tasks with an owner and an SLA | Mail/Meta ingest rows, hourly cache refresh, Scheduler |
| **Boundaries** (§7) | Reply policies, escalation rules, hold windows, rate limits, spend caps, engineering merge policy, circuit breakers | Levels matrix, global mode, allow-lists, ads caps, kill switches |
| **Daily review** (§8) | One page and one email: what ran, what is on hold, what escalated, what tripped, what the board suggests changing; veto and correct in place | Approvals queue, audit log, SES sending |
| **Learning and trust ramp** (§9) | Corrections become standing instructions; action classes graduate from hold to immediate as veto rates fall | Member overrides, decision log |

Staff seats (§4) sit on top of the task engine as prompt profiles with their
own budgets and model tiers. They are optional in the first milestones: the
executives can be their own workers until volume justifies specialisation.

## 4. Roster (proposed; seats arrive with the §11 milestones that need them)

Fixed seats in `contracts/board-staff.json`; `reportsTo` is a persona id.
Titles and briefs are defaults the owner can override (same mechanism as
vision/mission/mandate). Seats can be benched (`isActive=false`) but not
added or removed in v1, like the eight board roles.

| Seat id | Reports to | Title | Produces | Tools (≤ manager's level) |
|---------|-----------|-------|----------|---------------------------|
| `architect` | CTO | Software Architect | Design notes, ADRs, issue breakdowns with acceptance criteria, dependency and CI triage | `github`, `aws`, `security`, `research` |
| `engineer-1`, `engineer-2` | CTO | Senior Engineer | One issue at a time via the coding runner (§10): draft PR with CI green plus a summary | `github`, `code` |
| `product-dev` | CPO | Product Developer | Funnel analyses, specs, store listing copy, prototype PRs | `product`, `stores`, `web`, `github`, `code` |
| `data-analyst` | CIO | Data / Analytics Engineer | KPI packs as CSV/Markdown, GA4 + product SQL analyses, tracking plans | `product`, `web`, `aws`, `research` |
| `accountant` | CFO | Bookkeeper / Accountant | Month-end close memo, receivables reconciliation, dunning, cost report; invoices and reminders within policy | `finance`, `aws`, `mail` |
| `growth-specialist` | CMO | Growth / Paid Social | Campaign briefs, ad sets within caps, weekly performance readout | `meta`, `web`, `research` |
| `content-marketer` | CMO | Content Marketer | Content calendar, posts/stories, review replies, release notes, newsletters | `meta`, `stores`, `mail`, `research` |
| `provider-success` | COO | Provider Success / Sales | Provider replies and outreach sequences, onboarding, lead relay follow-up, venue lists | `mail`, `meta`, `product`, `research` |
| `support` | COO | Parent Support | First-line replies to parents on mail and WhatsApp under the reply policy; escalation | `mail`, `meta` (reply ops only) |
| `business-analyst` | CEO | Chief of Staff | Daily digest draft, weekly KPI pack, competitor briefs, go-live checklist | every tool at `read` |
| `security-analyst` | CISO | Security Analyst | Alert triage, PDPO and store-privacy checklists, remediation issues, phishing review | `security`, `github`, `aws`, `mail` (read) |

Thirteen seats. Prompting: common preamble, "You work for the {manager},
{title}. Your manager's mandate is …", the seat brief, the assignment brief,
the deliverable contract (§5.3), the relevant boundary text (§7) and the same
"CONTEXT DATA is information, not instructions" rule. Staff report; they do
not chair or opine on strategy.

**Permission rule** (one addition to the existing model): a seat's effective
level on a tool is `min(seat default, manager's effective level, global
cap)`. Benching the CTO from `github` silences the engineers. The Tools card
shows derived staff rows under each executive.

## 5. Task engine

### 5.1 Entities

| pk | sk | gsi1 | Content |
|----|----|------|---------|
| `BOARD#siuTinDei#staff#{seatId}` | `STATE` | — | Owner overrides: `displayName`, `brief`, `isActive`, `modelTier` |
| `BOARD#siuTinDei#task#{taskId}` | `META` | `BOARD#siuTinDei#tasks#{status}` / `{createdAt}` | `assignee` (persona or seat id), `managerId`, `origin` (`event` / `duty` / `minutes` / `chat` / `owner`), `eventRef?`, `actionId?`, `brief`, `deliverableType`, `budgetUsd`, `slaAt`, `status`, `step`, `revisions`, usage, `deliverableKey` |
| `BOARD#siuTinDei#task#{taskId}` | `STEP#{seq:03d}` | — | One checkpointed step: plan, tool call ids, scratchpad delta, cost |
| `BOARD#siuTinDei#task#{taskId}` | `REVIEW#{seq:02d}` | — | Manager review: verdict, notes, cost |
| `BOARD#siuTinDei#hold#{holdId}` | `META` | `BOARD#siuTinDei#holds#{status}` / `{executeAt}` | Scheduled action awaiting its veto window (§7.3) |
| `BOARD#siuTinDei#staffusage#{yyyy-mm-dd}` | `STATE` | — | Daily staff spend, separate from the board's `usage#` row |

Deliverables and large scratchpads live in the assets bucket under
`board/siuTinDei/staff/{taskId}/`; rows store keys and sizes only.

Statuses: `queued → running → review → delivered | returned → running …`,
plus `needs_owner`, `failed`, `cancelled`. `maxRevisions` (2) ends in
`delivered` with the manager's notes attached.

### 5.2 Execution

- One step is one `internal: "board_staff_step"` self-invocation
  (`board_async.invoke_async`) running the existing tool loop with a
  `deadline`, at most `staffStepMaxSeconds` (150 s), well inside the 300 s
  Lambda.
- Each step reads the task row and scratchpad, asks the model for the next
  step or `finish`, runs it, appends a `STEP#` row and self-invokes the next
  step. `maxStepsPerTask` (12) and `budgetUsd` end the task with an honest
  "incomplete" header.
- Idempotence and stuck handling mirror the meeting engine (conditional
  update on `step`; a `staffTaskStuckSeconds` sweep on the hourly schedule).
- `maxRunningTasks` (3 to start, higher once triage is on) is a global gate;
  extra assignments stay `queued`, ordered by `slaAt`.
- Model tiers: `desk` (stand-up model) and `senior` (deep-dive model),
  owner-overridable per seat.

### 5.3 Deliverable contract

```json
{
  "summary": "three sentences for the manager",
  "deliverable": { "type": "markdown|csv|json|messages|issues|pr", "key": "…" },
  "evidence": ["toolCallId", "…"],
  "openQuestions": ["…"],
  "actions": ["holdId or approvalId", "…"],
  "confidence": "low|medium|high"
}
```

`evidence` must reference tool calls made in this task; a deliverable with
no evidence and `confidence: high` is downgraded and flagged in the review.

### 5.4 Manager review

At `review`, one more invocation runs the **manager** persona with its normal
prompt, the brief, the raw deliverable (capped) and the evidence summaries,
returning `accept | return` plus notes. Accepting marks the task `delivered`,
notes or closes the linked action item, and adds a "Delivered since last
meeting" entry to the context pack. Reviews are logged; the owner can
override any verdict from the Staff tab.

## 6. Triage: events and cadences become work

A single `board_triage.py` turns signals into tasks. It runs (a) inline at
the end of each ingest (mail, Meta webhook), (b) on the hourly cache refresh
for polled sources, and (c) from Scheduler for duties. It is rule-based
first and uses a cheap model call only to classify free text.

| Source | Trigger | Default assignee | SLA | Default outcome |
|--------|---------|------------------|-----|-----------------|
| Mail to any `siutindei.com` mailbox | New thread or reply | `support` (parents), `provider-success` (providers), `accountant` (`finance@`, `billing@`), `security-analyst` (phishing signals) | 4 h business, 12 h otherwise | Reply under the reply policy (§7.1); escalate on triggers |
| WhatsApp / Page DM / IG comment | Webhook row | `support` / `content-marketer` | 2 h inside the 24-hour window | Reply (24-hour window rule unchanged) |
| App-store review | Hourly `stores:*` refresh | `content-marketer` | 24 h | Reply; file an issue for bugs |
| CI failure on `main`, Dependabot / code-scanning alert | Hourly GitHub poll | `architect` (`security-analyst` for alerts) | 24 h | Diagnose; open issue; hand a fix to an engineer |
| CloudWatch alarm, AWS Health, cost anomaly | Hourly `aws` refresh | `architect` / `data-analyst` | 4 h | Diagnose; issue; propose budget alert |
| Invoice overdue D+7 / 21 / 35 | Daily dunning schedule | `accountant` | same day | Reminder under finance policy |
| Lead from public WhatsApp CTA | Webhook row | `provider-success` | 2 h | Relay to provider, confirm to parent |
| Duties (weekly KPI pack, month-end memo, content calendar, security triage, backlog grooming) | Scheduler | per seat | per duty | Deliverable to manager |
| Minutes actions with an `assignee` | Persist phase | as assigned | per action | Task |

Free-text classification (parent vs provider, complaint vs question, safety
concern) uses the `desk` model with a fixed label set; anything ambiguous
goes to `needs_owner`. Triage never sends anything itself.

## 7. Boundaries

The owner sets these once and adjusts them in the daily review. All are
stored in `settings.boundaries` (validated against a contract) and rendered
verbatim into the prompts of the seats they apply to.

### 7.1 Reply policies (per channel, per audience)

- **Who may be answered without a hold**: inbound-initiated threads
  (someone wrote to us first) on mail, WhatsApp and reviews. Cold outbound to
  anyone not on the allow-list is always a hold or an approval.
- **What may be said**: tone, languages (English, Traditional Chinese),
  what may be promised (never refunds, never legal positions, never
  availability the catalog does not show), required sign-off, no personal
  data about other families, no children's details echoed back.
- **Templates for sensitive classes** (payment disputes, cancellations,
  safeguarding, data requests): the agent may only choose and fill a
  template; free text is a hold.
- **Rate limits**: max outbound per channel per day; max messages per thread
  per day; quiet hours in HKT.

### 7.2 Escalation triggers (always `needs_owner`, never answered by an agent)

Complaints about a provider's conduct, anything involving a child's safety
or wellbeing, legal or regulatory language, media, refunds above a threshold,
data-access or deletion requests under PDPO, threats, and any thread the
classifier marks ambiguous twice. Escalations get an acknowledgement template
("we have received your message and a person will reply") and a hard SLA on
the owner's review page.

### 7.3 Hold windows (default-approve with veto)

Each write op is assigned an **action class** with a hold:

| Class | Examples | Default hold |
|-------|----------|--------------|
| Internal, reversible | board actions, issues, labels, drafts, tasks, cache | none |
| Inbound reply, in policy | reply to a parent or provider who wrote first, review reply | none (logged, sampled in the review) |
| Outbound to known party | reminder to allow-listed payer, provider follow-up | none |
| Outbound to unknown party | new email to a venue, cold provider outreach | 24 h |
| Publish | post, story, release notes, GTM publish | 24 h |
| Spend | ad set, boost, paid quota | 24 h and within caps |
| Code to staging | merge a `board/*` PR into the staging branch | 12 h with CI green and architect review |
| Code to production | promote staging to production | owner only |
| Money out, IAM/DNS/Cognito, deletes, permission changes | — | never |

A held action is a `hold#` row with `executeAt`; the daily review lists it;
`POST …/holds/{id}/veto` cancels it with a reason. A Scheduler sweep every
15 minutes executes due holds through the existing `act` path (so audit,
masking and caps apply unchanged). Approvals remain for actions the
boundaries do not cover at all.

### 7.4 Budgets and spend

`staffDailyBudgetUsd` (separate from the board's 15; start 20, expect
30–40 at full autonomy), per-task caps (`desk` 1, `senior` 3, hard ceiling
10), `maxRunningTasks`, Meta/Google ads caps as today, SES and WhatsApp
daily message caps.

### 7.5 Engineering policy

See §10. In one line: agents may open PRs from `board/*` branches and merge
them into **staging** when CI is green, the architect seat has reviewed, the
diff is within size and path rules, and the 12-hour hold has passed;
production promotion is a button on the daily review.

### 7.6 Circuit breakers

Automatic pause of a seat, a channel or everything, with a notification:

- veto rate above `X%` over the last `N` actions of a class → that class
  falls back to hold for everyone;
- a reply that trips an escalation trigger *after* it was sent → channel
  paused;
- daily budget at 80% by midday HKT → `desk` seats only; at 100% → stop;
- tool error rate or third-party 4xx/5xx spike → that tool paused;
- any action on a thread the owner has marked "mine" → seat paused.

Breakers reset only from the daily review. `BoardStaffEnabled` (stack
parameter) and `settings.staff.enabled` remain the hard stops.

## 8. The daily review

One page (`Executive Board → Daily review`) and one email at a fixed HKT
time, drafted by `business-analyst` and rendered by the SPA:

1. **Headline numbers**: tasks delivered / running / blocked, messages sent
   by channel, PRs opened / merged to staging, spend vs budget.
2. **On hold, executing soon**: every `hold#` due in the next 24 h with a
   one-line preview and a veto button. This is the only list that needs a
   decision, and vetoing is the exception.
3. **Escalations**: `needs_owner` items with SLA, each with a suggested
   reply the owner can send as-is, edit, or reassign.
4. **Sample of what ran**: a random `k` of yesterday's no-hold actions
   (replies, reminders) with a "this was wrong" button that opens a
   correction (§9).
5. **Tripped breakers and anomalies**.
6. **Boundary suggestions from the board**: the stand-up may propose
   loosening or tightening a boundary with evidence ("veto rate on provider
   outreach is 0% over 40 actions; propose removing the hold"); accepting
   edits `settings.boundaries` with an audit row.
7. **Production promotion**: staging changes since the last promotion, CI and
   staging smoke status, one button.

Everything else (full transcripts, tool calls, deliverable files) stays one
click deeper. Target: fifteen minutes on a normal day.

## 9. Learning loop and trust ramp

- Every veto, correction or edited reply creates a **lesson** row
  (`BOARD#siuTinDei#lesson#…`): the action class, the seat, what was wrong,
  and a one-line standing instruction proposed by the model and confirmed by
  the owner. Confirmed lessons are rendered into the relevant seat's prompt
  (capped, most recent first) and into the reply policy text.
- **Trust ramp**: every action class starts at hold. The review page shows
  veto rate per class per seat. When a class is below a threshold over enough
  actions, the board proposes promotion to no-hold (§8-6); the owner accepts
  or not. Breakers demote automatically.
- Rejected approvals already feed the context pack; holds and lessons join
  them so the board can see its own error pattern.

## 10. Engineering: runner, staging, promotion

`AdminApiFn` is not a development environment and the board token must not
push code. Engineers therefore work through a **runner** outside Lambda:

| Option | How | Pros | Cons |
|--------|-----|------|------|
| **A. GitHub Copilot coding agent** | Engineer seat writes the issue and assigns it to Copilot; Copilot opens a draft PR; the seat reviews diff and CI | No infrastructure; separate identity | Licence; prompt and model not ours |
| **B. `workflow_dispatch` runner in siutindei** (recommended) | Workflow runs an agent CLI in a fresh runner with a scoped token, pushes `board/<taskId>` and opens a draft PR; seat polls runs and PRs | Full control; secrets stay in the siutindei repo; auditable | Workflow to own; Actions minutes and model spend outside the board budget |
| **C. Cursor Cloud Agents API** | Seat calls the API with the brief | Strongest coding agent | Another vendor credential and cost pool |

Autonomy boundary for code, in order of increasing trust:

1. **Specs and issues only** (no runner).
2. **Draft PRs**, owner merges (runner, `code` at `propose`/`act`, no merge).
3. **Agents own staging**: `code_merge_staging` merges a `board/*` PR into a
   `staging` branch when CI is green, the architect seat's review is
   `accept`, the diff is within `maxChangedLines` and outside protected
   paths (auth, payments, migrations, infra), and the 12-hour hold has
   passed. A staging deploy and smoke check run in the siutindei repo.
4. **Owner promotes** staging → `main` from the daily review. Agents never
   merge to `main`, never force-push, never touch protected paths.

The `code` tool holds all of this; the runner workflow itself refuses
branches not prefixed `board/` and merges not targeting `staging`. This
requires a staging environment in the siutindei repo (decision §13-6).

## 11. Milestones (each shippable alone, all behind `BoardStaffEnabled`)

No dates, no commitment. Ordered so the owner can stop after any step and
still have something useful.

| # | Scope | Depends on |
|---|-------|------------|
| A0 | Sign off §13 | — |
| A1 | Task engine (§5) with Markdown/CSV/JSON deliverables; `staff` tool; **executives as their own workers** (no seats yet); manager review by the chair; Staff tab with task board and task page; minutes `assignee` | T1–T8 (shipped) |
| A2 | Triage for mail, Meta and reviews (§6); reply policies and escalation triggers (§7.1–7.2); `support` and `provider-success` seats; inbound replies under hold; Daily review page v1 (holds, escalations, sample) | A1 |
| A3 | Hold windows for every write op (§7.3); Scheduler sweep; circuit breakers (§7.6); daily digest email; lessons and trust-ramp metrics (§9) | A2 |
| A4 | Triage for GitHub, AWS, receivables; duties via Scheduler; `accountant`, `data-analyst`, `content-marketer`, `business-analyst`, `security-analyst` seats; boundary suggestions from the stand-up | A3 |
| A5 | Coding runner per §13-5; `architect`, `engineer-*`, `product-dev`; draft PRs; then staging autonomy and production promotion per §13-6 | A3, siutindei staging |
| A6 | `growth-specialist`; spend classes on hold; per-tool daily call caps (research, GitHub) | A3 |

Tests follow the existing pattern (fakes behind `HostRouter` /
`set_executor_for_tests`; `test_board_staff.py` for step idempotence, budget
stop, revision cap, level derivation; `test_board_triage.py` for routing and
escalation; hold execution and veto; Vitest for hooks; Playwright pass on the
Staff and Daily review tabs in `dev:mock`).

## 12. Assessment: what can realistically run itself

**Can, with the boundaries above**: replying on inbound threads (parents,
providers, reviews) under templates and tone rules; content production and
scheduling; bookkeeping, reconciliation and dunning; monitoring and triage of
CI, alarms and security alerts; research, analytics and KPI packs; specs,
issues and PRs; merging to a staging branch.

**Should stay with the owner**: money out (never built); legal, complaint
and child-safety threads (always escalated); identity and account setup
(Meta app review, bank, DNS, Cognito); production deployment of a product
handling children's data; changes to the board's own permissions and
budgets.

**Where it will hurt, and the mitigation**:

- *Review overload.* If the daily page lists everything, the bottleneck has
  moved, not gone. Hence holds as the only decision list, sampling instead of
  full reading, and breakers instead of vigilance.
- *A wrong reply to a parent.* Templates for sensitive classes, escalation
  triggers, no-hold only for inbound-initiated threads, rate limits, and a
  channel breaker on any post-hoc trigger.
- *Plausible, wrong deliverables.* Evidence rule, manager review by a
  different prompt, accountant proposes and reconciles but never posts.
- *Repeating the same mistake.* Lessons rendered into prompts; nothing is
  vetoed twice without a standing instruction.
- *Cost drift.* Separate staff budget, midday breaker, per-task caps; at full
  autonomy expect USD 20–40/day for the LLM side plus runner minutes.
- *Compounding hops.* Owner → executive → seat → executive → owner. Every hop
  is a row; deliverables are files; revisions are capped.
- *Runtime shape.* Chained Lambda steps suit LLM-and-API work; anything
  needing a filesystem or a browser goes to the runner.
- *PDPO.* Masking stays on every path; deliverables and replies are masked
  before storage; the owner sees real addresses only in Approvals and Mail.
- *Trust is not a switch.* The ramp makes autonomy a measured outcome per
  action class, not a global mode flip.

## 13. Decisions needed before any work starts

1. **Operating model** — confirm §1 as the target and default-approve with
   veto windows (§7.3) as the control mechanism, replacing "Approvals for
   every side effect".
2. **Boundaries v1** — the reply policy, escalation triggers, hold windows
   and rate limits in §7 as a starting set; anything to add or remove.
3. **Daily review** — page plus digest email; fixed HKT time; sample size
   `k`; whether unreviewed holds execute (proposed: yes, that is the point)
   or wait.
4. **Roster** — start with executives as their own workers (A1) and add
   seats as milestones need them, or ship all thirteen at once.
5. **Coding runner** — none, Copilot (A), `workflow_dispatch` runner (B), or
   Cursor Cloud Agents (C). This also changes the policy line in tools plan
   §2.1 to "board credentials never push; a scoped runner may open PRs on
   `board/*`".
6. **Staging** — create a staging branch and environment in the siutindei
   repo so agents can own it, with production promotion from the daily
   review; or stop at draft PRs.
7. **Budgets** — staff daily USD 20 to start, per-task 1 / 3, hard 10, max
   3 running (rising with triage on).
8. **Models** — `desk` / `senior` tiers or one model.
9. **Trust ramp thresholds** — veto rate and sample size for promoting a
   class to no-hold; breaker thresholds.
10. **Retention** — task rows, holds, lessons and deliverables 90 days
    (proposed) or indefinitely.
