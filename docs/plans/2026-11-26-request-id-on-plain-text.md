# Plan: request id on plain text

**Status**: Done
**Zone**: yellow

## Goal

Put `x-request-id` on the plain-text responses in the newsletter, outreach, and Meta handlers the same way JSON responses already get it.

## Non-goals

No change to HTML, PDF, or JSON bodies. Do not edit `wire_format.py` or `wireFormat.ts`.

## Files

- `backend/lambda/admin/http_common.py`
- `backend/lambda/admin/board_newsletter.py`
- `backend/lambda/admin/board_outreach.py`
- `backend/lambda/admin/board_meta.py`
- `backend/lambda/admin/test_http_common.py`
- `backend/lambda/admin/test_board_t5.py`

## Invariants this change preserves

- The three handlers stay at their current line counts.
- The body and status of each plain-text response stay the same.
- A response with no bound request id omits the header.

## Done when

`python3 -m unittest test_http_common test_board_t5 -v` in `backend/lambda/admin` passes, and `python3 -m ruff check` is clean on the edited modules.

## Rollback

Revert this commit. Plain-text responses omit `x-request-id` again.

## Open questions

None.
