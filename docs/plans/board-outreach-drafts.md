# Plan: Outreach drafts the owner can read, and four board defects found in the 16 Nov sweep

**Status**: Done
**Zone**: yellow (`backend/lambda/admin/board_tools_outreach.py`, `board_tools_content.py`, `board_staff.py`, `board_prospects.py`)

## Goal

The owner asked the board to start emailing approved Stanley organisations and to see each email as a draft before it leaves. The sweep on 2026-11-16 found that the board could not do that, for five separate reasons. This change fixes each one.

1. An `outreach_send` hold or approval shows only a prospect id. The owner cannot read the email. The op gets a `preview` in the same shape as a mail preview (`kind: "email"`, from, to, subject, text), so the existing card on Approvals and Holds renders the sequence step as it would be sent. The recipient line is the organisation name and its `contact#N` alias, not the address.
2. `outreach_score_prospect` fetches a homepage, calls the desk model, then crawls up to four contact pages, all inside the default 10 second op timeout. It timed out on most calls. Each timeout is an error, and ten errors in an hour trip `tool:outreach`, which then blocked every upsert for a week (9 to 16 Nov). The op moves to the slow timeout.
3. Real, open Stanley businesses scored 0 and stayed `discovered`. Two things in the scoring call push toward zero, and this change removes both. The prompt showed `{"score":0,"note":""}` as the reply shape. A homepage our crawler could not fetch arrived as an empty string, which the rubric's "−50 if the website or listing is dead" line then applied to a start of 50. The prompt now names the range and the starting point, and an unread homepage is labelled as unread. Which of the two caused the zeros was not measured against the production model.
4. `content_publish` also ran under the 10 second timeout. Instagram needs two Graph calls and a media fetch on Meta's side. Seven of ten Instagram publishes between 11 and 15 Nov failed with "content_publish timed out after 10s" and their rows stayed `scheduled` with a failed hold. The op moves to the slow timeout.
5. `_confirmed_lessons` read only the newest 12 lesson rows for a seat and filtered for `confirmed` afterwards. A bulk veto on 9 Nov added 36 unconfirmed rows for `content-marketer`, which pushed all five of its confirmed lessons out of the window, so none reached the prompt. The function now reads a deeper window and keeps the newest 12 confirmed ones.

## Non-goals

No change to who may send, to the hold length, to the tool matrix, or to `write_blocked`. No new op and no contract change. No retry of the stuck Instagram rows. No change to the sequence copy in code: the founder's sequence is stored per board through `PUT /sequences/{type}`. Tool timeouts still count as breaker errors.

## Files

- `backend/lambda/admin/board_tools_outreach.py`: `_outreach_send_preview`, wired as `preview=` on `outreach_send`; `timeout_seconds` on `outreach_score_prospect`.
- `backend/lambda/admin/board_tools_content.py`: `timeout_seconds` on `content_publish`.
- `backend/lambda/admin/board_staff.py`: `_confirmed_lessons` window. Same line count; the file sits at its allowance.
- `backend/lambda/admin/board_prospects.py`: scoring prompt and the unfetched-homepage label. Same line count; the file sits at its allowance.
- `backend/lambda/admin/test_board_outreach.py`, `test_board_prospects.py`, `test_board_lessons.py`, `test_board_content.py`: tests, written first.
- `docs/architecture/executive-board.md`: the outreach preview, the two slow ops, and the lesson window.

## Invariants this change preserves

Holds and Approvals stay separate lists. The preview is read-only and sends nothing. It is built when the hold or approval is created, so a later edit to the sequence changes what is sent but not the stored preview; the send path still renders from the current sequence. The preview stores no prospect address: `/holds` and `/approvals` are readable by API keys without the `siutindei-pii` scope, and a vetoed hold's preview is passed to the desk model that drafts the lesson. `outreach_send` still refuses on every existing condition (stage, contact, cap, breaker, identity). At most 12 lessons reach a seat prompt. `board_staff.py`, `board_prospects.py` and `board_outreach.py` do not grow.

## Done when

`python3 -m unittest test_board_outreach test_board_prospects test_board_lessons test_board_content -v` passes in `backend/lambda/admin`, then the whole `python3 -m unittest discover -p 'test_*.py'` run. `python3 -m ruff check backend/lambda scripts` and `python3 scripts/check_file_length.py` pass.

## Rollback

Revert the commits. Stored holds that carry an email preview still render: the web card already handles that shape.

## Open questions

A tool timeout still counts toward the tool breaker. Whether a timeout should count is a separate decision. Scoring can still pass 25 seconds on a slow site: each page fetch may take 10 seconds and the model call 20. The worker thread keeps running after the timeout and still saves the score and the contact, so the cost of a late finish is one error row, not lost work.

The owner may want the real address on the card. That needs the hold and approval previews masked for keys without the PII scope first, which the mail previews do not have today either.
