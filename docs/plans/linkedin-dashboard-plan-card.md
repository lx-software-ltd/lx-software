# Plan: LinkedIn plan card on the LX Software dashboard

**Status**: Done
**Zone**: yellow

## Goal

On the LX Software dashboard, show a card on the same line as the fiscal year
card. It shows how many LinkedIn posts are still planned (approved, slot not
yet arrived), how many are overdue, and the first next empty slot in Hong
Kong time. The card uses `GET /lx-software/linkedin?view=plan`, stays visible
when the statement book is loading or failed, and refetches when the window
is focused or when the next relevant time arrives.

## Non-goals

- Siu Tin Dei, Evolve Sprouts, and the main Dashboard stay as they are
- No change to slot assignment or approval
- No new API Gateway route
- Drafts are not counted; a post is planned once it is approved

## Files

- `docs/plans/linkedin-dashboard-plan-card.md` (this plan)
- `backend/lambda/admin/linkedin_plan.py` — `plan_summary`, under the file-length ceiling
- `backend/lambda/admin/linkedin.py` — `?view=plan` on the existing GET
- `backend/lambda/admin/test_linkedin.py`
- `apps/admin_web/src/lib/linkedinModel.ts` — `linkedInPlanSummary`
- `apps/admin_web/src/lib/linkedinModel.test.ts`
- `apps/admin_web/src/components/dashboard/LinkedInPlanDashboardCard.tsx`
- `apps/admin_web/src/components/dashboard/LinkedInPlanDashboardCard.test.tsx`
- `apps/admin_web/src/pages/StatementBookPage.tsx` — optional card beside the fiscal year card
- `apps/admin_web/src/pages/LxSoftwarePage.tsx`
- `apps/admin_web/src/pages/LxSoftwarePage.test.tsx`
- `apps/admin_web/src/hooks/useLinkedIn.ts` — shared overview and plan queries
- `apps/admin_web/src/lib/mock/routes/linkedin.ts`
- `docs/deployment/admin-website.md`

## Invariants this change preserves

- The fiscal year card stays full width when no beside-card is passed
- Planned is approved posts whose slot is still in the future, plus an approved post with no slot
- Overdue is approved posts whose slot has passed
- The next empty slot is the first open time from `next_slots`, the same list the publisher uses
- `?view=plan` stays on the existing LinkedIn GET, so no API Gateway route is added
- Slot text uses `formatDateTimeHKT`

## Done when

- `npx vitest run src/lib/linkedinModel.test.ts src/components/dashboard/LinkedInPlanDashboardCard.test.tsx src/pages/LxSoftwarePage.test.tsx src/lib/mock/mockAdminApi.test.ts` in `apps/admin_web` passes
- `npm run lint` in `apps/admin_web` passes
- `python3 -m unittest test_linkedin.LinkedInStoreTests.test_plan_summary_splits_upcoming_from_overdue test_linkedin.LinkedInHttpTests.test_plan_view_returns_only_the_dashboard_counts` in `backend/lambda/admin` passes
- In `npm run dev:mock`, the LX Software dashboard shows the card beside the fiscal year card, and approving a draft updates the planned count and the next empty slot

## Rollback

Remove `fiscalYearAside` from the LX Software page and delete the card.

## Open questions

None.
