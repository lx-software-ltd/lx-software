# Plan: Board inbox for Facebook, Instagram and WhatsApp messages

**Status**: Draft. Awaiting review by a second agent. No code is written until that review approves.
**Zone**: red and yellow. The owner approved the red parts in chat on 18 Nov 2026. Each red edit is listed under Files so the reviewer can confirm the scope.

## Goal

The board sees Facebook Page, Instagram and WhatsApp conversations the way it sees email: every message in both directions, with the sender, the full text and the attachments, readable by the owner in the console and by staff through tools.

The first use is the Stanley outreach. Organisations answer the founder's WhatsApp message with a timetable, prices and photos. Today nobody on the board can read those answers.

## Decisions already taken by the owner

1. The WhatsApp number is the Siu Tin Dei WhatsApp Business app number. It is used for business only.
2. WhatsApp keeps running on the phone and is mirrored to the board (Meta "coexistence"). The number does not move to the API.
3. Staff draft replies. Every reply to an organisation waits for the owner's approval. Nothing is sent automatically.
4. Red-zone edits in this plan are approved.

## Non-goals

- Resuming Facebook or Instagram posting. The pause of 16 Nov stays in force and this plan does not touch publishing.
- Sending WhatsApp, Messenger or Instagram messages without an approval.
- WhatsApp group chats, broadcast lists, calls and status updates. Meta does not mirror them.
- Delivery and read receipts.
- Moving the WhatsApp number off the phone.
- A second personal-data scope. The existing `siutindei-pii` scope decides who reads unmasked text.

## Current state on `main`

| Area | Email | Facebook Page | Instagram | WhatsApp |
| --- | --- | --- | --- | --- |
| Inbound stored | Full text | Masked text only | Masked text only | Masked text only, and only if a number is on the Cloud API (none is) |
| Outbound stored | Yes | No | No | No |
| Sender name | Yes | No | No | No |
| Attachments | Text parts kept | Dropped | Dropped | Dropped |
| Thread history tool | `mail_get_thread` | None | None | None |
| List tool | `mail_list_threads` | `meta_list_dms` | None (stored, never listed) | `meta_list_whatsapp` |
| Console view | Mail tab | None | None | None |
| Key read | `GET /mail` masked without `siutindei-pii` | None | None | None |

Findings that shape the work:

- The webhook exists at `/webhooks/meta/siutindei` and checks `X-Hub-Signature-256`. Its GET handshake compares against the stack parameter `SiutindeiBoardMetaVerifyToken`, which defaults to blank and is not passed by Deploy Backend. Unless someone set it by hand, Meta cannot subscribe.
- `board_meta._store_inbound` runs triage inline. For an unknown sender `board_triage.classify_text` makes a model call with a 12-second timeout on the webhook request. Meta expects an answer within seconds and unsubscribes an endpoint that keeps failing.
- `board_store.list_meta_messages` has no caller. No tool or route returns a thread's history.
- `board_meta._iter_inbound` skips `is_echo` messages and reads only `text`. Page feed comment payloads carry `comment_id`, and the code reads `id`, so a Page comment is stored under a random id.
- Every inbound Meta message opens a "Reply to inbound message" task, and an escalation calls the reply op with the `ack_escalation` template. For an organisation answering the founder this is noise and can raise an unwanted approval.
- `board_meta.status_summary` is not exposed. Nobody can see whether Meta is delivering.
- `board_meta.py`, `board_routes.py`, `board_store.py` and `board_triage.py` are on the file-length allowlist and may not grow. New code goes into new modules.
- Console routes under `/siu-tin-dei/board` are registered one by one in `admin-api-routes.ts`. The public API uses `{proxy+}`.
- The console CSP is `script-src 'self'`. Meta's Embedded Signup needs the Facebook JavaScript SDK.

## Owner setup (Step 1)

Written as an operator runbook. Menu names follow Meta's documentation of November 2026 and may differ slightly. `<admin-api>` is the admin HTTP API host.

