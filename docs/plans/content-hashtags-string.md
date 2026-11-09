# Plan: Accept hashtags as a string in content items

**Status**: Done
**Zone**: yellow (`backend/lambda/admin`)

## Goal

The `content_stage_items` tool schema declares `hashtags` as a string, but
`upsert_item` iterated the value as if it were a list, so a caption such as
`"#小天地 #赤柱"` was stored one character per tag (`["#", "小", "天", …]`).
Every item staged by the content marketer since the tool shipped has these
spelled-out tags. The owner PUT path silently ignored strings.

## Non-goals

- Changing the tool schema to a list. Staff models already send strings and the
  string form is the smaller prompt.
- Repairing existing rows. They were all vetoed on 2026-11-09.

## Files

- `backend/lambda/admin/board_content.py`: new `coerce_hashtags()` accepts a
  string (split on whitespace and commas) or a list, prefixes `#`, caps 40
  chars and 20 tags. Used by `upsert_item`, the owner PUT path and `caption_for`.
- `backend/lambda/admin/test_board_content.py`: `test_hashtags_string_is_split_not_spelled`.
- `scripts/file-length-allowlist.txt`: `board_content.py` lowered 875 → 866.

## Invariants this change preserves

- List input behaves as before (prefix `#`, cap 40/20).
- An empty or missing value leaves the existing tags on update and stores `[]` on create.

## Done when

`python3 -m unittest test_board_content test_board_tools`, `ruff check`, and
`scripts/check_file_length.py` pass.

## Rollback

Revert the commit.

## Open questions

None.
