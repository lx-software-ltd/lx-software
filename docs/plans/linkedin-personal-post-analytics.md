# Plan: LinkedIn personal post analytics

**Status**: Done
**Zone**: yellow

## Goal

When the owner connects with personal post analytics, profile posts store lifetime impressions from LinkedIn member post statistics and the Posted table shows that count.

## Non-goals

- No company-page impression change
- No daily series, reach, reshares, or the newer creator metrics
- No contracts, CDK, or deploy changes
- The scope stays off unless the owner asks, so an unapproved product does not fail the consent screen

## Files

- `docs/plans/linkedin-personal-post-analytics.md` (this plan)
- `docs/deployment/admin-website.md` — optional scope and when impressions are read
- `backend/lambda/admin/linkedin_api.py` — scope and `memberCreatorPostAnalytics`
- `backend/lambda/admin/linkedin_metrics.py` — refresh loop, including profile impressions
- `backend/lambda/admin/linkedin.py` — connect flag; metrics refresh moves out
- `backend/lambda/admin/linkedin_store.py` — connection and OAuth flag
- `backend/lambda/admin/test_linkedin_api.py`
- `backend/lambda/admin/test_linkedin.py`
- `scripts/file-length-allowlist.txt` — lowered after the moves
- `apps/admin_web/src/lib/linkedinModel.ts`
- `apps/admin_web/src/hooks/useLinkedIn.ts`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.test.tsx`
- `apps/admin_web/src/lib/mock/routes/linkedin.ts`
- `apps/admin_web/src/lib/mock/routes/context.ts`
- `apps/admin_web/src/pages/LinkedInCallbackPage.tsx`

## Invariants this change preserves

- A connect that does not ask for personal post analytics still requests only `openid profile w_member_social` (plus organization scopes when company pages are included)
- Page impressions still come from organizational share statistics
- A denied reaction read is stored and not retried
- A failed impression read leaves the count empty and does not stop reaction refresh
- Tokens stay out of the SPA

## Done when

- `python3 -m unittest test_linkedin_api test_linkedin.LinkedInHttpTests.test_connect_keeps_company_pages_off_unless_asked test_linkedin.LinkedInHttpTests.test_connect_requests_personal_post_analytics_when_asked test_linkedin.LinkedInHttpTests.test_profile_impressions_use_member_post_analytics test_linkedin.LinkedInHttpTests.test_profile_impressions_stay_empty_without_the_scope test_linkedin.LinkedInHttpTests.test_a_denied_profile_impression_keeps_reactions -v` in `backend/lambda/admin` passes
- `npm run test:unit` in `apps/admin_web` passes
- `python3 scripts/check_file_length.py` passes
- Under `npm run dev:mock`, Settings shows the checkbox, connecting with it on records the flag, and a posted profile row shows its impression count

## Rollback

Revert the branch commit. Existing connections keep working; they simply have no member-analytics scope until the owner connects again.

## Open questions

None.
