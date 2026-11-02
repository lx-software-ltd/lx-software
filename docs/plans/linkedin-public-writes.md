# Plan: LinkedIn draft writes on the public API

**Status**: Done
**Zone**: red

The route table lives in `backend/infrastructure/**`. The owner asked for create, update, and delete on the key that already has `allowWrite` and `lxsoftware-linkedin`. `write_blocked` stays as it is.

## Goal

A key with `lxsoftware-linkedin` and `allowWrite`, while `PublicApiWritesEnabled` is on, can:

- `POST /public/lx-software/linkedin/posts` create a drafted post from `body`, `firstComment`, `hashtags`, and `pillar`
- `GET /public/lx-software/linkedin/posts/{id}` read one post in the same shape as the list
- `PUT /public/lx-software/linkedin/posts/{id}` update those four fields on a drafted or approved post
- `DELETE /public/lx-software/linkedin/posts/{id}` archive a post that is not published

## Non-goals

- No new scope and no key minting
- No change to `write_blocked`. LinkedIn is allowed in `write_deny_reason` because that function fail-closes every non-board path
- No approve, unapprove, mark-posted, regenerate, image, character, settings, or connection calls
- No picture queue on create. A public create does not spend the image budget
- No hard delete. The store archives
- A published post cannot be edited or archived through this key

## Files

- `docs/plans/linkedin-public-writes.md` (this plan)
- `backend/lambda/admin/board_public_api.py` — one-segment post path is `lxsoftware-linkedin`; that scope skips `write_blocked`
- `backend/lambda/admin/linkedin_public.py` — `handle`
- `backend/lambda/admin/dispatch.py` — same line count; item paths are public and writes call `handle`
- `backend/infrastructure/lib/admin-api-routes.ts` — POST on the collection, GET/PUT/DELETE on `{id}`, write throttle 1/5
- `backend/infrastructure/test/lxsoftware-stack.test.ts`
- `backend/lambda/admin/test_linkedin_public.py`
- `backend/lambda/admin/test_board_public_api.py`
- `backend/lambda/admin/test_handler.py`
- `docs/deployment/admin-website.md`

## Invariants this change preserves

- A key without `lxsoftware-linkedin` still cannot read or write these paths
- A key without `allowWrite`, or with writes disabled, gets 403
- Finance stays read-only and owner-only board routes stay owner-only
- `GET` with no `status` is still published posts only
- The response still omits tokens, generation, scene prompts, and image object keys
- `dispatch.py` does not grow
- `write_blocked` still returns true for the LinkedIn paths

## Done when

- `python3 -m unittest test_linkedin_public test_board_public_api test_handler.TestPublicReadRoutes test_routes` in `backend/lambda/admin` passes
- `python3 -m ruff check` on the edited Python files passes
- `python3 scripts/check_file_length.py` and `python3 scripts/check_pii.py` pass
- The LinkedIn route assertions in `backend/infrastructure` pass

## Rollback

Revert the branch commit. The public posts route goes back to GET, and writes return 403 `not_allowlisted`.

## Open questions

None. DELETE archives. It does not remove the row.