### Part A. Verify token

The owner chose the GitHub secret over a CloudFormation console edit.

1. Generate a random string of 40 or more letters and digits in a password manager. Keep it there.
2. GitHub, this repository, Settings, Environments, `production`, Add environment secret. Name `SIUTINDEI_BOARD_META_VERIFY_TOKEN`. Value is the string from step 1. Save. Do not put it in `params/*.json` or in chat.
3. After pull request 1 (Deploy Backend wiring) is merged: Actions, Deploy Backend, Run workflow, branch `main`. Wait until it is green. Merging the wiring pull request does not run Deploy Backend by itself (the workflow path filter is `backend/**` and `contracts/**` only).
4. Check: open `https://<admin-api>/webhooks/meta/siutindei?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=123` in a private window. The page shows `123`. A page that shows `forbidden` means the token is not deployed. The secret can be created before pull request 1 merges; it does nothing until that deploy.

### Part B. Facebook Page and Instagram

1. developers.facebook.com, My Apps, the Siu Tin Dei app. Confirm the app mode switch reads **Live**.
2. App settings, Basic: privacy policy URL, app icon and category are filled in. Meta refuses Live mode and App Review without them.
3. Add the **Messenger** product if it is missing. Messenger, Settings (or Messenger API Settings), Configure webhooks: Callback URL `https://<admin-api>/webhooks/meta/siutindei`, Verify token from Part A, Verify and save.
4. Same screen, Generate access tokens or Pages: add the Siu Tin Dei Page. Next to the Page, Add subscriptions: tick `messages`, `message_echoes`, `messaging_postbacks`, `message_reactions` and `feed`.
5. Add the **Instagram** product if it is missing (Instagram API with Facebook Login). Under its webhooks section use the same Callback URL and Verify token. Subscribe `messages`, `messaging_postbacks`, `message_reactions` and `comments`.
6. business.facebook.com, Settings, Users, System users, the board's system user. Assigned assets: the Page with full control, the Instagram account, and the app.
7. Same system user, Generate token only if step 8 shows a missing permission. Permissions needed: `pages_show_list`, `pages_manage_metadata`, `pages_messaging`, `pages_read_engagement`, `pages_read_user_content`, `business_management`, `instagram_basic`, `instagram_manage_messages`, `instagram_manage_comments`. A new token replaces the value of the board Meta token secret in AWS Secrets Manager.
8. developers.facebook.com/tools/debug/accesstoken: paste the current token and compare the listed permissions with step 7. Do not paste the token anywhere else.
9. On the phone, Instagram app for the business account: Settings, Messages and story replies, Message controls, Connected tools, turn on **Allow access to messages**.
10. Meta Business Suite, Settings, Business apps (or Page settings, Advanced messaging): the Siu Tin Dei app is listed as connected to the Page.
11. Test with a person who has no role on the Meta app: one message to the Page in Messenger, one direct message to the Instagram account, one comment on a Page post. Then reply to each from Business Suite.
12. Tell the agent the time of the test. The agent reads the store and confirms six items arrived (three inbound, three outbound).
13. If the tester's messages do not arrive but the owner's own do, the app has Standard Access only. Request Advanced Access for `pages_messaging`, `instagram_manage_messages` and `pages_read_engagement` through App Review. Business verification (Part C step 2) comes first.

### Part C. WhatsApp coexistence

Meta allows coexistence onboarding only through an app that is a **Tech Provider** or through a **Solution Partner**. The owner chooses a route at step 1.

1. Choose the route.
   - Route 1, own Tech Provider. The existing Meta app enrols. No third party sees the messages, the existing webhook and signature check are reused, and there is no monthly fee. It needs business verification and an App Review with two screen recordings.
   - Route 2, Solution Partner. A partner onboards the number in a day or two. Messages pass through the partner, the partner charges a fee, and the webhook authentication differs from Meta's. This is the fallback if Route 1 stalls.
