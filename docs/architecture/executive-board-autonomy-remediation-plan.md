# Executive Board autonomy — senior review and remediation plan

Review of branch `cursor/board-staff-plan-cdbc` (PR #341, WP1–WP10) against
`executive-board-autonomy-implementation.md` (the spec) and
`executive-board-autonomy-reviewer-notes.md`. This document is the hand-off
for the developer who remediates: every item has a stable id (`R-nn`), the
files to touch, the spec clause it serves, the evidence that it is real, the
change to make and the test that proves it.

Baseline at review time (HEAD `fd01cb3`): 707 admin-Lambda unit tests, 210
Vitest tests and 29 CDK tests pass offline; `eslint --max-warnings=0`, `tsc -b`,
CDK `tsc`, `check-contracts.py` and all 18 PR checks are green; no `TODO`,
`console.log`, `as any` or stray `print(` in the diff; Python byte-compiles.
Method: six independent read-only passes (foundations, WP2+4, WP3+9, WP5+6,
WP7+8, WP10/CDK/docs), each finding then re-verified by hand against the code
on this branch; two AWS-behaviour claims were checked against current AWS
documentation. One claimed defect (SES templates HTML-escaping `{{html}}`) was
found to be **false** — SES does not escape template variables — and is
omitted.

## 1. Verdict

The branch is functionally complete against a 1,400-line specification and
is inert with `SiutindeiBoardStaffEnabled=false`, so it is **safe to merge as is** but
**must not be enabled in production** until the P0 items below are fixed. The
recurring theme is that safety checks are applied at *proposal* time but not at
*execution* time, and that several multi-writer paths use unconditional writes
despite the spec asking for conditional ones. Nothing found reopens a §1
product decision; five items need an owner answer and are listed in §6.

| Severity | Count | Meaning |
|---|---|---|
| BLOCKER | 1 | Undermines the control model; fix before `SiutindeiBoardStaffEnabled=true` |
| HIGH | 11 | Safety, kill-switch, PDPO or "feature cannot work" gaps |
| MEDIUM | 14 | Correctness under concurrency, accounting, spec deviations |
| LOW | 12 | Hygiene, robustness, small spec gaps |

Gates:

- **P0 — before `SiutindeiBoardStaffEnabled=true`:** R-01, R-02, R-03, R-04, R-09, R-10, R-13, R-14, R-20, R-21.
- **P1 — before any outbound email (`SiutindeiBoardMailSendingEnabled=true`, outreach identity verified):** R-05, R-06, R-07, R-08, R-11, R-16, R-17, R-18, R-19, R-25.
- **P2 — before enabling WP10 `code_merge_staging` at `act`:** R-01 (merge part), R-22.
- **P3 — before the public newsletter form goes live:** R-12, R-18.
- **P4 — hardening and hygiene:** everything else.

## 2. BLOCKER and HIGH findings

### R-01 [BLOCKER] Scheduled holds execute without guards, breakers, level or tool kill-switch re-checks

- **Where:** `backend/lambda/admin/board_tools.py` `execute_call` (the `else: level = "act"` branch for non-persona actors; `act_guard`, `board_breakers.write_blocked` and `effective_level` are evaluated only when `ctx.actor == "persona"`); `board_holds.py` `_execute_one` (builds `ToolContext(actor="hold")`), `execute_due` (gates on `board_staff.enabled` only, never `tools_enabled`); `board_staff.handle_tick` (runs `execute_due` before `board_breakers.evaluate`); `board_code.py` `op_merge_staging` / `architect_accepted`; `board_meta._record_ads_commitment`.
- **Spec:** WP2 "executes due holds through the existing act path so audit, masking and caps apply unchanged" and "Potential issues → hold executes with stale data"; WP4 "Every write op checks `is_tripped(...)` in `execute_call`"; WP10 `code_merge_staging` guard (CI success, architect accept, ≤ 400 lines, no `PROTECTED_PATHS`); §5 kill-switch ladder.
- **Evidence:** A hold created at T executes at T+24 h with `level="act"` unconditionally. Between T and T+24 h any of the following is ignored: `SiutindeiBoardToolsEnabled=false` / `settings.tools.enabled=false` / `globalMode=readOnly`; a matrix or seat downgrade below `act`; a `channel:` / `tool:` / `outreach` breaker trip; a Meta spend-cap or allow-list change; a WhatsApp 24-hour window closing; for `code_staging`, new commits on the PR (red CI, protected paths, > 400 lines) because `merge_guard` ran once as `act_guard` and `architect_accepted` is keyed on PR number, not head SHA. N `spend:meta` holds each pass the cap check against the same snapshot and all execute (aggregate cap bypass). Only `mail_reply` (thread-changed) and `outreach_send` (its own breaker inside `send`) re-check anything. A reproduction with a tripped `channel:facebook` breaker and an injected failing guard executed the hold with `act_guard consulted: False`.
- **Remediation:**
  1. In `execute_call`, treat `ctx.actor == "hold"` like a persona for safety: re-derive `level` from the current matrix and seat roster for the stored `personaId` / `seatId`; run `op.act_guard` and `board_breakers.write_blocked`; check `tools_enabled(ctx.settings)`. If any check fails, return a `ToolOutcome(status="error", result={"error": reason})` and have `_execute_one` mark the hold `failed` with that reason (never silently convert a hold to an Approval; the owner sees it on the review page).
  2. In `handle_tick`, call `board_breakers.evaluate` (and reload settings) **before** `execute_due`.
  3. In `board_code`: persist `headSha` in the architect review deliverable and require equality with the PR head in `architect_accepted`; call `merge_guard` again inside `op_merge_staging` and refuse on any reason.
  4. In `board_meta`: record the ads commitment at hold creation (or include scheduled `spend:*` holds in `ads_spend_snapshot`) so concurrent holds cannot each fit the remaining cap.
  5. Keep `code_merge_staging` as `always_propose` until the siutindei `board-merge-staging.yml` re-verification workflow (Appendix A) exists and is confirmed.
- **Tests:** `test_board_holds.py`: hold scheduled → breaker tripped → execution ends `failed`; hold scheduled → persona downgraded to `propose` → `failed: level changed`; `test_board_code.py`: CI flips to failure between schedule and execution → not merged; new head SHA after accept → not merged; `test_board_t5.py`: two `spend:meta` holds whose sum exceeds the cap → second fails.

### R-02 [HIGH] Breaker and hold checks fail open on exceptions

- **Where:** `board_tools.py` `execute_call`: `except Exception: breaker_error = None` and `except Exception: hold_doc = None`.
- **Spec:** WP2 integration; WP4; §1 #1 (default-approve *with veto*).
- **Evidence:** If `board_breakers.write_blocked` or `board_holds.maybe_hold` raises (Dynamo throttle, import error, classification bug), control falls through to the final `else` and `_invoke_op` runs immediately — an `act`-level `outreach_send`, `content_publish` or `meta_propose_post` executes with no hold and no veto window. The `act_guard` path correctly fails closed (`guard_reason = "the safety check could not be completed"`).
- **Remediation:** On exception in either block set `guard_reason = "the safety check could not be completed"` (mirroring the guard path) so the call downgrades to an Approval. Keep the log lines.
- **Tests:** `test_board_holds.py`: monkeypatch `board_holds.maybe_hold` to raise → outcome `pending_approval`; same for `board_breakers.write_blocked`.

### R-03 [HIGH] Deploy-level kill switches do not reach the inbound-mail Lambda; `env_enabled()` fails open

- **Where:** `backend/infrastructure/lib/lxsoftware-stack.ts` `InboundStatementMailFn` environment block (no `BOARD_STAFF_ENABLED`, `BOARD_TOOLS_ENABLED`, `BOARD_MAIL_SENDING_ENABLED`, `OUTREACH_SENDING_DOMAIN`; only the `BOARD_MAIL_DOMAIN/_RAW_SEGMENT/_INBOUND_ADDRESS` loop is shared); `board_staff.env_enabled` (unset → `True`); `board_mail.ingest_bytes` → `board_triage.on_mail_ingested`; `board_triage._send_ack`; `board_staff.run_step` / `run_review` (no `enabled(settings)` check).
- **Spec:** §0 "With both off, nothing in this document runs"; §3.4 `SiutindeiBoardStaffEnabled` "every staff path"; WP3 acceptance (escalation ack sent).
- **Evidence:** Triage (classifier LLM call, task creation, `drain_queue` → `invoke_async` into `AdminApiFn`) runs inside `InboundStatementMailFn`, where the flag is unset and therefore read as enabled; `run_step` in `AdminApiFn` never consults the flag, so `SiutindeiBoardStaffEnabled=false` does not stop mail-driven task steps. In the same Lambda `sending_enabled()` reads an unset `BOARD_MAIL_SENDING_ENABLED` (fail-closed) and the role lacks `SiutindeiBoardMailSendPolicy`, so the escalation acknowledgement can never send in production. `own_domains()` there excludes the partners domain, so outreach replies are threaded as external.
- **Remediation:**
  1. Extend the existing `for (const fn of [adminFn, inboundStatementFn])` loop to add `BOARD_STAFF_ENABLED`, `BOARD_TOOLS_ENABLED`, `BOARD_MAIL_SENDING_ENABLED`, `OUTREACH_SENDING_DOMAIN`, `OUTREACH_FROM_LOCAL_PART` and any other env `board_triage`/`board_mail` read.
  2. Make `env_enabled()` fail closed: `return env in ("1", "true", "yes", "on")`. Update the WP1 reviewer note and the tests that rely on the unset default.
  3. Add `if not enabled(settings): return` at the top of `run_step`, `run_review` and the review invoke in `op_task_finish`.
  4. Have triage enqueue the ack via `board_async.invoke_async` to `AdminApiFn` instead of executing `mail_reply` inline in the ingest Lambda.
- **Tests:** `lxsoftware-stack.test.ts`: both functions carry the four variables; `test_board_staff.py`: `env_enabled()` false when unset; `run_step` no-ops when `BOARD_STAFF_ENABLED=false`.

### R-04 [HIGH] Per-task budget is never enforced (step usage is discarded)

- **Where:** `board_staff.py` `run_step`: `task["usage"] = _task_usage_add(task, usage)` is applied to a local copy; the function then re-reads `latest = board_store.get_task(...)` and persists `latest`, which still has the zeroed usage. `task.get("_finished")` is never set anywhere.
- **Spec:** WP1 `run_step` step 2 (`task.usage.cost < task.budgetUsd` → `_finish_incomplete`); §1 #9 per-task caps desk 1.0 / senior 3.0 / hard 10.
- **Evidence:** A scripted step with cost 0.01 wrote `STEP#001.usage.cost = 0.01` and `staffusage#` correctly, while the task row stayed `usage = {cost: 0, calls: 0}`. No test covers "Task budget exhausted". The SPA cost-per-card is always 0.
- **Remediation:** Apply `_task_usage_add(latest, usage)` after the re-read (or use an atomic `ADD usage.cost` update in a new `board_store.add_task_usage`), also on the `task_finish` path so the review row shows spend; delete the dead `_finished` guard.
- **Tests:** two steps → `usage.cost == 0.02`; third step with `budgetUsd=0.015` → `failed: "Task budget exhausted"`.

### R-05 [HIGH] Personal addresses reach the send path; prospect `type` can be rewritten

- **Where:** `board_prospects.py` `upsert` (`if not row.get("contact") and email: row["contact"] = email`, and `row.update({"type": ptype, ...})` on existing rows); `board_outreach.py` `op_upsert_prospect`, `send` (uses `prospect.contact or prospect.email` with no `_is_business_address` re-check); `_is_business_address` is applied only in `find_contact`.
- **Spec:** §1 #4 "named personal addresses are never used in v1"; §1 #3 restaurants never contacted; WP6 `find_contact` filter; proposal §7.1 PDPO Part 6A.
- **Evidence:** With `personalAddressesAllowed=False`, `outreach_upsert_prospect(email="peter.chan.1984@gmail.com")` stored that address as `contact`; `send()` returned `ok` and SES `ToAddresses` confirmed it. `outreach_upsert_prospect` is class `internal` (hold 0). A `parked` restaurant can be re-typed to `venue` and then qualified and mailed.
- **Remediation:** In `upsert`, promote `email` to `contact` only when `_is_business_address(email, allow_personal=_personal_allowed(settings))`; otherwise keep it in `raw` and set `contactRejected="personal"` so the row lands in "needs a contact". In `send()`, add a final `_refuse("personal address not allowed")`. Refuse `type` changes on existing rows unless `source="owner"` (`owner_put` remains the audited override).
- **Tests:** both entry points in `test_board_prospects.py` / `test_board_outreach.py`; type rewrite refused.

### R-06 [HIGH] `outreach_send` ignores `SiutindeiBoardMailSendingEnabled`

- **Where:** `board_outreach.py` `send` (checks breaker, identity, stage, suppression, cap; never `board_mail.sending_enabled()`); `board_newsletter.send_issue` and `board_review.send_digest` do check it.
- **Spec:** §5 "`SiutindeiBoardMailSendingEnabled` (all email)".
- **Remediation:** `if not board_mail.sending_enabled(): return _refuse("email sending is switched off")` before the SES call.
- **Tests:** `test_board_outreach.py` with `BOARD_MAIL_SENDING_ENABLED=false`.

### R-07 [HIGH] Shared mail-provider domains are indexed as prospect dedupe keys

- **Where:** `board_prospects.py` `_index_keys` (`contact.rsplit("@", 1)[1]` → `prospectkey#gmail.com`); fallback domain lookups in `board_triage._prospect_for_sender`, `board_outreach.maybe_handle_reply`, `board_holds._prospect_for_address`, `board_outreach.handle_ses_events`.
- **Spec:** §3.2 `prospectkey#{dedupeKey}` = registrable website domain / E.164 phone / place id; WP3 "sender is a prospect (`prospectkey#` lookup by domain)".
- **Evidence:** After upserting a provider with `hello@gmail.com`, `_prospect_for_sender("some.parent@gmail.com")` returned that prospect and the parent was classified `audience=provider` (routed to provider-success, not support); any Gmail reply containing "unsubscribe"/"取消" suppresses that prospect.
- **Remediation:** Index the contact's domain only when it equals `registrable_domain(website)`; add a public-mailbox denylist (gmail, googlemail, yahoo, hotmail, outlook, live, icloud, me, qq, 163, 126, ymail, protonmail) to `_index_keys` and to every domain fallback; always try the exact address first.
- **Tests:** `test_board_prospects.py` (no `gmail.com` key written); `test_board_triage.py` (Gmail parent not matched to a Gmail prospect).

### R-08 [HIGH] A positive reply that quotes our own footer is auto-suppressed

- **Where:** `board_outreach.py` `UNSUB_WORDS` (`unsubscribe|取消|不要再|退訂`, `re.I`) applied to the full body in `maybe_handle_reply`; `board_mail._body_text` does no quoted-text stripping; every default template in `board_sequences.py` ends with `Reply "unsubscribe" or use {unsubscribeUrl}` / `回覆「退訂」…`.
- **Spec:** WP6 "the word 'unsubscribe' in a reply → suppress"; §7.1 "a reply at any point moves the prospect to provider-success".
- **Evidence:** `"Yes, we would love to be listed!"` plus the quoted footer → `{'suppressed': True}`; no task created; prospect permanently suppressed. Most clients quote the original by default.
- **Remediation:** Strip quoted regions (`>`-prefixed lines, `On … wrote:`, `-----Original Message-----`, `寄件者:`, `From:` blocks) and our own footer sentence before matching; treat the keyword as an unsubscribe only when it appears in the unquoted body (or the unquoted body is short and consists mainly of it); otherwise mark `replied` and note the keyword match in the provider-success brief.
- **Tests:** positive reply with quoted footer → `replied`; bare "unsubscribe" → suppressed; "請取消" first line → suppressed.

### R-09 [HIGH] Raw inbound personal data enters prompt paths in triage

- **Where:** `board_triage.py` `classify_text` (`text[:4000]` sent to OpenRouter), `_open_or_append` (`NEW MESSAGE: {text[:800]}` appended to the scratchpad that `render_task_frame` renders), `render_event_brief` (raw subject), `on_meta_event` (prefers `msg.text` over `lastTextMasked`); `board_mail.ingest_bytes` passes `parsed.text` unmasked.
- **Spec:** §2 "Never store unmasked personal data in a prompt path: use `board_pii.Pseudonymizer`"; §5 PII.
- **Remediation:** Run subject and body through `board_mail.pseudonymizer(table).mask_text(...)` before the classifier call, the digest cache key, the brief and every scratchpad append; in `on_meta_event` use `textMasked` / `lastTextMasked` only.
- **Tests:** `test_board_triage.py`: a body containing a phone number and email reaches the fake model masked as `phone#N` / `contact#N`.

### R-10 [HIGH] Model-controlled URL fetches have no allow-list or private-network guard (SSRF)

- **Where:** `board_intel.py` `op_fetch_page` (`intel_fetch_page(url)`), `board_prospects.find_contact` (fetches `prospect.website` supplied via `outreach_upsert_prospect` plus `/contact*` paths), `board_crawl.py` `fetch` (default `urllib` opener, follows redirects) and `robots_allows` (only checks `scheme in (http, https)`).
- **Spec:** §1 #5 "Crawl: watchlist URLs plus homepage of discovered domains only"; WP5 `intel_fetch_page` "crawl a single **allowed** URL on demand".
- **Evidence:** Loopback, link-local (`169.254.169.254`, the Lambda runtime API on `127.0.0.1:9001`) and RFC1918 targets are not rejected before or after redirects; crawled competitor pages are prompt-injection surfaces that can steer the seat to fetch attacker URLs with context data in the query string.
- **Remediation:** In `board_crawl.fetch`, resolve the host and refuse loopback / link-local / RFC1918 / CGNAT / multicast before the request and on every redirect (custom `HTTPRedirectHandler`, max 3 hops); in `op_fetch_page`, accept only hosts present on the watchlist (`watch#` rows) or in discovered candidates; in `find_contact`, apply the same host check to `prospect.website`.
- **Tests:** `test_board_intel.py`: `http://169.254.169.254/` and a redirect to `127.0.0.1` refused; non-watchlist host refused; watchlist host allowed.

### R-11 [HIGH] SES IAM grants omit the configuration-set resource, so real sends are denied

- **Where:** `lxsoftware-stack.ts`: the outreach `PolicyStatement` (`ses:SendEmail`, `ses:SendRawEmail`, `ses:GetEmailIdentity` on `identity/<OutreachSendingDomain>` only) and `SiutindeiBoardMailSendPolicy` (identity only); `board_outreach.send`, `board_newsletter._send_confirm` / `send_issue` all pass `ConfigurationSetName`.
- **Spec:** WP6 "`ses:SendEmail` on the new identity ARN"; WP6/WP8 configuration sets; §7 "PR description lists every IAM grant".
- **Evidence:** The SES v2 authorization reference lists `configuration-set` as a resource type for `SendEmail`; AWS's own example policy includes both `identity/…` and `configuration-set/…` ARNs, and CDK issue #34402 documents `AccessDenied` when only the identity is granted. Unit tests use fakes and cannot catch this.
- **Remediation:** Add `formatArn({service:"ses", resource:"configuration-set", resourceName:"lxsoftware-admin-siutindei-outreach"})` and `…-newsletter` to the two statements (also `ses:SendBulkEmail` to the outreach statement if bulk is ever used there). Scope the template statement (`ses:CreateEmailTemplate` etc., currently `*`) to `template/lxsoftware-admin-siutindei-*`.
- **Tests:** `lxsoftware-stack.test.ts` asserts the configuration-set ARNs on both policies.

### R-12 [HIGH] The public newsletter form cannot reach the API (CORS)

- **Where:** `lxsoftware-stack.ts` `HttpApi.corsPreflight.allowOrigins` (admin web domain only); `apps/public_www/src/lib/newsletter.ts` (JSON `POST` → preflight); `apps/public_www/src/components/NewsletterForm.tsx`.
- **Spec:** WP8 "Public site: `NewsletterForm` posting to the public route … verify".
- **Evidence:** The browser preflight from the public-site origin is rejected; the form always shows the failure state. No CDK test or doc covers it.
- **Remediation:** Add a `PublicSiteOrigins` CSV stack parameter and append it to `allowOrigins` (or add a separate CORS configuration for `/public/newsletter/*`); confirm with the owner which site hosts the form (see §6). Add a browser-level check to the WP8 acceptance.
- **Tests:** `lxsoftware-stack.test.ts` asserts the origin list; manual browser check recorded in the PR.

## 3. MEDIUM findings

### R-13 [MEDIUM] `claim_task_step` is not a mutual-exclusion claim for steps > 0; step 1 is never claimed

- **Where:** `board_store.py` `claim_task_step` (the `expected_step > 0` branch only sets `updatedAt` under `status = running AND step = expected`); `board_staff.run_step` (`if wanted > 1 and not claim…`).
- **Spec:** WP1 "Every step must be idempotent through `claim_task_step`; never write the step row before the claim succeeds" (mirrors `claim_meeting_phase`).
- **Evidence:** Two concurrent deliveries of the same `{taskId, step}` both pass the condition, both run the model and tool loop (duplicate writes, double spend) and both write `STEP#{seq}`. `step` is only advanced at the end.
- **Remediation:** Make the claim `SET stepClaimed = :wanted, stepClaimedAt = :now` with `ConditionExpression #st = :running AND #step = :expected AND (attribute_not_exists(stepClaimed) OR stepClaimed < :wanted)`; claim step 1 too; write the step row keyed on the claimed seq.
- **Tests:** two claims for the same step → one `True`, one `False`.

### R-14 [MEDIUM] Settings writes are unconditional; the SPA's stale draft clobbers ramp promotions and cap raises

- **Where:** `board_store.py` `save_settings` (increments `version`, writes with `_put_state`; `_put_state_if_version` exists but is used only by `board_pii`); `board_holds._demote` / `promote` (write the tick's stale `settings`); `board_breakers._fresh_save_staff` (rewrites on every tick while ≥ 100 %); `board_routes._boundaries_put` (replaces the whole `boundaries` object); `apps/admin_web/src/components/board/BoardBoundariesCard.tsx` (`useState(boundaries)` seeded once, never resynced).
- **Spec:** §5 Concurrency "`settings` writes use a version attribute"; WP4 "read-modify-write with a `version` attribute".
- **Evidence:** `holdOverrides`, `outreach.dailyCap` and `capRaisedAt` live inside `boundaries`; an owner who saves the Boundaries card after a 08:00 cap raise or a ramp promotion silently reverts them, and the server accepts the write regardless of `version`. `_demote` can overwrite an owner's `staff.enabled=false` set during the tick.
- **Remediation:** `save_settings` → `_put_state_if_version(attr="version", expected=doc["version"])`, one reload-and-retry for automated writers, `409` for owner routes; `_boundaries_put` merges only the fields the card edits (holds, reply policy, keywords) and returns `version`; the SPA sends `version`, resyncs the draft when the query data changes (`useEffect` on `boundaries`) and refetches on 409.
- **Tests:** stale version → `ConditionalCheckFailedException` → retry path; Vitest for the card resync.

### R-15 [MEDIUM] Staff daily spend counter is a non-atomic read-modify-write

- **Where:** `board_store.py` `add_staff_usage_day` (`load_staff_usage_day` → `_put_state`); contrast `add_external_usage_day` (atomic `ADD`).
- **Spec:** WP1 `staffusage#`; WP4 `budget` breaker 80 % / 100 % rules.
- **Remediation:** Single `update_item` with `ADD cost :c, calls :n, promptTokens :p, completionTokens :k, bySeat.#seat.cost :c, bySeat.#seat.calls :n`, creating the map with `if_not_exists`, `SET expiresAt`.
- **Tests:** two concurrent adds on `FakeTable` sum correctly.

### R-16 [MEDIUM] Outreach daily cap and post-send bookkeeping are not safe under concurrency or failure

- **Where:** `board_outreach.py` `send`: reads `day.sent`, checks the cap, calls SES, then `ingest_bytes` → `put_prospect` → `save_outreach_day`.
- **Spec:** §1 #4 warm-up cap; WP6 "Warm-up: a brand-new subdomain sending 100/day immediately will be filtered".
- **Evidence:** Several due holds in one tick each read the same `sent` and all pass; the increment happens after the SES call, so a crash in `ingest_bytes`/`put_prospect` leaves the touch and counter unrecorded and the next task re-sends step 0.
- **Remediation:** Reserve the slot first with `update_item ADD sent :one` + `ConditionExpression sent < :cap` (release on SES failure); write a provisional touch (`sesMessageId` pending) before the send and finalise after.
- **Tests:** two sends at `cap - 1` → one refused; SES success + `put_prospect` failure → touch still recorded on retry.

### R-17 [MEDIUM] Newsletter issue send is not idempotent; metrics can never be attributed; bulk results ignored

- **Where:** `board_newsletter.py` `send_issue` (no `status == "sent"` check, no per-batch checkpoint, `sent += len(chunk)`, `send_bulk_email` without `DefaultEmailTags`), `recipients` (`limit=2000`), `handle_ses_events` (looks up `mail.tags.issueId`).
- **Spec:** WP8 "metrics from SES open/click events … written to the issue row"; WP1 duplicate async invocations.
- **Remediation:** Claim `draft → sending` with a conditional update; persist `sentThrough` per batch and skip completed offsets on retry; refuse when already `sent`; pass `DefaultEmailTags=[{"Name":"issueId","Value":issue_id}]`; count only `Status == "SUCCESS"` entries and log failures; paginate subscribers.
- **Tests:** second `send_issue` call is a no-op; fake SES receives the tag; a failed entry is not counted.

### R-18 [MEDIUM] Public subscribe endpoint can un-confirm or clobber subscribers, bomb third parties, and unsubscribe is permanent

- **Where:** `board_newsletter.py` `handle_subscribe` (row keyed by `sha256(email)` only; `list` and `confirmedAt: ""` overwritten), `_rate_limited` (100/h per IP only), `handle_unsubscribe` (`board_outreach.suppress(email=...)`), `recipients`.
- **Spec:** §3.2 `newsletter#sub#{digest}` / gsi1 `newsletter#{list}`; WP8 double opt-in "prevents list poisoning".
- **Evidence:** Posting a confirmed `parents` subscriber's address with `list="providers"` resets `confirmedAt` and moves the row; a person cannot be on both lists; a distributed caller can make `news@siutindei.com` send unlimited confirmation mails to a victim; after unsubscribing, a parent can never re-subscribe (generic 200, no mail).
- **Remediation:** Key rows by `{list}#{digest}` (or per-list state in one row) and route tokens accordingly; never reset an existing `confirmedAt` from the public route; add a per-digest confirm cooldown (`nl-confirm:{digest}`, 24 h, max 3/day) and skip when a pending confirm exists; keep newsletter opt-out on the subscriber row (`unsubscribedAt`) instead of the outreach suppression list, or let an explicit subscribe clear a `reason="newsletter unsubscribe"` row.
- **Tests:** cross-list subscribe keeps the first list confirmed; fourth confirm in a day not sent; re-subscribe after unsubscribe works.

### R-19 [MEDIUM] SES events: newsletter bounces inflate the outreach breaker; batch has no partial-failure reporting

- **Where:** `dispatch.py` SQS branch (every record goes to both `board_outreach.handle_ses_events` and `board_newsletter.handle_ses_events`); `board_outreach.handle_ses_events` increments `outreachday#.bounces/complaints` without checking `mail.tags["ses:configuration-set"]`; `lxsoftware-stack.ts` `SqsEventSource(queue, { batchSize: 10 })`.
- **Spec:** WP6 7-day bounce > 5 % / complaint > 0.1 % breaker over ≥ 50 sends; WP8 "configuration set `…-newsletter` sharing the SQS bounce path".
- **Evidence:** A newsletter to a few thousand subscribers with a handful of complaints exceeds 0.1 % of ≤ 100 outreach sends and trips the `outreach` breaker, freezing the cap ramp. One bad record fails the whole batch of ten.
- **Remediation:** Route each record by configuration-set tag (or `prospectId` vs `issueId` tag) to exactly one handler, keeping address suppression shared; enable `reportBatchItemFailures` and return `batchItemFailures`.
- **Tests:** newsletter-tagged complaint leaves `outreachday#` unchanged; one bad record → only its `messageId` reported.

### R-20 [MEDIUM] Trust ramp has no demotion signal once a class is promoted

- **Where:** `board_holds.py` `record_ramp` (called only from `_execute_one` and `veto`), `list_ramp` (derives class keys from the last 200 holds); `board_review` "This was wrong" → `board_lessons.create_from_correction` (no ramp update).
- **Spec:** §1 #11 "Demote when veto rate > 10 % over the trailing 20 actions"; WP4 `sample` of hold-0 actions.
- **Evidence:** After `holdOverrides[classKey] = 0` no hold rows exist, so `record_ramp` never fires and vetoes are impossible; owner corrections on sampled actions do not count; promoted classes drop out of `GET /ramp` once their old holds age out.
- **Remediation:** Call `record_ramp(..., vetoed=False)` from `execute_call` for immediate act-level writes of ramped classes; count `review/sample/{callId}/wrong` as a veto for that call's `classKey`; keep a `ramp-index` state doc instead of deriving keys from holds.
- **Tests:** promote → 3 immediate acts → 1 "wrong" → veto rate computed → demotion when > 10 %.

### R-21 [MEDIUM] Manager review fails open on an unparsable verdict

- **Where:** `board_staff.py` `run_review` (`verdict = "accept"` unless JSON parses to exactly `"return"`).
- **Spec:** WP1 §5.4 manager review as the check against plausible-but-wrong deliverables.
- **Remediation:** Treat unparsable / unknown verdicts as `return` (or `needs_owner` after the stuck sweep's retry) and log `board_staff_review_unparsed`.
- **Tests:** empty and non-JSON completions → `return`.

### R-22 [MEDIUM] `_pr_files` reads only the first 100 files

- **Where:** `board_code.py` `_pr_files` (`per_page=100`, one page); `review_bundle`, `merge_guard`.
- **Spec:** WP10 guard; "Protected paths bypass via renames … evaluate both old and new paths".
- **Remediation:** Paginate until a short page; refuse when `pr.changed_files` differs from the fetched count.
- **Tests:** fake GitHub returning 150 files with a protected path on file 120 → refused.

### R-23 [MEDIUM] `GET /prospects` has no cursor pagination and is O(n²)

- **Where:** `board_prospects.py` `list_for_api` (`limit=max(limit, 400)` across ten stages, then `possible_duplicates` per row, each a further 400-row scan); `board_routes.py` prospects GET; `apps/admin_web/src/hooks/useBoardPipeline.ts`.
- **Spec:** §5 "`prospects#{stage}` can reach tens of thousands … add `cursor` query params on the prospect list route".
- **Remediation:** Return `nextCursor` (base64 `LastEvaluatedKey`) and accept `cursor`; compute `possibleDuplicates` only in `GET /prospects/{id}` (or precompute a `nameKey` attribute); wire the cursor into `useBoardPipeline`.
- **Tests:** two pages of a 30-row stage with `limit=20`.

### R-24 [MEDIUM] All 15 seats are `isActiveDefault: true` and `maxRunningTasksDefault` is 6

- **Where:** `contracts/board-staff.json`.
- **Spec:** §1 #16 "unused ones are `isActive=false` by default"; WP3 "the only three that default on"; §1 #9 `maxRunningTasks` 3 → 6 after WP4; §6 rollout runbook steps 1–7.
- **Evidence:** One `settings.staff.enabled` flip activates prospector, content-marketer, engineers, architect and product-dev at once (triage, targets, duty catch-up, `board_code.handle_tick`), the opposite of the staged runbook.
- **Remediation (owner to confirm, see §6):** restore `isActiveDefault: false` for every seat except `support`, `provider-success`, `community-manager` (and `business-analyst` if the daily review is wanted from day one); set `maxRunningTasksDefault` 3; document in the runbook which seat to flip on at each step; tests that need other seats use `save_staff_override`. Run `sync-contracts.py` after the change.

### R-25 [MEDIUM] Advertised `mailto:` unsubscribe has no receiving path

- **Where:** `board_outreach.py` `send` sets `List-Unsubscribe: <https…>, <mailto:unsubscribe@{sending_domain}?subject={token}>`; no receipt rule, fanout or handler references `unsubscribe@`.
- **Spec:** WP6 step 3; §7.1 UEMO "functional unsubscribe facility".
- **Remediation:** Either add a receipt rule for `partners.siutindei.com` → inbound handler that parses `subject={token}` into `suppress()`, or advertise the HTTPS URL only (RFC 8058 permits HTTPS-only with `List-Unsubscribe-Post`).

### R-26 [MEDIUM] Budget breaker and usage day: re-disables staff every tick, `seniorPaused` never clears, UTC day vs HKT rule

- **Where:** `board_breakers.py` `evaluate` (`ratio >= 1.0` → `_fresh_save_staff(enabled=False)` on every tick; "80 % before noon HKT" evaluated against a UTC `staffusage#` day); `board_store.normalize_staff_config` (nothing resets `seniorPaused` / `disabledReason`); `BoardSettingsCard.tsx` (does not show `disabledReason`).
- **Spec:** WP4 budget breaker; §8.6 "reset only from the review page"; §5 time zones.
- **Evidence:** An owner who re-enables staff while the UTC day is still over budget is flipped back within 5 minutes with no feedback; between 08:00 and 12:00 HKT the day's spend is near zero so the 80 % rule cannot fire.
- **Remediation:** Disable only on the trip transition; block the toggle while `budget` is tripped and surface `disabledReason` in the card; reset `seniorPaused` on breaker reset or day rollover; key `staffusage#` by HKT date (or compute the ratio over the HKT window).

## 4. LOW findings

### R-27 [LOW] `STEP#` and `REVIEW#` rows never receive a TTL
`board_store.put_task_step` / `put_task_review` (§3.2 "with task"). Stamp `expiresAt` when the task reaches a terminal state, or at creation with the retention window.

### R-28 [LOW] Evidence validation uses a global 200-row tool-call window
`board_staff.op_task_finish`, `run_review` (`list_tool_calls(limit=200)`), `board_lessons.get_tool_call` (500). With six concurrent tasks a long task's early calls fall out of the window and valid evidence is flagged `no_evidence`. Query tool calls by `taskId` (gsi1 key or `STEP#` `callIds`).

### R-29 [LOW] Unused statuses and re-proposed vetoes
`holdStatuses.expired` and `taskStatuses.returned` are never written; holds left `scheduled` while staff is disabled all fire in one tick on re-enable; a vetoed `outreach_send` hold is re-proposed the next 08:00 because `nextTouchAt` is untouched. Mark holds `expired` when `now > executeAt + 24 h` or staff is disabled; on veto of `outreach_send` push `nextTouchAt` or park the prospect with `vetoedAt`; either implement `returned` or remove it from the contract.

### R-30 [LOW] Duty task creation is a non-conditional read-then-write
`board_duties.run_due`: `get_cache(duty:{seat}:{duty})` → `find_open_event_task` → `create_task` → `put_cache`; overlapping ticks can create the same duty twice. Make the per-duty marker write conditional (`attribute_not_exists` on a `duty:{seat}:{duty}:{date}` row) before `create_task`.

### R-31 [LOW] `slotAt` shorter than the publish hold shrinks the veto window
`board_holds.maybe_hold` passes `execute_at=slot_at` for `content_publish` (spec-conformant per WP7, but §8.4 says 24 h). Use `max(slotAt, now + hours)` while the class hold is > 0, or flag items scheduled inside the window.

### R-32 [LOW] District mapping mis-assigns common addresses
`board_hk.district_from_address` matches generic tokens (`North`, `Central`, `Eastern`, `Southern`, `Islands`) by substring, so "North Point Road" → `North`; unmapped returns `""` not `"unknown"` (WP6). Order specific tokens first, add negative look-ups, return `"unknown"`.

### R-33 [LOW] Outreach personalisation is unchecked free text
`board_outreach.render_message` prepends `personalisation[:400]` verbatim; `outreach_send` has no `act_guard`. Reuse the `board_policy` forbidden-promise patterns as an `act_guard` (violation → Approval with reason).

### R-34 [LOW] Unsubscribe token parsing splits on a byte that may appear in the MAC
`board_outreach.parse_unsub_token` does `raw.split(b".", 1)`; the 16-byte MAC is fixed length, so use `raw[:-16]` / `raw[-16:]` and drop the separator. Also makes the newsletter `c:list:digest` payload safe if a list name ever contains a dot.

### R-35 [LOW] Font binaries are committed twice (~14 MB duplicated)
`backend/lambda/admin/fonts/`: `cmp` shows `NotoSans-Regular.ttf` ≡ `NotoSans-Bold.ttf` and `NotoSansTC-Regular.otf` ≡ `NotoSansTC-Bold.otf` (the reviewer notes say `board_creative` selects the `wght` axis of one variable font). Keep one variable file per family, point both weights at it, and remove the duplicates before merge so they do not enter `main` history.

### R-36 [LOW] `_origin_from_ctx` records task-originated assignments as `chat`
`board_staff._origin_from_ctx` returns `"chat"` for `kind == "task"` and ends in a dead conditional (`"chat" if ctx.kind == "chat" else "chat"`). Add a `task` origin to `BOARD_STAFF_TASK_ORIGINS` (contract change) or map `kind == "task"` to the parent's origin, and simplify the tail.

### R-37 [LOW] `always_propose` publish ops become auto-executing holds when staff is on
`board_holds.maybe_hold` exempts only `code_promote`; `meta_propose_post` / `meta_propose_story` (`always_propose=True`) become 24 h holds. The spec contradicts itself (WP2 integration vs WP2 acceptance) and the branch chose the acceptance test. Keep if the owner confirms (§6), but state it in `docs/deployment/admin-website.md` and `AGENTS.md`, and exempt by action class (`code_production`) rather than by op name.

### R-38 [LOW] Newsletter rate limiter and suppression digest are read-modify-write
`board_newsletter._rate_limited` and `board_outreach._rate_limited` increment via `get_cache` → `put_cache`. Acceptable for a soft limit; switch to `ADD count :one` if R-18's per-address cooldown is built on the same helper.

## 5. Ordered execution plan

Work in this order; each step is one PR against the feature branch with its own tests, and CI (lint, contracts, CDK build, viewport smoke, Checkov, CodeQL, Semgrep) must stay green.

1. **Control model at execution time** — R-01 (steps 1–2, 4), R-02, R-20, R-21. Touches `board_tools.execute_call`, `board_holds._execute_one` / `execute_due`, `board_staff.handle_tick` / `run_review`, `board_meta`. Largest behavioural change; do it first so every later fix is tested against the corrected path.
2. **Kill-switch reach** — R-03 (CDK env loop, `env_enabled` fail-closed, `run_step` / `run_review` gate, ack via `invoke_async`). Touches `lxsoftware-stack.ts`, `board_staff.py`, `board_triage.py`, `lxsoftware-stack.test.ts`; update the WP1 reviewer note.
3. **Task engine accounting and idempotency** — R-04, R-13, R-15, R-27, R-28, R-30, R-36. Touches `board_staff.py`, `board_store.py`, `board_duties.py`, contracts if a `task` origin is added.
4. **Settings concurrency** — R-14, R-26. Touches `board_store.save_settings`, `board_holds`, `board_breakers`, `board_routes._boundaries_put`, `BoardBoundariesCard.tsx`, `BoardSettingsCard.tsx`, `useBoardBoundaries.ts`.
5. **Outreach safety (PDPO and reputation)** — R-05, R-06, R-07, R-08, R-16, R-25, R-33, R-34. Touches `board_prospects.py`, `board_outreach.py`, `board_triage.py`, `board_sequences.py`.
6. **PII and SSRF** — R-09, R-10. Touches `board_triage.py`, `board_crawl.py`, `board_intel.py`, `board_prospects.find_contact`.
7. **SES plumbing and IAM** — R-11, R-19. Touches `lxsoftware-stack.ts` (both SES policies, `SqsEventSource`), `dispatch.py`, `board_outreach.handle_ses_events`, `board_newsletter.handle_ses_events`. Verify on a dev stack with one real send per configuration set.
8. **Newsletter correctness** — R-12, R-17, R-18, R-38. Touches `board_newsletter.py`, `board_store` newsletter keys (data model change — add a migration note; no live rows exist yet), `lxsoftware-stack.ts` CORS parameter, `apps/public_www`.
9. **Engineering runner** — R-01 step 3, R-22. Touches `board_code.py`, `test_board_code.py`. Keep `code_merge_staging` `always_propose` until Appendix A workflows land in siutindei.
10. **Contracts and roster** — R-24 (after the owner answers §6), R-37 exemption by class. Run `python3 scripts/sync-contracts.py && python3 scripts/check-contracts.py`.
11. **Hygiene** — R-23, R-29, R-31, R-32, R-35 (font de-duplication should land before merge to `main` to keep the blobs out of history).
12. **Docs** — update `executive-board-autonomy-reviewer-notes.md` (close each item or record the owner decision), `docs/deployment/admin-website.md` (CORS parameter, configuration-set grants, `env_enabled` semantics, hold-of-`always_propose` behaviour), `AGENTS.md` gotchas, and the §6 runbook (which seat to enable at each step).

Definition of done for the whole plan: every `R-nn` above is either fixed with a named test or closed with a recorded owner decision; the reproductions in this document (hold executes past a tripped breaker, personal address mailed, Gmail prospect match, quoted-footer suppression, task usage stays zero) all fail as tests before and pass after; `SiutindeiBoardStaffEnabled=true` is exercised on a dev stack end to end (inbound mail → triage → task → manager review → digest; one outreach send; one newsletter confirm) with the CloudWatch log lines named in the spec's acceptance sections captured in the PR.

## 6. Decisions needed from the owner (do not reopen §1; these are ambiguities the spec leaves open)

1. **Seat roster count and defaults (R-24).** Spec says sixteen seats and "unused ones are `isActive=false`"; the contract ships fifteen, all active. Confirm the fifteen-seat roster and whether the staged runbook (three seats on at step 2) still applies.
2. **`always_propose` ops under staff (R-37).** With staff enabled, `meta_propose_post` / `meta_propose_story` become 24 h holds instead of Approvals. Confirm or revert to Approvals.
3. **Newsletter form home and origin (R-12).** The form was placed in the LX Software public site footer; confirm whether it belongs on the Siu Tin Dei site instead, and provide the origin(s) for CORS.
4. **`mailto:` unsubscribe (R-25).** Provision `unsubscribe@partners.siutindei.com` inbound, or ship HTTPS-only.
5. **`code_merge_staging` at `act` (R-01, R-22).** Keep `always_propose` until the siutindei workflows in Appendix A are live and the head-SHA binding is in place.

Also still awaiting sign-off, as recorded in the reviewer notes: brand colours / logo, `PROVIDER_SIGNUP_URL`, Places Enterprise SKU prices, and the single-PR delivery (spec asked for one PR per WP; per-WP commits exist for bisecting).

## 7. What is done well

The implementation is complete against the spec and disciplined: every route, schedule (all EventBridge Scheduler, none `events.Rule` on `AdminApiFn`), contract and SPA section exists and is exercised by 707 Python, 210 Vitest and 29 CDK tests that run offline in seconds; contracts are synced and CI-checked; the public routes follow the Meta-webhook throttle pattern with the stage dependency that avoided the earlier `UPDATE_ROLLBACK_FAILED`; secrets are CDK-generated and read lazily; HMAC tokens use `compare_digest`; FEHD XML is parsed with `defusedxml`; `claim_hold` / `claim_task_step` (step 0) / `claim_approval_decision` are conditional updates; `mail_reply` holds re-check the thread; quiet hours shift rather than refuse; content publish is idempotent by `platformPostId` and caption hash; `act_guard` failures fail closed; and the reviewer-notes file records every intentional deviation with its reasoning, which is what made this review tractable. The gaps above are concentrated in one pattern (checks at proposal time but not at execution time) and one habit (unconditional writes on multi-writer documents); both are mechanical to fix with the fakes already in the test suite.
