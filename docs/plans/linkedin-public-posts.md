# Plan: LinkedIn posts on the public API

**Status**: Done
**Zone**: red

Contracts and the HTTP API route table are red. The request is to add published LinkedIn posts to the API-key surface a cloud agent can call.

## Goal

`GET /public/lx-software/linkedin/posts` returns published posts (text, pillar, time, reactions, comments, impressions) for a key with scope `lxsoftware-linkedin`.

## Non-goals

- No drafts, connection, tokens, or image bytes
- No writes, and no new scope on existing keys
- No deploy and no live key mint from this change

## Files

- `docs/plans/linkedin-public-posts.md`
- `contracts/public-api-scopes.json` and the generated copies
- `backend/lambda/admin/linkedin_public.py`
- `backend/lambda/admin/board_public_api.py`
- `backend/lambda/admin/dispatch.py`
- `backend/lambda/admin/test_linkedin_public.py`
- `backend/lambda/admin/test_board_public_api.py`
- `backend/lambda/admin/test_handler.py`
- `backend/lambda/admin/test_routes.py`
- `backend/infrastructure/lib/admin-api-routes.ts`
- `backend/infrastructure/test/lxsoftware-stack.test.ts`
- `docs/deployment/admin-website.md`

## Invariants this change preserves

- Finance and board scopes do not allow this path
- The path is GET-only and uses the existing API-key authorizer and read throttle
- A key without `lxsoftware-linkedin` still gets 404
- Unpublished posts never leave this route

## Done when

- `python3 scripts/check-contracts.py` passes
- `python3 -m unittest test_linkedin_public test_board_public_api test_handler.TestPublicReadRoutes test_routes` in `backend/lambda/admin` passes
- `npm test` in `backend/infrastructure` passes
- `python3 scripts/check_file_length.py` passes

## Rollback

Revert the branch commit. Existing keys keep their current scopes.

## Open questions

None.
