# Plan: clear a DMARC config gap when the finding is gone

**Status**: Done
**Zone**: yellow

## Goal

`dmarc:siutindei.com` stays under Unconfigured integrations after the last-24h DMARC finding has ended. Remove that gap on the next enabled evaluation, and show the live gap list on the daily review screen.

## Non-goals

Changing SES, DNS, or which messages `own_sender_failing` reports. Turning the DMARC check off does not wipe a gap. The morning digest keeps the list from compile time.

## Files

- `backend/lambda/admin/board_dmarc.py`
- `backend/lambda/admin/board_duties.py`
- `backend/lambda/admin/board_review.py`
- `backend/lambda/admin/board_routes.py`
- `backend/lambda/admin/test_board_dmarc.py`
- `backend/lambda/admin/test_board_duties.py`
- `backend/lambda/admin/test_board_review.py`
- `docs/architecture/executive-board.md`
- `docs/deployment/admin-website.md`

## Invariants this change preserves

Parsing stays on when the check is disabled. A disabled evaluation does not clear gaps. Non-`dmarc:` gaps stay. `own_sender_failing` still requires a both-fail, quarantine, or reject in the last 24 h of intake. A review read does not evaluate or write gaps. The stored digest is the compile-time list.

## Done when

`test_board_dmarc`, `test_board_duties`, and `test_board_review` pass. A `dmarc:siutindei.com` gap opened by a quarantined SES row is gone after that report ages out of the 24 h intake, and `GET /siu-tin-dei/board/review` no longer lists it while the stored snapshot still does.

## Rollback

Revert the commit. Gaps stay until the 40-day cache TTL.

## Open questions

None.
