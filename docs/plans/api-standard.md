# Plan: one API standard

**Status**: In progress
**Zone**: red for `backend/infrastructure/**`, `backend/lambda/public_api_authorizer/**`, `contracts/**`, and `scripts/manage-public-api-keys.py`. Yellow for the remaining Lambda handlers and the admin site. The owner approved those red paths for this plan, and no others.

## Goal

Bring lx-software onto the shared API shape in three pull requests. L1 adds `PATCH` to CORS, exposes `x-request-id`, and adds the problem members to error bodies while keeping `message` and `reason`. L2 moves routes under `/v1/<audience>/` and converts JSON keys at the boundary. L3, a draft, closes the execute-api endpoint after 25 Dec 2026. The steps are in the actions plan at commit `dadcbf4d63519cb93117f85925b6f90e013e057b`:

https://github.com/lx-software-ltd/actions/blob/dadcbf4d63519cb93117f85925b6f90e013e057b/docs/plans/api-standard.md

## Non-goals

No rename in L1. `_require_admin` and `write_blocked` stay as they are. No deploy.

## Files

- `backend/infrastructure/lib/admin-http-api.ts` and `backend/infrastructure/test/lxsoftware-stack.test.ts` (L1)
- `backend/lambda/admin/http_common.py` and `backend/lambda/admin/test_http_common.py` (L1)
- `backend/lambda/admin/dispatch.py` binds the request id without growing the file (L1). L2 shortens it, and `scripts/file-length-allowlist.txt` records the new length.
- L2 and L3 follow the actions plan. L3 deletes this note.

## Invariants this change preserves

- Existing error keys `message` and `reason` stay.
- A success body is not given problem members.
- `_require_admin` and `write_blocked` are not edited.
- `dispatch.py` does not grow. Its allowlist entry shrinks when the file does.

## Done when

L1: the new stack test and `test_http_common.py` pass, then the checks in `AGENTS.md` for the files this pull request touches.

## Rollback

Revert the pull request. L1 adds fields and a CORS method. It removes nothing.

## Open questions

None. The actions plan settled the shape.
