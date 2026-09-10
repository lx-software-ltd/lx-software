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
