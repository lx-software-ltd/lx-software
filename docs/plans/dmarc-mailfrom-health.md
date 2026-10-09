# Plan: show custom MAIL FROM on the board mail health strip

**Status**: Draft
**Zone**: yellow

## Goal

The Mail header already reads SES identity health. Include the custom MAIL FROM domain and status so a missing or failed `mail.siutindei.com` envelope is visible next to DKIM.

## Non-goals

Changing SES, DNS, or which messages `own_sender_failing` reports.

## Files

- `backend/lambda/admin/board_mail.py`
- `backend/lambda/admin/test_board_mail.py`
- `apps/admin_web/src/lib/board/types.ts`
- `apps/admin_web/src/lib/mock/fixtures.ts`
- `apps/admin_web/src/components/board/BoardMailView.tsx`
- `docs/deployment/admin-website.md`

## Invariants this change preserves

Sending still follows `SiutindeiBoardMailSendingEnabled`. A `PENDING` MAIL FROM does not mark sending down. `FAILED` does. Health stays cached for 10 minutes and read errors stay on `errors`.

## Done when

`test_board_mail` passes. The mock Mail section shows a MAIL FROM badge for `mail.siutindei.com` `SUCCESS`.

## Rollback

Revert the commit. The strip returns to domain, DKIM, and production access.

## Open questions

None.
