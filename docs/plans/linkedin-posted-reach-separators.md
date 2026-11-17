# Plan: LinkedIn posted reach thousand separators

**Status**: Done
**Zone**: yellow

## Goal

Show grouped integers in the Posted table Reach column so a value such as
`30000` impressions reads `30,000`. Reactions and comments in the same cell
use the same grouping.

## Non-goals

- No change to stored metrics, the LinkedIn refresh, or the Lambda
- No change to other admin tables or currency formatting
- No layout change to the Posted table

## Files

- `docs/plans/linkedin-posted-reach-separators.md` (this plan)
- `apps/admin_web/src/lib/formatDisplay.ts` — `formatCount` for grouped integers
- `apps/admin_web/src/lib/formatDisplay.test.ts`
- `apps/admin_web/src/components/linkedin/LinkedInPublishedSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInPublishedSection.test.tsx`
- `apps/admin_web/src/lib/linkedinModel.ts` — sample posted impressions of `30000`
- `apps/admin_web/docs/UI_COMPONENTS.md` — one line for `formatCount`

## Invariants this change preserves

- Empty or unavailable metrics still render an em dash
- A missing impressions count still omits the impressions clause
- Grouping uses the same `en-US` comma as money (`30,000`, not `30.000`)
- The Reach cell still reads `N reactions · N comments · N impressions`

## Done when

- `npm run test:unit` in `apps/admin_web` covers `formatCount` and the Posted Reach cell
- `npm run lint` in `apps/admin_web` passes
- Mock admin Posted tab shows `30,000 impressions` for the sample row

## Rollback

Revert the branch commits.

## Open questions

None.
