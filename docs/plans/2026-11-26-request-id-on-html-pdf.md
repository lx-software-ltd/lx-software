# Plan: request id on HTML and PDF

**Status**: Done
**Zone**: yellow

## Goal

Make `_problem_field` keep a problem value without a no-op `setdefault`, and put `x-request-id` on HTML and PDF responses the same way JSON responses already get it.

## Non-goals

No change to success JSON bodies, to `message` or `reason`, or to the public API authorizer. The AWS usage path stays `/aws/usage.pdf` on this branch.

## Files

- `backend/lambda/admin/http_common.py`
- `backend/lambda/admin/board_newsletter.py`
- `backend/lambda/admin/board_outreach.py`
- `backend/lambda/admin/aws_billing.py`
- `backend/lambda/admin/test_http_common.py`
- `backend/lambda/admin/test_aws_billing.py`

## Invariants this change preserves

- A conflicting `code` or `status` is still replaced by the problem value.
- A body that already carries the problem value keeps it.
- `dispatch.py` is not edited.
- Newsletter and outreach stay at their allowlisted lengths.

## Done when

`python3 -m unittest test_http_common test_aws_billing -v` in `backend/lambda/admin` passes, and `python3 -m ruff check` is clean on the edited modules.

## Rollback

Revert this commit. HTML and PDF responses omit `x-request-id` again.

## Open questions

None.
