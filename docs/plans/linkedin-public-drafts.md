# Plan: LinkedIn drafts on the public API

**Status**: Done
**Zone**: yellow

## Goal

`GET /public/lx-software/linkedin/posts?status=drafted` returns drafted posts for a key that already has `lxsoftware-linkedin`. The same parameter accepts `approved`, `published`, `archived`, `failed`, a comma-separated list of those, or `all`. With no parameter the route stays published-only.

## Non-goals

- No new scope, no new API Gateway route, no contract or CDK change
- No writes. Approving, editing, and publishing stay on the JWT routes
- No connection, tokens, image bytes, scene prompts, or metric error text
- No deploy from this change

## Files

- `docs/plans/linkedin-public-drafts.md` (this plan)
- `backend/lambda/admin/linkedin_public.py` — `posts_response`, status filter, `status` on each item
- `backend/lambda/admin/dispatch.py` — pass the query string; the file stays at 1346 lines
- `backend/lambda/admin/test_linkedin_public.py`
- `backend/lambda/admin/test_handler.py` — the scope test patches `posts_response`
- `docs/deployment/admin-website.md`

## Invariants this change preserves

- A key without `lxsoftware-linkedin` still gets 404
- The default response is still published posts only
- The path stays GET-only on the existing authorizer and read throttle
- Finance and board scopes do not allow this path
- `dispatch.py` does not grow

## Done when

- `python3 -m unittest test_linkedin_public test_handler.TestPublicReadRoutes test_routes` in `backend/lambda/admin` passes
- `python3 scripts/check_file_length.py` passes
- `python3 scripts/check_pii.py` passes

## Rollback

Revert the branch commit. The default read goes back to published posts only.

## Open questions

None. The existing `lxsoftware-linkedin` key reads drafts after deploy; it does not need reminting.
