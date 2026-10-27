# Plan: Repeat statement import

**Status**: Ready
**Zone**: yellow

## Goal

A statement whose filename was already imported must still be parsed.
Inbound mail, the house parse route, and the statement-book parse route
append the extracted lines. The job succeeds.

The Morrison inbound PDF on 27 Oct 2026 failed with “already imported”
before OpenRouter ran. The same filename had been imported on 28 Sep.

## Non-goals

- No line-level dedupe. A repeated file can add the same amounts again.
- Hand-entered statement lines still refuse a filename already linked to
  another line (`HouseStatementPanel`).
- No change to catalog “already imported”, contracts, or CDK.

## Files

- `docs/plans/repeat-statement-import.md` (this plan)
- `backend/lambda/admin/parse_statement.py` — do not raise on a repeated basename
- `backend/lambda/admin/dispatch.py` — do not return 409 before enqueue
- `backend/lambda/admin/test_handler.py`
- `apps/admin_web/src/hooks/useParseStatement.ts` — do not block the upload
- `apps/admin_web/src/hooks/useParseStatement.repeat.test.tsx`
- `docs/deployment/admin-website.md` — inbound mail still parses a repeated name

## Invariants this change preserves

- Unknown S3 keys, oversize batches, and parser errors still fail the job.
- Each new line still stores the full `sourceAssetKeys` list.
- A filename already attached to another hand-entered line is still rejected
  in the line editor.

## Done when

- `python3 -m unittest test_handler.TestParseRepeatsImportedBasename -v`
  in `backend/lambda/admin` passes.
- `npm run test:unit -- src/hooks/useParseStatement.repeat.test.tsx`
  and `npm run lint` in `apps/admin_web` pass.
- `python3 -m ruff check backend/lambda/admin/parse_statement.py backend/lambda/admin/dispatch.py backend/lambda/admin/test_handler.py` passes.

## Rollback

Revert this change. Repeated filenames fail again with 409 and the
inbound job is marked failed.

## Open questions

None. Re-importing a file appends lines, including duplicates.
