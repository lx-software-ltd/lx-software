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

## Later WPs

Notes will be appended here as each WP is built.
