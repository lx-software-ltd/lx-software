# Plan: Assets list reads the index

**Status**: Done
**Zone**: yellow. The shell guard that blocks `scripts/backfill-asset-index.py --apply` is red (`.cursor/hooks/`) and was approved with the request to fix the review findings.

## Goal

Serve Admin → Assets from the existing `gsi1` index, newest first, fifty assets per request. Stamp `gsi1pk` / `gsi1sk` when an asset is confirmed or imported. The follow-up from review keeps that list correct:

- The one-time backfill is documented where operators look, reads S3 `LastModified` when `uploadedAt` is missing, does not store the 1970 placeholder as the upload time, and does not recreate a deleted row.
- A dry run reports `pending`. `updated` counts rows actually written.
- `GET /assets?q=` searches file name, object key, owner key, and owner label across the index, not only the loaded page.
- A deep-linked row stays on the page after it is closed. An `ASSET#…` link closes on the first click. A lookup error other than 404 leaves the link in place.
- A cursor from the old table scan returns 400, and the page reloads the first page.
- An import stamps the sort key from the row's existing `uploadedAt`.
- `GET /records` and `/public/records` omit `gsi1pk` and `gsi1sk`.
- The agent shell blocks `backfill-asset-index.py --apply`.

## Non-goals

A new DynamoDB index or a new HTTP route. Virtualising the table. Changing download, delete, or confirm key rules.

## Files

- `backend/lambda/admin/assets.py`
- `backend/lambda/admin/asset_backfill.py`
- `backend/lambda/admin/finance_store.py`
- `backend/lambda/admin/test_board.py`
- `apps/admin_web/src/hooks/useAdminAssets.ts`
- `apps/admin_web/src/pages/AssetsPage.tsx`
- `apps/admin_web/src/pages/AssetsPage.test.tsx`
- `apps/admin_web/src/lib/mock/routes/admin.ts`
- `scripts/backfill-asset-index.py`
- `docs/deployment/admin-website.md`
- `.cursor/rules/scripts.mdc`
- `.cursor/hooks/guard_shell.py`
- `scripts/test_agent_hooks.py`

## Invariants this change preserves

Download, delete, and confirm keep the same key rules and status codes. `GET /assets` still returns `{ items, nextCursor }` for `ASSET#` / `META` rows, without `gsi1pk` or `gsi1sk`. An `inbound/{owner}/…` key still displays that owner when `house` was not stored. A deep link to a known asset still opens that row. Rows without index attributes stay off the list until `scripts/backfill-asset-index.py --apply`.

## Done when

`python3 -m unittest test_board.TestAssets test_inbound_email_handler.TestRecordInboundAssetMeta -v` in `backend/lambda/admin` passes. `npm run test:unit -- src/pages/AssetsPage.test.tsx` and `npm run lint` in `apps/admin_web` pass. `python3 -m unittest scripts/test_agent_hooks.py` passes. `python3 -m ruff check backend/lambda scripts` passes. `npm run dev:mock` shows a filter that narrows the fixture list, and closing a deep-linked row takes one click.

## Rollback

Revert the commit. New rows written with `gsi1pk = ASSET` are unused by the old scan. The backfill only adds attributes, so leaving them in place is safe.

## Open questions

None.
