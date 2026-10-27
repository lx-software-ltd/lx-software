# Plan: Repeat statement import

**Status**: Ready
**Zone**: yellow

## Goal

A statement whose filename was already imported must still be parsed when
the S3 key is new. Inbound mail stores each message under its own
`inbound/{owner}/{batch}/` prefix, so a re-sent PDF is parsed and its
lines are appended. The job succeeds.

A retried job uses the same S3 key. If that key is already on a statement
line, the job succeeds, calls no parser, and adds no lines.

The admin statement panel asks before uploading a filename that is already
on a line. The success mail says when a filename was already imported, and
whether the new object's size and S3 etag match an earlier copy.

The Morrison inbound PDF on 27 Oct 2026 failed with "already imported"
before OpenRouter ran. The same filename had been imported on 28 Sep.
That job stays failed. After deploy, download the PDF from Assets and
import it again; the panel asks before appending.

## Non-goals

- No line-level dedupe. A new S3 key with a repeated filename can add the
  same amounts again. The mail and the panel say so.
- Hand-entered statement lines still refuse a filename already linked to
  another line. That editor attaches one file to one typed line.
- No change to catalog "already imported", contracts, or CDK.
- This change does not re-queue the failed 27 Oct job.

## Files

- `docs/plans/repeat-statement-import.md` (this plan)
- `backend/lambda/admin/parse_statement.py` — parse a new key; skip a key already on a line
- `backend/lambda/admin/parse_jobs.py` — store the repeat notes on the job
- `backend/lambda/admin/parse_notify.py` — mention a repeated filename in the mail
- `backend/lambda/admin/dispatch.py` — do not return 409 before enqueue
- `backend/lambda/admin/test_handler.py`
- `backend/lambda/admin/test_parse_notify.py`
- `apps/admin_web/src/hooks/useParseStatement.ts` — do not block; surface repeat notes
- `apps/admin_web/src/components/StatementImportControl.tsx` — confirm before a repeated filename
- `apps/admin_web/src/components/HouseStatementPanel.tsx` — keep the line-editor refusal
- `docs/deployment/admin-website.md`

## Invariants this change preserves

- Unknown S3 keys, oversize batches, and parser errors still fail the job.
- Each new line stores `sourceAssetKeys` for the files parsed in that run.
- A filename already attached to another hand-entered line is still rejected
  in the line editor.
- A second run of a job whose key is already on a line does not append again.

## Done when

- `python3 -m unittest test_handler.TestParseRepeatsImportedBasename test_handler.TestParseJobPublicDoc test_parse_notify.TestBuildMessage -v`
  in `backend/lambda/admin` passes.
- `npm run test:unit -- src/hooks/useParseStatement.repeat.test.tsx src/hooks/useParseStatement.test.ts src/components/StatementImportControl.test.tsx`
  and `npm run lint` in `apps/admin_web` pass.
- `python3 -m ruff check backend/lambda/admin/parse_statement.py backend/lambda/admin/parse_jobs.py backend/lambda/admin/parse_notify.py backend/lambda/admin/dispatch.py backend/lambda/admin/test_handler.py backend/lambda/admin/test_parse_notify.py` passes.
- `python3 scripts/check_file_length.py` passes.

## Rollback

Revert this change. Repeated filenames fail again with 409 and the
inbound job is marked failed. Exact-key retries lose the skip.

## Open questions

None. A new key with a repeated name is parsed. The same key is not parsed twice.
