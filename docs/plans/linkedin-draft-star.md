# Plan: LinkedIn draft star

**Status**: Done
**Zone**: yellow

## Goal

Add a star button next to each LinkedIn draft on the drafts table. Clicking it
toggles a like: outline star off, filled yellow star on. The flag persists on
the post so a refresh keeps the mark.

## Non-goals

- No star on Calendar, Posted, or Ideas
- No filter or sort by starred
- No contracts, CDK, or deploy changes
- Stars do not change approval, copy, or generation

## Files

- `docs/plans/linkedin-draft-star.md` (this plan)
- `backend/lambda/admin/linkedin_store.py` — store and return `starred`
- `backend/lambda/admin/test_linkedin.py` — star does not unapprove
- `apps/admin_web/src/lib/linkedinModel.ts` — `starred` on `LinkedInPost`
- `apps/admin_web/src/hooks/useLinkedIn.ts` — optimistic star mutation
- `apps/admin_web/src/lib/mock/routes/linkedin.ts` — persist `starred` on PUT
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx` — star button
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`
- `apps/admin_web/src/styles/tables.css` — star colour
- `apps/admin_web/e2e/mobile-smoke.spec.ts` — click the star
- `docs/deployment/admin-website.md` — one sentence on the drafts queue
- `scripts/file-length-allowlist.txt` — `linkedin_store.py` after the added lines

## Invariants this change preserves

- Starring is not a copy edit: an approved post stays approved and keeps its slot
- Clicking the star does not expand or collapse the row
- Other row actions stay in the kebab menu
- Existing posts without `starred` read as unstarred
- LinkedIn rows stay on the `LINKEDIN#` prefix and out of `/records`

## Done when

- `python3 -m unittest test_linkedin.LinkedInStoreTests.test_star_toggles_without_unapproving -v` in `backend/lambda/admin` passes
- `npm run test:unit` in `apps/admin_web` covers the star toggle
- `npm run lint` in `apps/admin_web` passes
- Under `npm run dev:mock`, each draft row has a star that turns yellow on click and back on a second click

## Rollback

Revert the branch commit that adds `starred` and the star button.

## Open questions

None.
