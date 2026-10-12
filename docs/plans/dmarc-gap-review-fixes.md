# Plan: correct the DMARC gap review follow-ups

**Status**: Done
**Zone**: yellow

## Goal

Today's review screen should not drop compiled gaps when the cache read fails, should not rewrite a past day's list, should hide a `dmarc:` row a fresh summary no longer reports without deleting it, should keep one row per gap id, and should name the last-24h source IP with the most failures. The on-screen digest preview should match that list.

## Non-goals

A review read does not evaluate and does not write gaps. Turning the DMARC check off does not clear or hide a gap. The stored morning digest stays the compile-time copy.

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

Parsing stays on when the check is disabled. Non-`dmarc:` gaps stay. `own_sender_failing` still requires a both-fail, quarantine, or reject in the last 24 h of intake. A summary at the finding cap is not used to hide gaps.

## Done when

The new review and DMARC tests pass, including a past date, a failed gap read, a fresh empty summary, an older week row, and a week-heavy IP that is quiet today.

## Rollback

Revert the commit. The previous overlay behavior returns.

## Open questions

None.
