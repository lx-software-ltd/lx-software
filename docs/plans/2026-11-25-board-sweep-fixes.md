# Plan: Executive Board fixes from the 2026-11-25 sweep

**Status**: Implemented
**Zone**: yellow

## Goal

Stop the two daily loops that spend model budget without qualifying prospects or importing catalog facts, and stop the board from dropping founder notes, accepting claims the tools refused, and reopening pre-launch tracking work.

One pull request, as asked. `contracts/**` stays untouched. The red options in the sweep (a Settings switch for site liveness, a `pausedChannels` key) are not taken. The provider handoff does not upsert a prospect; that path needed a separate owner choice. The handoff records the published contact and does not call `mail_send`.

## Non-goals

- Fit rubric, the score threshold of 60, `launchListingTarget`, and the trust ramp.
- `board_code.py`, `contracts/**`, and `backend/infrastructure/**`.
- Loosening `board_mail.recipient_sourced`.
- Auto-recreating expired approval drafts.
- CloudWatch for the 2026-11-25 02:25Z `outreach_score_prospect` failures. The admin Lambda logs are not on this machine. `board_crawl.py` already comments that errno 16 leaves `getaddrinfo` as a bare `OSError`, and `host_is_blocked` only catches `socket.gaierror`, which matches `Tool failed: [Errno 16] Device or resource busy`.

## Files

- `board_crawl.py` — `host_is_blocked` catches `OSError`. Fetched page text is cached for later checks.
- `board_prospect_facts.py` — scoring payload and a score call that survives a contact-lookup failure.
- `board_outreach.py`, `board_prospects.py`, `board_tools_outreach.py` — wire the score call, pass stored facts, filter `outreach_list_prospects` by district, reject a bracketed district that disagrees with the argument.
- `board_targets.py`, `board_progress.py` — numbered qualify brief, gap filter, cap of 8, weekly target from `qualifiedPerWeek`.
- `board_catalog_evidence.py`, `board_catalog_import.py` — demote verified facts that are not on a fetched page, refuse duplicate coordinates, stop after two failures.
- `board_catalog.py`, `board_triage.py` — skip generic host-root URLs, skip a second handoff after one was delivered, handoff brief has no mail step. Describe rows carry address, phone, and coordinates already on the candidate.
- `board_breakers.py` — `recipient not sourced` does not trip `tool:mail`.
- `board_store.py`, `board_context.py`, callers of `add_update` — `kind` `note` or `system`; the pack keeps 10 notes and 5 system lines.
- `board_web_live.py`, `board_web.py`, `board_context.py` — daily home-page probe; maintenance mode is printed into the pack and into session results.
- `board_review_claims.py`, `board_staff_review.py` — a sent, published, or qualified claim with no successful matching call is flagged and not accepted.
- `board_content_pause.py`, `board_content.py` — plan sentence from `perWeek`; skip the plan when social and seo counts are 0; skip the readout when nothing was published.
- `board_meta_metrics.py`, `board_meta.py`, `board_tools_meta.py` — drop retired metric names.
- `board_lessons.py`, `board_holds.py` — one lesson for a class veto, and one undecided draft per subject and class per hour.
- `board_review_expiry.py`, `board_review.py`, `board_staff.py` — approvals due within 48 hours are listed; expiry says expired, not declined.
- `docs/architecture/executive-board.md` — the behaviour above.

## Invariants this change preserves

- Qualify still needs a score of 60. The rubric text is unchanged.
- `recipient_sourced` still refuses a raw address.
- Kill switches stay fail-closed. An unset staff or tools flag is off.
- Catalog import still copies only `verified_fields`, and the thin-organisation rule still runs after a demotion.
- Founder updates stay on the admin Updates list. System lines are extra context, not a second store.
- No contract key is added.

## Done when

- `cd backend/lambda/admin && python3 -m unittest discover -p 'test_*.py'`
- `npm run lint`, `npm test`, and `npm run build` in `apps/admin_web`
- `pre-commit run check-file-length --all-files` and `pre-commit run check-test-focus --all-files` when the hooks are installed

## Rollback

Revert the pull request. No data migration. Cached `web:site-live` and `crawl:text:` rows expire on their TTL. Settings, including catalog auto-import, are not changed by this code.

## Review fixes

- A send, publish, or qualify claim is past tense, and a negation or "published contact" does not count. The flag is cleared when a later review has the successful call. Catalog sheets and the review headline are not parked for it.
- Fetched page text is stored under the requested URL and the final URL. Each organisation is checked against its own official page. Address and phone that match the imported record count as supported. The street number is the one beside the street name. A price needs every currency amount. The same coordinates are allowed when the street number and street name agree (shop or floor may differ). An evidence miss parks `unverified` at once and does not spend `revalidateAttempts`.
- The content readout reads the newest published rows.
- A busy resolver (errno 16, EAGAIN, EINTR) is retried once inside `host_is_blocked`, then fails closed.
- Unit tests stub the public-site probe. A failed probe is cached for 15 minutes. Maintenance is cached for 1 hour. A live result stays cached for a day.
- Only a class veto (`class_once`) merges lesson drafts in the same hour.
- The context pack reads the newest 1000 updates so a burst of system lines does not drop founder notes.
- A catalog handoff is remembered on its own cache row, so a long delivered list does not open a second task.
- `board_staff.py` keeps the pre-sweep formatting. The expiry sentence is the only change in that file.

## Open questions

- CloudWatch was not read. The errno 16 path is fixed from the code that produces that message.
- Handoff does not create a prospect. First contact stays on the founder’s outreach sequence only when someone upserts the organisation there.
- Page evidence runs when the task has a successful `research_fetch_page`. A sheet with no fetch is left to the existing thin-organisation rule, so current micro-batch accepts keep validating.