2. Business verification: business.facebook.com, Settings, Security Centre, Start verification. Legal name, address, phone, website and a business registration document. Meta takes from a few days to two weeks.
3. Route 1: App Dashboard, Use cases, add or customise **WhatsApp**, then Tech Provider onboarding. Follow its checklist. App Review asks for Advanced Access to `whatsapp_business_messaging` and `whatsapp_business_management`, with one recording of a message being sent and one of a template being created. The agent prepares the written answers.
4. Update the WhatsApp Business app on the phone to the current version (2.24.17 is the minimum).
5. App Dashboard, WhatsApp, Configuration: same Callback URL and Verify token. Subscribe `messages`, `smb_message_echoes`, `history`, `smb_app_state_sync` and `account_update`.
6. Wait for pull request 4 to deploy. Console, Executive Board, Messages, **Connect WhatsApp**. In the Meta window choose "Connect your existing WhatsApp Business app", enter the number, scan the QR code with the phone, and choose **share chat history** when asked.
7. Keep the phone unlocked with the WhatsApp Business app open until the console reports the history import complete. The import must start within 24 hours of step 6 and cannot be repeated.
8. Afterwards open the WhatsApp Business app at least once every 14 days. Meta disconnects a number whose phone stays inactive.

Side effects Meta applies to a coexistence number: disappearing messages, view-once media and live location are turned off; broadcast lists stop working; group chats are not mirrored; linked devices are unlinked once and can be linked again (WhatsApp for Windows and Wear OS are not supported). Messages typed on the phone stay free. Messages the board sends through the API follow Meta's API pricing.

### Part D. What the owner can start today

Part A steps 1 and 2 (create the GitHub secret), Part B steps 1 to 10, Part C steps 1, 2 and 4. Creating the secret does not depend on code. Deploying it does (Part A step 3).

## Design

### Storage

- Keep the existing keys (`BOARD#<b>#meta#threads` and `BOARD#<b>#meta#thread#<id>`) and the 90-day TTL.
- A message row gains `direction` (`in` or `out`), `text`, `senderName`, `source` (`webhook`, `echo`, `history`, `backfill`, `board`), `attachments` and `replyTo`. Rows written before this change keep `textMasked`, and readers fall back to it.
- A thread row gains `displayName`, `phone` (WhatsApp), `handle` (Instagram), `prospectId`, `lastOutboundAt`, `lastDirection` and `unreadCount`.
- Text is stored as received and masked at read, the same model `board_mail.py` uses. Staff tools and keys without `siutindei-pii` see `contact#N` and `phone#N` aliases. The owner's console session sees the real text. This replaces mask-at-ingest for Meta rows and is called out under Open questions.
- Attachments are fetched by an asynchronous job, never by the webhook. Bytes go to the assets bucket under `board/meta-media/<threadId>/<messageId>/<n>`. The row keeps kind, MIME type, size, SHA-256 and key. The console reads a 15-minute presigned URL. A lifecycle rule expires that prefix after 90 days, current and non-current versions.
- Limits are added to `contracts/board-tools.json`: `metaMessageTextMax` 8000, `metaMediaMaxBytes` 16777216, `metaMediaPerMessageMax` 10, `metaThreadListMax` 50, `metaThreadMessagesMax` 100, `metaBackfillThreadsPerRun` 25.

### Ingest

- New module `board_meta_ingest.py` parses a webhook payload into normalised messages. `board_meta.ingest_webhook` delegates to it and shrinks.
- Messenger and Instagram: inbound `messages`; outbound `message_echoes` and Instagram's own-message deliveries stored as `out`; attachments of type image, audio, video, file, reel and story reply; sender name from `GET /{psid}?fields=name` (Instagram `name,username`) where Meta returns it, cached on the thread.
- Comments: read `comment_id`, `post_id` and `parent_id` from Page feed payloads, and `id` and `text` from Instagram payloads.
- WhatsApp: `messages` (text, image, document, audio, video, sticker, location, contacts, reaction, edit, revoke); `smb_message_echoes` as `out`; `history` in its three phases; `smb_app_state_sync` for contact names; `account_update` raises an owner alert on disconnect. A payload that identifies a user by business-scoped id without a phone number is stored under that id and joined to the phone thread when a later payload carries both.
- The webhook stores rows and returns. Triage and media download move to one `board_async.invoke_async` call per request (`internal: board_meta_after_ingest`), with a synchronous fallback only when the invoke fails.
- Each accepted delivery writes `lastWebhookAt` per channel so the status view can show whether Meta is delivering.

