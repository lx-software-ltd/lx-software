# Plan: Messages inbox review fixes

**Status**: Approved
**Zone**: red (`backend/infrastructure/lib/admin-data.ts`, one lifecycle rule), otherwise yellow

## Goal

Fix the faults found in the review of the Messages inbox before it is deployed.

- Approval cards for ad sets, boosts, Page posts and stories show their arguments again.
- A message is stored once, whichever path delivers it: webhook, echo, hourly catch-up, history import, or the board's own send.
- Imported history and old catch-up messages are stored as read and are not triaged.
- The hourly catch-up files each message in the customer's thread with the right direction and the stored timestamp format.
- Photos and files open from the Messages tab. WhatsApp media is fetched by media id.
- Staff tools and keys without `siutindei-pii` get an alias in place of a contact's name.
- **Connect WhatsApp** runs Meta's coexistence signup, and the board checks the number with Meta before it reports "connected".
- Organisation matching reads every prospect, keeps the prospect's stage when it is already past `replied`, and holds a reply addressed by number as well as by thread.

## Non-goals

- No new API route and no CSP change.
- No reply box in the Messages tab.
- No Mail filter. That is `docs/plans/board-messages-mail-filter.md`.
- Names inside message text are not masked. Mail has the same limit: only email addresses and phone numbers are replaced in free text.

## Files

- `backend/lambda/admin/board_meta_ingest.py`: one claim row per message id, thread fields move forward only, contact names kept until the thread exists, one thread write per webhook.
- `backend/lambda/admin/board_meta_inbox.py`: catch-up direction, customer and timestamp; aliases for names; media references; per-message error handling in the follow-up.
- `backend/lambda/admin/board_meta_attachments.py`: WhatsApp media by id, attachment index kept, fetch on first open.
- `backend/lambda/admin/board_meta_whatsapp.py`: number checked against the account, import lock, each import step recorded.
- `backend/lambda/admin/board_meta_triage.py`: full prospect index, stage guard, staff-disabled guard, note on a later message.
- `backend/lambda/admin/board_meta_profile.py` (new): display name for Page and Instagram threads.
- `backend/lambda/admin/board_routes_messages.py`, `board_tools_meta.py`, `board_policy.py`, `board_meta.py`, `board_routes.py`.
- `backend/lambda/admin/test_board_meta_inbox_fixes.py` (new) and `test_board_meta_inbox.py`.
- `apps/admin_web/src/components/board/BoardApprovalsList.tsx`, `BoardMessagesView.tsx`, `BoardMessagesConnections.tsx` (new), `ExecutiveBoardTab.tsx`, `hooks/useBoardMessages.ts`, `lib/board/metaSignup.ts` (new), `lib/mock/routes/messages.ts`, tests beside each.
- `apps/admin_web/src/lib/board/types.ts`, `lib/mock/fixtures.ts`: back to their `main` content.
- `backend/infrastructure/lib/admin-data.ts`: non-current versions under `board/meta-media/` expire after one day, so a photo is gone about 90 days after it arrived.
- `docs/architecture/executive-board.md`, `docs/architecture/security.md`, `docs/deployment/admin-website.md`.

## Invariants this change preserves

- The webhook does no Graph call and no model call.
- An organisation thread never gets an automatic reply.
- A key without `siutindei-pii` cannot read media, contact names, phone numbers, or the WhatsApp account ids.
- The owner-only route list in `board_public_api.py` is unchanged.
- No file grows past its ceiling in `scripts/file-length-allowlist.txt`.

## Done when

- `python3 -m unittest discover -p 'test_*.py'` passes in `backend/lambda/admin`, including the new file, which holds one test per review finding.
- `python3 -m ruff check backend/lambda scripts`, `python3 scripts/check-contracts.py`, `python3 scripts/check_file_length.py`, `python3 scripts/check_pii.py` and `python3 scripts/validate_agent_rules.py` pass.
- `npm run lint`, `npx tsc -b`, `npm run test:unit`, `npm run build` and `npm run test:e2e` pass in `apps/admin_web`.
- `npm test` and `npm run build` pass in `backend/infrastructure`.
- A recording on the mock console shows a photo opening from a thread, the WhatsApp import asking for confirmation, and an ad set approval showing its budget.

## Rollback

Revert the commits. Claim rows (`MID#…`) and name rows (`meta#names`) expire with the messages and are ignored by the older code.

## Open questions

- Whether Meta lets this app run the coexistence signup without Tech Provider enrolment (Route 0 in `docs/plans/board-messages-inbox.md`). Only a live attempt answers it.
- Whether Meta still serves media for messages that arrive through the history import. The board asks on first open and shows "not available" when Meta refuses.
