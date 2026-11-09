# Plan: Hashtags as a string, and deleting a published post

**Status**: Done
**Zone**: yellow (`backend/lambda/admin`, `apps/admin_web/src`)

## Goal

Two content-calendar fixes found during the 2026-11-09 launch sweep.

1. The `content_stage_items` tool schema declares `hashtags` as a string, but
   `upsert_item` iterated the value as if it were a list, so a caption such as
   `"#小天地 #赤柱"` was stored one character per tag (`["#", "小", "天", …]`).
   Every item staged by the content marketer since the tool shipped has these
   spelled-out tags. The owner PUT path silently ignored strings.
2. The board could publish to the Facebook Page but had no way to take a post
   down again. Twelve bad posts from 2026-11-06 had to be deleted by hand.

## Non-goals

- Changing the tool schema to a list. Staff models already send strings and the
  string form is the smaller prompt.
- Repairing existing rows. They were all vetoed on 2026-11-09.
- A staff-side delete tool. Deleting is owner-only; the seats veto instead.
- Deleting Instagram media. The Instagram Graph API has no delete endpoint for
  media, so the UI explains that and asks the owner to delete in the app.
- A new content status. `vetoed` already means "do not publish; keep the record".

## Files

- `backend/lambda/admin/board_content.py`: new `coerce_hashtags()` accepts a
  string (split on whitespace and commas) or a list, prefixes `#`, caps 40
  chars and 20 tags. Used by `upsert_item`, the owner PUT path and `caption_for`.
  New `delete_post()` calls `DELETE /{platformPostId}` for a published Facebook
  item, then sets `status=vetoed`, clears `platformPostId`, and records
  `deletedPostId` and `deletedAt`. Refuses manual, unpublished and Instagram
  items with a `ContentError`. The duplicated Instagram/story publish branches
  fold into `_publish_ig`, and `_save`/`_published_fields`/`_veto_lesson` share
  the write path so the file stays at its 866-line ceiling.
- `backend/lambda/admin/board_routes.py`: `POST /content/{id}/delete-post`
  audited as `BOARD_CONTENT_DELETE_POST`. The content route is now a
  dispatcher wrapped in one `ContentError`/`KeyError` handler.
- `backend/lambda/admin/board_public_api.py`: `delete-post` is owner-only; the
  full API key cannot call it.
- `apps/admin_web/src/lib/board/paths.ts`, `content.ts`, `types.ts`,
  `hooks/useBoardContent.ts`: `boardContentDeletePostPath`, `canDeletePost`,
  `deletedPostId`, and the `deletePost` mutation.
- `apps/admin_web/src/components/board/BoardContentSection.tsx`: `Delete post`
  button on a published, board-posted item with an inline confirm step; the
  header shows the live post id and, after deletion, the removed id.
- `apps/admin_web/src/lib/mock/routes/content.ts` and `fixtures.ts`: mock
  route and a published Facebook fixture (`cnt-fb-live`).
- Tests: `test_hashtags_string_is_split_not_spelled`,
  `test_delete_post_removes_facebook_post_and_refuses_instagram`, the
  `write_blocked` assertion, and `BoardContentSection.test.tsx`.
- `scripts/file-length-allowlist.txt`: `board_content.py` 875 → 866,
  `board_routes.py` 1532 → 1519, `types.ts` 1369 → 1361, `fixtures.ts`
  1285 → 1272.

## Invariants this change preserves

- List hashtag input behaves as before (prefix `#`, cap 40/20).
- An empty or missing value leaves the existing tags on update and stores `[]` on create.
- `publish()` still dedupes on caption hash and recovers from transient Graph errors.
- Only an owner JWT can delete; a hand-posted item (`platformPostId == "manual"`) is never sent to Graph.
- Content statuses stay within `contracts/board-staff.json`.

## Done when

`python3 -m unittest discover -p 'test_board*.py'`, `ruff check`,
`scripts/check_file_length.py`, and admin `npm run lint`, `npx tsc --noEmit`,
`npm run test:unit`, `npm run build` pass; the mock console shows the
confirm-then-delete flow.

## Rollback

Revert the commit. Deleted Facebook posts are not restorable.

## Open questions

None.