### Backfill and reconciliation

- The hourly `board_cache_refresh` event also runs `board_meta_inbox.backfill`: `GET /{page-id}/conversations` for `messenger` and `instagram`, newest first, capped by `metaBackfillThreadsPerRun`, inserting messages not yet stored. This covers the past and any webhook gap. No new schedule.
- WhatsApp has no conversation read. Its past comes only from the one-off history import, and its gaps are reported by the status view.

### Staff tools

- `meta_list_threads` (read): channel filter `page`, `instagram`, `whatsapp` or `all`; unread only; returns masked name, last text, direction, counts and `prospectId`.
- `meta_get_thread` (read): masked history, oldest first, with attachment descriptions.
- `meta_list_dms` and `meta_list_whatsapp` stay and become thin wrappers so existing prompts keep working.
- `meta_reply_dm`, `meta_reply_whatsapp` and `meta_reply_comment` store the sent message as `out` when an approval executes.
- The context pack prints unread per channel and names the two new tools.
- Tool levels do not change. The registry snapshot test and `contracts/board-tools.json` are updated.

### Console and key reads

- New tab **Messages** beside Mail: thread list with channel filter and unread badge, thread view with both directions, attachments, the matched organisation, Mark read, and a status panel (token permissions, subscribed fields, last delivery per channel, WhatsApp connection state).
- Routes: `GET /siu-tin-dei/board/messages`, `GET /messages/status`, `GET /messages/{threadId}`, `POST /messages/{threadId}/read`, `GET /messages/{threadId}/media/{n}`, `POST /messages/connect/page` (subscribes the Page with the required fields), `POST /messages/whatsapp/connect`, `POST /messages/whatsapp/sync`.
- Public API: the same GET routes under the board scope, masked without `siutindei-pii`; media is refused without it. The three `connect` and `sync` POSTs join the owner-only list in `write_blocked`.
- The overview gains `unreadMessageCount`.

### WhatsApp connection

- Parameters `SiutindeiBoardMetaWaPhoneNumberId` and `SiutindeiBoardMetaWabaId` are set in `params/production.json` after onboarding returns them.
- **Connect WhatsApp** runs Meta's Embedded Signup with `featureType: "whatsapp_business_app_onboarding"`. The console CSP gains `https://connect.facebook.net` in `script-src` and `https://www.facebook.com` in `frame-src`, only for this purpose.
- `POST /messages/whatsapp/connect` exchanges the returned code, records the WABA and phone ids, and subscribes the app to the WABA.
- `POST /messages/whatsapp/sync` calls `POST /{phone-number-id}/smb_app_data` with `smb_app_state_sync`, then `history`. It refuses a second run and records Meta's answer, including error `2593109` when history sharing was declined.
- Route 2 replaces Embedded Signup with the partner's onboarding link and adds the partner's webhook authentication. That variant gets its own plan if chosen.

### Staff behaviour

