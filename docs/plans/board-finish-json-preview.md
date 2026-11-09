# Plan: Preview the JSON a finished task delivered

**Status**: Done
**Zone**: yellow (`backend/lambda/admin`, `apps/admin_web/src`)

## Corrections

The first read path rebuilt today's sample from the newest 400 tool calls. That could drop stored rows, disagree with the sent digest, and lose a "This was wrong" target. A read now fills `deliverablePreview` on the stored rows only, looked up by `CALL#<createdAt>#<callId>`, and does not write the snapshot.

The preview also shows on a chat reply, a meeting transcript and a task step, from the same JSON. Long bodies stay valid JSON plus a truncation line. The Settings card keeps DMARC beside the digest address. Schedule, context, models and the daily budget sit in the other column; catalog stays with staff.

## Goal

A `task_finish` row titled "Finished the task" currently points at the stored JSON (the result's `deliverableKey`, and on the daily review the task link). Show a preview of that JSON immediately under the title in the tool-call log and in "Sample of what ran". A JSON deliverable in the task drawer renders as formatted JSON. The Settings card's two columns carry a similar amount of content: schedule, defaults, context, models and the daily budget on the left; staff, catalog, the digest address and DMARC on the right.

## Non-goals

Changing which calls are sampled, the digest line, or how `task_finish` stores the blob. No new route. Markdown and CSV deliverables stay as they are. The stored review snapshot is not rewritten on read.

## Files

- `backend/lambda/admin/board_review_sample.py`: `deliverablePreview` on each sample row; a read fills it on the stored rows.
- `backend/lambda/admin/board_review_gaps.py`: today's review read calls `for_read`. `board_routes.py` stays the same length.
- `backend/lambda/admin/test_board_review_sample.py`: preview, truncation, digest stays free of the body, overlay does not write the snapshot.
- `apps/admin_web/src/lib/board/taskFinishPreview.ts`: pretty-print and clip a JSON deliverable.
- `apps/admin_web/src/components/board/BoardToolCallList.tsx`, `BoardToolsCard.tsx`, `BoardReviewSection.tsx`, `BoardTaskDrawer.tsx`, `BoardSettingsCard.tsx`.
- `apps/admin_web/docs/UI_COMPONENTS.md` and `docs/architecture/executive-board.md`: one sentence each.

## Invariants this change preserves

Sample membership, order and size stay the same. Arguments shown are still the masked tool-call arguments. The digest line does not grow to include the deliverable. A missing deliverable leaves the row as it is. `board_routes.py` and `board_review.py` do not grow.

## Done when

`python3 -m unittest test_board_review_sample.py` in `backend/lambda/admin` passes. `python3 -m ruff check backend/lambda/admin/board_review_sample.py backend/lambda/admin/board_review_gaps.py backend/lambda/admin/test_board_review_sample.py` passes. In `apps/admin_web`: `npm run test:unit` and `npm run lint`. `npm run dev:mock` shows the JSON under "Finished the task" on Review, and the Settings card columns are balanced.

## Rollback

Revert the commit. Older snapshots still render; a later read fills `deliverablePreview` on the rows they already stored.

## Open questions

None.
