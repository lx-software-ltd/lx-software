# Plan: tidy the DMARC gap split

**Status**: Done
**Zone**: yellow

## Goal

The review GET should read the snapshot and compile in the route, using one value from `board_hk.today_hkt()` for the default date and the overlay. Gap modules should call the gap cache directly, and domain matching should be a public function. Tests should call the new modules.

## Non-goals

No change to which findings open a gap, when a gap clears, or what a review read writes. Existing callers of `board_duties.note_config_gap`, `list_config_gaps`, and `clear_config_gap` stay on those names.

## Files

- `backend/lambda/admin/board_routes.py`
- `backend/lambda/admin/board_review_gaps.py`
- `backend/lambda/admin/board_dmarc.py`
- `backend/lambda/admin/board_dmarc_gaps.py`
- `backend/lambda/admin/test_board_review.py`
- `backend/lambda/admin/test_board_dmarc_gaps.py`
- `backend/lambda/admin/test_board_config_gaps.py`
- `scripts/file-length-allowlist.txt`

## Invariants this change preserves

A review read does not evaluate or write gaps. A failed gap read keeps the compiled list. A past date stays compiled. Turning the DMARC check off does not clear or hide a gap.

## Done when

The new module tests pass, the review tests pass, and `python3 scripts/check_file_length.py` exits 0.

## Rollback

Revert the commit. The review GET goes back to `board_review_gaps.for_get`.

## Open questions

None.
