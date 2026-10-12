# Plan: LinkedIn story tones

**Status**: Done
**Zone**: yellow

## Goal

Add four story-tone buttons under LinkedIn Settings → Voice. Each button fills the Voice field. Save stores the chosen note for the next drafts.

## Non-goals

- No change to substance or safety rules
- No change to per-draft shape rotation
- No assertive register, and no catchphrase quoted in a voice note
- The Sunday batch does not assign a different tone to each draft

## Files

- `docs/plans/linkedin-story-tones.md` (this plan)
- `backend/lambda/admin/linkedin_voices.py` — `RECOMMENDED_VOICE`, `STORY_VOICES`
- `backend/lambda/admin/linkedin_store.py` — re-exports those notes and returns them from overview
- `backend/lambda/admin/test_linkedin.py`
- `apps/admin_web/src/lib/linkedinModel.ts` — `LINKEDIN_STORY_VOICES`
- `apps/admin_web/src/lib/linkedinModel.test.ts`
- `apps/admin_web/src/lib/mock/routes/linkedin.ts`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.test.tsx`
- `docs/deployment/admin-website.md`
- `scripts/file-length-allowlist.txt` — `linkedin_store.py` allowance lowered after the move

## Invariants this change preserves

- `RECOMMENDED_VOICE` text is unchanged and is the Over lunch note
- Each note stays under 1000 characters and quotes no catchphrase
- The same four notes exist in the Lambda and the SPA
- Voice still overrides tone defaults only; substance and safety rules stay in force
- Shape rotation (`OPENINGS` × `CLOSINGS` × `LENGTHS`) is unchanged

## Done when

- `python3 -m unittest test_linkedin.LinkedInStoreTests.test_story_voices -v` in `backend/lambda/admin` passes
- `npm run test:unit` in `apps/admin_web` covers the four notes and a click that fills Voice
- `npm run dev:mock`: Settings shows the four buttons and a click fills the Voice field

## Rollback

Revert the branch commit that adds the story-tone notes and buttons.

## Open questions

None. One chosen note applies to the whole batch. Shape rotation still varies the way in and the way out.
