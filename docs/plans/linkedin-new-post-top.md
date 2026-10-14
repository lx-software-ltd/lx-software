# Plan: LinkedIn new post at top of table

**Status**: Ready
**Zone**: yellow

## Goal

When **New post** is open, the draft row sits at the top of the Drafts
table, the same place finance create rows already use. It currently
renders after every existing draft.

## Non-goals

- No change to Ideas, Calendar, or Posted
- No change to saved-post sort order
- No contracts, CDK, or Lambda changes

## Files

- `docs/plans/linkedin-new-post-top.md` (this plan)
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`

## Invariants this change preserves

- `new` is still the query value for the create draft
- One row is open
- Existing drafts keep their current order
- LinkedIn rows stay on the `LINKEDIN#` prefix and out of `/records`

## Done when

- `npm run test:unit` in `apps/admin_web` covers row order
- `npm run lint` in `apps/admin_web` passes
- Under `npm run dev:mock`, **New post** opens above the first draft

## Rollback

Revert the commit that moves the create row.

## Open questions

None.
