# Plan: Daily review sample rows carry task context

**Status**: Done
**Zone**: yellow (`backend/lambda/admin/board_review.py` and a new sibling module); green for `apps/admin_web`

## Goal

"Sample of what ran" on the daily review lists hold-0 write tool calls from yesterday, but most rows read only "Finished the task", which tells the owner nothing. Each sample row now also carries who ran it, when, the op name, the masked arguments, and, when the call belongs to a staff task, the task id, assignee, status, brief and result summary. The web section shows that context, links the task id to the Tasks section, and folds the raw arguments and result preview under a Details toggle. The digest email line names the seat and the task brief.

## Non-goals

Changing which calls are sampled, the sample size, the seeded order, or the "This was wrong" lesson flow. No new API route. No change to how tool calls are recorded.

## Files

- `backend/lambda/admin/board_review_sample.py` (new): `collect()` builds the rows, `digest_line()` renders the mail line, one `get_task` lookup per task id.
- `backend/lambda/admin/board_review.py`: `_sample` and `_sample_line` delegate to the new module. The file shrinks, so its allowance in `scripts/file-length-allowlist.txt` is lowered.
- `backend/lambda/admin/test_board_review.py`: new test for the enriched row and the digest line.
- `apps/admin_web/src/lib/board/types.ts`: `BoardReviewSample` type.
- `apps/admin_web/src/components/board/BoardReviewSection.tsx`: richer row rendering.
- `apps/admin_web/src/components/board/BoardReviewSection.test.tsx`: renders inside a router and checks the task context and the Details toggle.
- `apps/admin_web/src/lib/mock/fixtures.ts`: a task-linked sample row for `npm run dev:mock`.

## Invariants this change preserves

Sample rows stay deterministic for a given date (seeded shuffle unchanged). Only `status == "ok"` write ops with zero hold hours are sampled. Arguments shown are the already-masked `arguments` field from the tool-call log; no new secret surface. A missing or deleted task yields `task: null` and the row still renders. `board_review.py` does not grow. The digest keeps the same section order and never links into the SPA.

## Done when

`python3 -m pytest backend/lambda/admin/test_board_review.py -q` passes. `python3 -m ruff check backend/lambda scripts` and `python3 scripts/check_file_length.py` pass. In `apps/admin_web`: `npm run lint`, `npm run test:unit`, `tsc --noEmit`. `npm run dev:mock` shows the task row under Siu Tin Dei → Board → Review → Sample of what ran, with the task link opening the task.

## Rollback

Revert the commit. Snapshots compiled with the richer rows still render in the old UI because the old fields are unchanged.

## Open questions

None.
