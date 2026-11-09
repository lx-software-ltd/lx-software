# Plan: Board Meta insights defaults survive Meta's 2025 metric retirements

**Status**: Implemented
**Zone**: yellow

## Goal

Both board Insights reads fail on production, and neither failure is a permission problem:

- `meta_page_insights` → Graph 400 code 100 "The value must be a valid insights metric". Meta retired the `page_impressions*` family on 2025-11-15 (second wave 2026-06-15). The default `page_impressions,page_post_engagements` now fails as a whole because one bad metric rejects the request.
- `meta_ig_insights` → Graph 400 code 100 "Tried accessing nonexisting field (insights)". That is Meta's answer when the id is not an Instagram professional-account node for this token. `META_IG_USER_ID` on production (`1291672990695789`) is not the Graph `instagram_business_account.id` of the Page (those are 17-digit ids that start with 17841). Separately, the default metric `impressions` left IG Insights in 2025 and account-level metrics now need `metric_type`.

Fix the defaults and make the IG read resolve the linked account from the Page when the configured id is rejected, so the owner can correct the parameter at leisure without the board staying blind.

## Non-goals

No change to publishing, comments, DMs, WhatsApp, ads, or the Page-token exchange. No new CDK parameter. No change to `production.json` in this plan (the IG id correction is an owner action once the resolved id is known).

## Files

- `backend/lambda/admin/board_meta_token.py`: `linked_ig_user_id()` reads `GET /{page-id}?fields=instagram_business_account` with the Page token and caches the id per warm container.
- `backend/lambda/admin/board_meta.py`: Page default metric → `page_media_view,page_total_media_view_unique,page_post_engagements`; IG default metric → `reach,views,profile_views` with `metric_type=total_value`; on "nonexisting field" the IG read retries once with the Page-linked id and reports `resolvedFrom: "page"`. File does not grow.
- `backend/lambda/admin/test_board_wp2.py`, `test_board_t5.py`: fake Graph answers the `instagram_business_account` lookup; tests for both defaults and the fallback.
- `docs/deployment/admin-website.md`: note how to read the correct IG id.

## Invariants this change preserves

Token still travels only in the `Authorization` header. The configured `META_IG_USER_ID` is tried first; the fallback runs only on Meta's "nonexisting field" error and never for other errors. Reads stay `level: read`; no hold or approval path changes. `board_meta.py` stays at or under its allowance.

## Done when

`cd backend/lambda/admin && python3 -m unittest test_board_wp2 test_board_t5` passes. `python3 -m ruff check backend/lambda scripts` and `python3 scripts/check_file_length.py` pass. After deploy, a CMO chat `meta_page_insights` and `meta_ig_insights` return rows; the IG result shows `resolvedFrom: "page"` until the parameter is corrected.

## Rollback

Revert the commit. Defaults return to the retired metrics and the reads fail as before.

## Open questions

None. If the Page has no linked Instagram professional account, the fallback finds nothing and Meta's own error is re-raised unchanged.
