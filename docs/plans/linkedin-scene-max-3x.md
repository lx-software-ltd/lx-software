# Plan: LinkedIn scene max 3x

**Status**: Ready
**Zone**: yellow

## Goal

Raise the LinkedIn draft picture `imageScene` cap from 400 to 1200
characters (3×) so a longer gag-cartoon brief can be stored, edited, and
sent to the image model.

## Non-goals

- No change to expression (80) or caption (140) caps
- No change to the default draft model or OpenRouter keys
- No contracts, CDK, or deploy changes

## Files

- `docs/plans/linkedin-scene-max-3x.md` (this plan)
- `backend/lambda/admin/linkedin_store.py` — `IMAGE_SCENE_MAX` and overview
- `backend/lambda/admin/test_linkedin.py` — cap and overview
- `apps/admin_web/src/lib/linkedinModel.ts` — mirrored `IMAGE_SCENE_MAX`
- `apps/admin_web/src/lib/linkedinModel.test.ts`
- `apps/admin_web/src/lib/mock/routes/linkedin.ts` — fixture overview
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx` — Scene field
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`
- `docs/deployment/admin-website.md` — scene cap
- `scripts/file-length-allowlist.txt` — `linkedin_store.py` after the added overview field

## Invariants this change preserves

- Scene text is still sliced at `IMAGE_SCENE_MAX` on parse and on draw
- Expression and caption caps stay 80 and 140
- LinkedIn rows stay on the `LINKEDIN#` prefix and out of `/records`
- Frontend `IMAGE_SCENE_MAX` stays the same number as `linkedin_store.py`

## Done when

- `python3 -m unittest test_linkedin.LinkedInImageTests.test_scene_keeps_three_times_the_old_cap -v` in `backend/lambda/admin` passes
- `npm run test:unit` in `apps/admin_web` covers the Scene `maxLength`
- `npm run lint` in `apps/admin_web` passes
- Under `npm run dev:mock`, the Scene field accepts 1200 characters

## Rollback

Revert the branch commit that raises `IMAGE_SCENE_MAX`.

## Open questions

None.
