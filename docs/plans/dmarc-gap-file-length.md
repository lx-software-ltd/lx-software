# Plan: keep the DMARC gap files on the length ratchet

**Status**: Done
**Zone**: yellow

## Goal

The file-length ratchet rejects this branch because four already-over-ceiling modules grew. Move the new gap-list code into modules under the 500-line ceiling and lower the allowances for the files that shrink. Behavior stays the same.

## Non-goals

No change to which findings open a gap, when a gap clears, or what a review read writes. The allowlist is not raised.

## Files

- `backend/lambda/admin/board_dmarc_gaps.py` (new)
- `backend/lambda/admin/board_config_gaps.py` (new)
- `backend/lambda/admin/board_review_gaps.py` (new)
- `backend/lambda/admin/board_dmarc.py`
- `backend/lambda/admin/board_duties.py`
- `backend/lambda/admin/board_review.py`
- `backend/lambda/admin/board_routes.py`
- `scripts/file-length-allowlist.txt`
- `docs/architecture/executive-board.md`

## Invariants this change preserves

`board_duties.note_config_gap`, `list_config_gaps`, and `clear_config_gap` stay the public names. A review GET still overlays only today. A failed gap read still keeps the compiled list. Disabled evaluation still does not clear gaps.

## Done when

`python3 scripts/check_file_length.py` exits 0, and the existing DMARC, duty, and review unit tests pass.

## Rollback

Revert the commit. The gap logic returns to the four larger modules.

## Open questions

None.
