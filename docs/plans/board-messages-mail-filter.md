# Plan: Mail filter on the Messages tab

**Status**: Draft
**Zone**: yellow

## Goal

The Messages tab in the admin console gets a Mail button next to All, WhatsApp, Facebook and Instagram. The owner reads email threads in the same list and the same reading pane as the other channels.

## Non-goals

- No backend, CDK, contract or public API change. The console reuses the existing `GET /mail`, `GET /mail/{threadId}` and `POST /mail/{threadId}/read` routes.
- The Mail tab stays. It keeps search, mailbox chips, archived threads, the masked view and the test email.
- No sending or replying from the Messages tab. A reply box is a later plan.
- No change to what staff tools or API keys can read.
- No split of Facebook into Messenger chats and Page comments. The Facebook button is the Messenger one.

## Decisions

The owner answered these on 18 November 2026.

1. **All includes mail.** The All filter lists mail threads and Meta threads together, newest first.
2. **The Messages badge counts unread mail.** It is unread Meta threads plus unread mail threads. The same unread email is therefore counted on Mail and on Messages, and reading it in either place clears both.
3. **The buttons are All, WhatsApp, Facebook, Instagram, Mail.** "Messenger" means the Facebook button.

## Design

1. The merge happens in the browser. A pure helper maps a mail thread and a Meta thread to one row shape: `{ kind, threadId, channel, title, snippet, lastMessageAt, unread }`. Rows are keyed `kind:threadId`, because mail and Meta thread ids come from different stores.
2. Rows sort by `Date.parse(lastMessageAt)`, newest first. A row with a date that does not parse sorts last. String sorting is not used, because the two stores write different timestamp formats.
3. The Mail filter shows mail rows only. The All filter shows both.
4. Archived mail is left out, the same as the default Mail tab view.
5. Opening a mail row loads the thread with `useBoardMailThread` and marks it read with `useBoardMailRead`. Opening a Meta row keeps today's behaviour.
6. The reading pane shows mail messages with the same card the Mail tab uses, so subject, sender, recipients and attachments look the same in both places. A link "Open in Mail" goes to the Mail tab with that thread selected.
7. The mail list is fetched only when the filter is Mail or All, so the other filters make no extra request.
8. The Messages badge is `unreadCount` from the messages status route plus `unreadMailCount` from the board overview. Both are already loaded on the board page.
9. The chosen filter and thread go in the URL (`?section=messages&channel=mail&thread=…`), so a reload or a shared link lands on the same thread.

## Files

- `apps/admin_web/src/lib/board/inbox.ts` (new): row type, the two mapping functions, merge and sort.
- `apps/admin_web/src/lib/board/inbox.test.ts` (new): mapping, sort order across both timestamp formats, unread flag, archived mail excluded, key collisions.
- `apps/admin_web/src/components/board/BoardMessagesView.tsx`: Mail button, merged list, branch on row kind for open and read, mail reading pane.
- `apps/admin_web/src/components/board/BoardMessagesView.test.tsx`: Mail filter lists mail threads, opening one calls the mail read endpoint, All shows both kinds, WhatsApp filter makes no mail request.
- `apps/admin_web/src/components/board/BoardMailView.tsx`: export the message card only. If the export pushes the file over a length ceiling, move the card to `BoardMailMessageCard.tsx`.
- `apps/admin_web/src/components/board/ExecutiveBoardTab.tsx`: pass the thread-open callback for "Open in Mail", and add unread mail to the Messages badge.
- A test for the badge (new, beside the helper that adds the two counts): the badge is the sum of both.
- `apps/admin_web/src/lib/mock/routes/messages.ts`: no change expected; the mock already serves mail fixtures.
- `docs/architecture/executive-board.md` and `docs/deployment/admin-website.md`: one sentence each on the Mail filter.

## Invariants this change preserves

- The owner console is the only place that shows unmasked mail. Staff tools and API keys keep their masked views, because no server code changes.
- Reading a thread in Messages and reading it in Mail mark the same thread read. There is one unread state per mail thread.
- The Mail tab unread badge keeps its meaning. The Messages badge adds the same number to its own.
- No new shared constants, so `contracts/*.json` is untouched.
- No file grows past its ceiling in `scripts/file-length-allowlist.txt`.

## Done when

- `npm run lint`, `npx tsc -b`, `npm run test:unit`, `npm run build` and `npm run test:e2e` pass in `apps/admin_web`.
- `python3 scripts/check_file_length.py` and `python3 scripts/check_pii.py` pass.
- On the mock (`npm run dev:mock`, port 5174), a recording shows: Mail filter lists the mail fixtures, opening one shows the message and clears its unread mark, the Mail tab shows the same thread as read, All shows mail and WhatsApp rows in date order, and a reload keeps the selected thread.

## Rollback

Revert the pull request. Nothing is stored and nothing is deployed outside the admin web bundle, so the Mail tab and the other channel filters are unaffected.

## Open questions

1. Should a reply box on the Messages tab come later, as its own plan? This plan leaves it out.

## Sequencing

After pull request #654 is merged. This plan depends on the Messages tab from #654, including its review fixes, and on nothing else. It is not implemented until the owner confirms it.