- A sender is matched to a prospect by phone (`board_prospects.e164_phone`), then by Page or Instagram id recorded on the prospect. A match sets `prospectId` on the thread and marks the prospect `replied`, as `board_outreach.maybe_handle_reply` does for mail.
- For a matched organisation thread: no generic reply task and no `ack_escalation`. One task per thread, "Put the schedule from <organisation> into the catalog", goes to the catalog seat with the thread id. Later messages append to it.
- A reply to a matched organisation is always an Approval, whatever the tool level or allow-list. The approval card shows the last messages and the draft.
- Approving a WhatsApp draft offers two actions: send through the API when the 24-hour window is open, or open WhatsApp on the phone with the text filled in. A phone send returns through `smb_message_echoes`, so the thread stays complete either way.
- Page and Instagram replies outside Meta's 24-hour window are refused by Meta. The card then links to the conversation in Business Suite.
- Photos of timetables: an asynchronous job transcribes each image once and stores the text on the message, so staff can read a timetable they cannot see. It runs only for matched organisation threads.
- Unmatched threads keep today's routing, with the reply still landing in Approvals unless the recipient is on the allow-list.

## Files

Pull request 1. Verify token in Deploy Backend (red).
- `.github/workflows/deploy-backend.yml`: pass `SiutindeiBoardMetaVerifyToken` from the `production` environment secret `SIUTINDEI_BOARD_META_VERIFY_TOKEN` only when it is non-empty, so a missing secret never blanks a set value. Helper: `scripts/deploy/cdk-params.sh` `cdk_append_nonempty_param`.
- `docs/deployment/admin-website.md` and `docs/deployment/setup.md`: the secret, the handshake check, and the Run workflow step.

Pull request 2. Inbox backend and staff tools (yellow, plus contracts).
- New: `backend/lambda/admin/board_meta_ingest.py`, `board_meta_inbox.py`, `board_meta_media.py`, `test_board_meta_ingest.py`, `test_board_meta_inbox.py`.
- Edit without growth: `board_meta.py`, `board_store.py` (helpers move to a new `board_store_meta.py` if needed), `board_tools_meta.py`, `board_context.py`, `dispatch.py` (internal event), `test_board_tools.py` (registry snapshot).
- Red: `contracts/board-tools.json` (limits and two ops), then `python3 scripts/sync-contracts.py`.
- Docs: `docs/architecture/executive-board.md` section 6.2, `docs/architecture/security.md`.

Pull request 3. Console tab, routes and key reads (yellow, plus red route registration).
- New: `backend/lambda/admin/board_routes_messages.py`, `test_board_routes_messages.py`, `apps/admin_web/src/components/board/BoardMessagesView.tsx`, `apps/admin_web/src/hooks/useBoardMessages.ts`, their tests, and mock fixtures under `apps/admin_web/src/lib/mock/`.
- Edit: `board_routes.py` (delegation only), `ExecutiveBoardTab.tsx`, `apps/admin_web/src/lib/board/paths.ts`, `apps/admin_web/e2e` smoke.
- Red: `backend/infrastructure/lib/admin-api-routes.ts` (eight routes), `backend/infrastructure/lib/admin-data.ts` (lifecycle rule), `board_public_api.py` (`write_blocked` entries and message masking), and the infrastructure tests.
- Docs: `docs/deployment/admin-website.md`.

Pull request 4. WhatsApp coexistence (yellow and red).
- New: `backend/lambda/admin/board_meta_whatsapp.py`, `test_board_meta_whatsapp.py`, `apps/admin_web/src/components/board/BoardWhatsAppConnect.tsx`.
- Red: `backend/infrastructure/lib/lxsoftware-admin-web-stack.ts` (CSP), `backend/infrastructure/params/production.json` (two ids, in a follow-up commit after onboarding), infrastructure tests.
- Docs: `docs/deployment/admin-website.md` Board Meta section, replacing the current one-line coexistence step.

Pull request 5. Staff behaviour (yellow).
- New: `backend/lambda/admin/board_meta_triage.py`, `test_board_meta_triage.py`.
- Edit without growth: `board_triage.py` (`on_meta_event` delegates), `board_policy.py` (organisation threads always propose), the approval card component, `contracts/board-staff.json` only if a routing constant is needed.

## Invariants this change preserves

