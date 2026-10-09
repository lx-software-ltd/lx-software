# Plan: LinkedIn Personal pillar

**Status**: Done
**Zone**: yellow

## Goal

Add a LinkedIn content pillar named Personal (`id: personal`) so drafts, ideas, and settings can use it alongside the existing pillars.

## Non-goals

- No new seed topics for the pillar
- No contracts, CDK, or deploy changes
- No change to voice notes or guardrails

## Files

- `docs/plans/linkedin-personal-pillar.md` (this plan)
- `backend/lambda/admin/linkedin_store.py` — `PILLARS`
- `backend/lambda/admin/test_linkedin.py` — pillar list assertion
- `apps/admin_web/src/lib/linkedinModel.ts` — `LINKEDIN_PILLARS`
- `apps/admin_web/src/lib/linkedinModel.test.ts` — pillar list assertion
- `apps/admin_web/src/lib/mock/routes/linkedin.ts` — overview pillar list

## Invariants this change preserves

- Pillar ids stay lowercase kebab-case and match between Lambda and the SPA
- Existing pillars keep their ids and labels
- Default settings still enable every known pillar
- Posts still fail closed on unknown pillar ids

## Done when

- `python3 -m unittest test_linkedin.TestLinkedInPillars -v` in `backend/lambda/admin` passes
- `npm run test:unit` in `apps/admin_web` covers the Personal pillar label
- Personal appears in Settings pillar checkboxes under `npm run dev:mock`

## Rollback

Revert the branch commit that adds the Personal pillar entry and tests.

## Open questions

None.
