# Plan: Assets list reads the index

**Status**: Done
**Zone**: yellow

## Goal

Opening Admin → Assets walks `lxsoftware-admin-records` fifty items at a time and keeps going until the scan cursor ends. `Limit` is applied before the `ASSET#` filter, and each page may also load every finance book and call S3 `HeadObject`. The browser chains those pages itself.

Serve the list from the existing `gsi1` index, newest first, fifty assets per request. Stamp `gsi1pk` / `gsi1sk` when an asset is confirmed or imported. Stop the browser from draining the cursor. Look up a deep-linked asset with `GetItem` on `GET /assets?key=`.

## Non-goals

A new DynamoDB index or a new HTTP route (both would touch the infrastructure zone). Virtualising the table. Server-side filename search. Changing `GET /records`.

## Files

- `backend/lambda/admin/assets.py`
- `backend/lambda/admin/dispatch.py`
- `backend/lambda/admin/finance_store.py`
- `backend/lambda/admin/test_board.py`
- `backend/lambda/admin/test_inbound_email_handler.py`
- `apps/admin_web/src/hooks/useAdminAssets.ts`
- `apps/admin_web/src/pages/AssetsPage.tsx`
- `apps/admin_web/src/pages/AssetsPage.test.tsx`
- `apps/admin_web/src/lib/mock/routes/admin.ts`
- `scripts/backfill-asset-index.py`

## Invariants this change preserves

Download, delete, and confirm keep the same key rules and status codes. `GET /assets` still returns `{ items, nextCursor }` for `ASSET#` / `META` rows, without `gsi1pk` or `gsi1sk`. An `inbound/{owner}/…` key still displays that owner when `house` was not stored. A deep link to a known asset still opens that row. Rows that never received index attributes stay off the list until `scripts/backfill-asset-index.py --apply` stamps them.

## Done when

`python3 -m unittest test_board.TestAssets test_inbound_email_handler.TestRecordInboundAssetMeta -v` in `backend/lambda/admin` passes. `npm run test:unit -- src/pages/AssetsPage.test.tsx` and `npm run lint` in `apps/admin_web` pass. `npm run dev:mock` shows the first fixture page without a second `/assets` request, and Load more appears only when `nextCursor` is set. `python3 -m ruff check backend/lambda scripts` passes.

## Rollback

Revert the commit. New rows written with `gsi1pk = ASSET` are unused by the old scan. The backfill only adds attributes, so leaving them in place is safe.

## Open questions

None. Filename filtering stays on the rows already loaded. Legacy uploads whose house lived only on a statement line pick that house up during the one-time backfill, not on each list request.