- Approvals stay with the owner. No reply to an organisation is sent without one.
- The webhook rejects a POST without a valid `X-Hub-Signature-256` and a GET without the verify token. A blank token keeps the handshake rejected.
- The webhook request does no model call, no Graph call and no media download.
- Staff and keys without `siutindei-pii` see aliases, never a name, number or handle.
- Rows expire after 90 days, and stored media expires with them.
- No secret, token or real contact detail is written to source, docs, fixtures or logs. Tests use fictional people and `example.com`.
- Allowlisted files do not grow, and new modules stay under 500 lines.
- Kill switches fail closed. With the `meta` tool off, the new tools refuse.
- The Facebook and Instagram posting pause is unaffected. No publish path is edited.
- Email behaviour is unchanged.

## Done when

- [ ] The handshake URL returns the challenge with the right token and `forbidden` with a wrong one.
- [ ] A message to the Page, a direct message to Instagram and a WhatsApp message from a person with no app role each appear in the Messages tab within a minute, with name, text and photo.
- [ ] A reply typed in Business Suite and a reply typed in the WhatsApp Business app appear in the same thread as outbound.
- [ ] `meta_get_thread` returns that history with aliases, and `GET /messages/{threadId}` through a key without `siutindei-pii` returns the same masked view.
- [ ] The nine Stanley WhatsApp conversations are present after the history import, each linked to its prospect, and each prospect that answered is `replied` with one catalog task.
- [ ] A staff draft to an organisation appears in Approvals and is not sent until approved.
- [ ] A webhook delivery of 50 messages returns in under two seconds in a unit test with the async invoke faked.
- [ ] The status panel shows the subscribed fields, the token permissions and the last delivery time per channel.
- [ ] `python3 -m unittest discover -p 'test_*.py'` in `backend/lambda/admin`, `python3 -m ruff check backend/lambda scripts`, `python3 scripts/check-contracts.py`, `python3 scripts/check_file_length.py`, `bash scripts/check-pii.sh`, and `npm run lint`, `npm test`, `npm run build` in `apps/admin_web` and `backend/infrastructure` pass on each pull request.

## Rollback

- Each pull request reverts on its own. Reverting 2 to 5 restores today's masked, inbound-only behaviour. New fields on stored rows are ignored by the old code.
- Stop intake without a deploy: remove the webhook subscription in the Meta App Dashboard, or blank the verify token and unsubscribe the Page.
- Disconnect WhatsApp: WhatsApp Business app, Settings, Account, Business Platform, Disconnect account. The phone keeps every chat.
- Stored messages and media expire after 90 days. To purge sooner, delete the `meta#thread` partitions and the `board/meta-media/` prefix by hand, which is an owner action.

## Open questions

- Route 1 (own Tech Provider) or Route 2 (Solution Partner) for coexistence. Recommendation: start Route 1 now and switch only if business verification or App Review is refused.
- Does the Page and Instagram messaging need Advanced Access? Meta's pages disagree for a business messaging on its own assets. Part B step 11 answers it.
- Storing Meta text unmasked at rest, as mail is, in place of masked at ingest. Recommendation: yes, because the owner cannot read aliases and the catalog seat needs the real timetable. The reviewer should confirm against `docs/architecture/security.md`.
- Should WhatsApp history be imported at all? It brings up to 180 days of every business chat on the number, not only the nine organisations. Recommendation: yes, since the number is business-only.
- Image transcription sends photos from organisations to the model provider. Acceptable for timetables, or limit it to an explicit staff tool call?
- Is 90 days long enough for organisation conversations, given the schedule is copied into the catalog?
- Does Meta's hosted Embedded Signup link support coexistence? If it does, the CSP change in pull request 4 is unnecessary.
- App Review asks for a privacy policy URL. This plan did not check whether the siutindei.com privacy page says that messages sent to the Page, Instagram or WhatsApp are stored and read by AI staff. Does it need a line before App Review?
- Approving a WhatsApp draft: default to the API send, or to opening the phone app with the text filled in?
