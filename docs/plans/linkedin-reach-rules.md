# Plan: LinkedIn reach rules

**Status**: Done
**Zone**: yellow

## Goal

Make the draft generator write posts the way the measured October 2026 posts say a post has to be written to get past LinkedIn's first wave: a short first line that carries a figure or a person, a 200 to 260 word body, the engineering detail in the first comment, one line of setting, and a closing question only this story can raise. The measurements and the reasoning live in `docs/architecture/linkedin-reach.md`.

## Non-goals

- No change to the safety rules (hook cap 210, employer, availability, pitch, blocked phrases)
- No automatic scheduling of personal posts; a personal post needs the owner's own material
- No change to the metrics refresh, which still stores nothing for these posts
- No new settings field; the rules are substance rules the voice cannot override

## Files

- `docs/plans/linkedin-reach-rules.md` (this plan)
- `docs/architecture/linkedin-reach.md` — the measured posts and the rules drawn from them
- `backend/lambda/admin/linkedin_reach.py` — new: `HOOK_PREVIEW_MAX`, `BODY_WORDS_MAX`, `OPENINGS`, `CLOSINGS`, `LENGTHS`, `shape_for`, `reach_block`, `reach_findings`
- `backend/lambda/admin/linkedin_draft.py` — imports the shape rotation from `linkedin_reach`, adds the reach block to the system prompt, runs `reach_findings` before the rewrite pass, and shows a filled `firstComment` in the schema example
- `backend/lambda/admin/linkedin_voices.py` — the four voices say 200 to 260 words and allow the one closing question
- `backend/lambda/admin/test_linkedin.py`
- `apps/admin_web/src/lib/linkedinModel.ts` — `RECOMMENDED_LINKEDIN_VOICE` and `LINKEDIN_STORY_VOICES` mirror the Lambda text
- `apps/admin_web/src/lib/linkedinModel.test.ts`
- `docs/deployment/admin-website.md`
- `.cursor/rules/linkedin.mdc`
- `scripts/file-length-allowlist.txt` — `linkedin_draft.py` allowance lowered after the move

## Invariants this change preserves

- `RECOMMENDED_VOICE` and `RECOMMENDED_LINKEDIN_VOICE` are the same text and under 1000 characters; no voice quotes a catchphrase
- `OPENINGS`, `CLOSINGS`, and `LENGTHS` keep coprime lengths (7, 6, 5) so `shape_for` still walks distinct pairs
- `HOOK_MAX` (210) stays the hard cap in `linkedin_store.guardrails`; the 110-character preview limit is a draft-time check that sends the draft to the rewrite pass
- Draft-time findings keep the `{code, severity, detail}` shape and are never stored
- `linkedin_draft.py` does not grow; `linkedin_reach.py` stays under the 500-line ceiling

## Done when

- `python3 -m unittest test_linkedin -v` in `backend/lambda/admin` passes, including the new `reach_findings` and system-prompt tests
- `python3 scripts/check_file_length.py` passes with the lowered allowance
- `npm run test:unit` in `apps/admin_web` passes with the mirrored voices
- `python3 scripts/validate_agent_rules.py` and `python3 scripts/check_pii.py` pass

## Rollback

Revert the branch commits. The stored voice in Settings keeps whatever text the owner saved; a saved copy of the old recommended voice is replaced by the new one on load only if it matches the retired text exactly, otherwise it stays.

## Open questions

- The first comment and the closing question are prompt rules, not deterministic checks. A check would send every draft whose comment is empty to the rewrite pass; the batch tests stub bodies without a comment, and the model has never been asked for one until now. Revisit after the next batch shows whether the filled schema example is enough.
- The admin metrics refresh stores `impressions: null` and `reactions: 0` for every published post, including the one that reached 26,498 impressions. Until that is fixed the LinkedIn export is the source of truth for the numbers in `docs/architecture/linkedin-reach.md`.
