# Plan: request id reset and problem code

**Status**: Done
**Zone**: yellow

## Goal

Stop a warm Lambda process from reporting the previous invocation's request id, and stop `_with_problem` from keeping a `code` or `status` that means something other than the problem members.

## Non-goals

No change to success bodies, to `message` or `reason`, or to the public API authorizer. That function does not read this ContextVar. Webhook routes enter through `lambda_handler`.

## Files

- `backend/lambda/admin/http_common.py`
- `backend/lambda/admin/dispatch.py` (same line count)
- `backend/lambda/admin/test_http_common.py`

## Invariants this change preserves

- `dispatch.py` stays at its allowlisted length.
- `_require_admin` is not edited.
- An error that already carries the problem `code` and numeric `status` keeps them. Other keys on the body stay.

## Done when

`python3 -m unittest test_http_common -v` in `backend/lambda/admin` passes, and `python3 -m ruff check` is clean on the edited modules.

## Rollback

Revert this commit. Error bodies go back to `setdefault` for `code` and `status`, and the request id stays set until the next bind.

## Open questions

None. No error body in the admin Lambda sets `code` or `status` today. `reason` still carries the deny reason.
