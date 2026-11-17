# Plan: LinkedIn analytics refresh fixes

**Status**: Done
**Zone**: yellow

## Goal

Keep the analytics refresh from the engagement change, and correct the six review findings. A spent daily cap still refreshes company-page posts. A denied `memberCreatorPostAnalytics` query is logged and not retried. Due profile posts are read newest first. The posted table shows each read count on its own, and a profile zero that was never read stays blank. Disconnecting analytics does not replace a stored analytics reaction or comment with the posting app's social-actions count.

## Non-goals

- No new LinkedIn permission, route, or secret
- No change to the 80-call development-tier cap
- Page reactions stay on the posting token

## Files

- `docs/plans/linkedin-analytics-engagement-fixes.md` (this plan)
- `docs/deployment/admin-website.md`
- `docs/architecture/linkedin-reach.md`
- `backend/lambda/admin/linkedin_api.py`
- `backend/lambda/admin/linkedin_metrics.py`
- `backend/lambda/admin/linkedin_member_analytics.py`
- `backend/lambda/admin/test_linkedin.py`
- `backend/lambda/admin/test_linkedin_api.py`
- `apps/admin_web/src/lib/linkedinModel.ts`
- `apps/admin_web/src/components/linkedin/LinkedInPublishedSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInPublishedSection.test.tsx`

## Invariants this change preserves

- The analytics app still requests only `r_member_postAnalytics r_basicprofile`
- A failed read that is not a denial keeps a count already stored and waits six hours
- Page posts do not call `memberCreatorPostAnalytics`
- Tokens stay out of the SPA

## Done when

- `python3 -m unittest test_linkedin.py test_linkedin_api.py` in `backend/lambda/admin` passes
- `python3 -m ruff check backend/lambda/admin/linkedin_api.py backend/lambda/admin/linkedin_metrics.py` passes
- `npm run test:unit` in `apps/admin_web` passes for the posted-reach tests

## Rollback

Revert the commit. Stored counts remain. The refresh returns to the previous cap, order, and display rules.

## Open questions

None.
