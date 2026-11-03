# Plan: Board Meta uses a Page access token on Page edges

**Status**: Implemented
**Zone**: yellow

## Goal

Make the board's `meta` tools work against the Siu Tin Dei Facebook Page
with the System User token the owner stored on 2026-11-03. The first live
reads after the Page and Instagram ids were deployed failed twice:

- `GET /{page-id}/feed` → Graph 400, code 190, subcode 2069032,
  "A Page access token is required for this call for the new Pages
  experience." Pages on the new Pages experience refuse user and System
  User tokens on Page edges.
- `GET /{page-id}/insights?metric=page_impressions,page_engaged_users` →
  Graph 400, code 100, "The value must be a valid insights metric."
  `page_engaged_users` was removed from Page Insights.

## Non-goals

- Instagram, WhatsApp and Marketing API calls keep using the System User
  token unchanged.
- No new secret or CDK parameter. The Page token is derived at run time
  from the existing `…-board-meta-token` secret.
- No change to the Instagram insights default metric (unverified).

## Files

- `backend/lambda/admin/board_meta_token.py` (new, under the 500-line
  ceiling): System User / app-secret caches and the Page-token exchange.
  `page_token()` calls `GET /{page-id}?fields=access_token` once per warm
  container. `token_for()` picks the Page token for any path whose first
  segment is the Page id or a Page-prefixed object id (`{page-id}_…`).
- `backend/lambda/admin/board_meta.py`: `graph()` uses `token_for`; Page
  Insights default metric becomes `page_impressions,page_post_engagements`.
  File-length allowance lowered from 1302 to 1262.
- `backend/lambda/admin/test_board_t5.py`: `FakeGraph` answers the token
  exchange and records it in `exchanges`.
- `backend/lambda/admin/test_board_wp2.py`: tests for the exchange, its
  caching, the fallback when the exchange fails, and the new default metric.
- `docs/deployment/admin-website.md`: note that the System User must be
  assigned to the Page so the exchange succeeds.
- `scripts/file-length-allowlist.txt`: `board_meta.py` 1302 → 1262.

## Invariants this change preserves

- The token still travels only in the `Authorization` header.
- Non-Page paths (`me`, `act_*`, WhatsApp phone ids, IG ids) are untouched.
- When the exchange fails the call falls back to the System User token so
  Meta's own error reaches the persona instead of a synthetic one.

## Done when

- `cd backend/lambda/admin && python3 -m unittest test_board_wp2 test_board_t5 test_board_followups test_board_content -v` passes.
- `python3 scripts/check_file_length.py` exits 0.
- A CMO chat `meta_page_insights` or `meta_list_comments` call on
  production returns rows instead of code 190 / code 100.

## Rollback

Revert the commit. No data migration.

## Open questions

- Whether the System User has been assigned the Page in Business
  Manager with the `MANAGE` / `CREATE_CONTENT` tasks. If not, the exchange
  returns no `access_token` and the owner has to add the assignment.
