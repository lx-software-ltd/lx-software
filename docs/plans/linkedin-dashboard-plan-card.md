# Plan: LinkedIn plan card on the LX Software dashboard

**Status**: Done
**Zone**: yellow

## Goal

On the LX Software dashboard, show a card on the same line as the fiscal year
card. It shows how many LinkedIn posts are planned (approved, waiting for
their slot) and the first next empty slot in Hong Kong time.

## Non-goals

- Siu Tin Dei, Evolve Sprouts, and the main Dashboard stay as they are
- No change to slot assignment, approval, or the LinkedIn API
- Drafts are not counted; a post is planned once it is approved

## Files

- `docs/plans/linkedin-dashboard-plan-card.md` (this plan)
- `apps/admin_web/src/lib/linkedinModel.ts` — `linkedInPlanSummary`
- `apps/admin_web/src/lib/linkedinModel.test.ts`
- `apps/admin_web/src/components/dashboard/LinkedInPlanDashboardCard.tsx`
- `apps/admin_web/src/components/dashboard/LinkedInPlanDashboardCard.test.tsx`
- `apps/admin_web/src/pages/StatementBookPage.tsx` — optional card beside the fiscal year card
- `apps/admin_web/src/pages/LxSoftwarePage.tsx`
- `apps/admin_web/src/pages/LxSoftwarePage.test.tsx`

## Invariants this change preserves

- The fiscal year card stays full width when no beside-card is passed
- Planned count is `counts.approved` from `GET /lx-software/linkedin`
- The next empty slot is the first `nextSlots` entry, the same list the publisher uses
- Slot text uses `formatDateTimeHKT`

## Done when

- `npx vitest run src/lib/linkedinModel.test.ts src/components/dashboard/LinkedInPlanDashboardCard.test.tsx src/pages/LxSoftwarePage.test.tsx` in `apps/admin_web` passes
- `npm run lint` in `apps/admin_web` passes
- In `npm run dev:mock`, the LX Software dashboard shows the card beside the fiscal year card, and approving a draft updates the planned count and the next empty slot

## Rollback

Remove `fiscalYearAside` from the LX Software page and delete the card.

## Open questions

None.
