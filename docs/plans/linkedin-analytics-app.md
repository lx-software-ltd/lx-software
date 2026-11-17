# Plan: LinkedIn analytics app

**Status**: Done
**Zone**: yellow

## Goal

Profile posts store lifetime impressions from the LX Software Analytics app, which holds the Community Management API. Posting stays on the LX Software app. The owner connects the analytics app on its own, and the metrics pass reads `memberCreatorPostAnalytics` with that token, including posts already published. Counts from the last 30 days are read again every six hours. A development-tier day stops after 80 analytics calls, including the profile read and a token refresh. The counter update does not rewrite the token.

## Non-goals

- No second Secrets Manager secret and no CDK change. The analytics client id and secret are `analyticsClientId` and `analyticsClientSecret` on `lxsoftware-admin-linkedin-app`
- No company-page impression change
- No members-reached, reshares, follower series, or day-1 / day-2 snapshots
- The posting connect does not gain the analytics scope. An existing posting connection that already asked for it still works

## Files

- `docs/plans/linkedin-analytics-app.md` (this plan)
- `docs/deployment/admin-website.md` — two apps, two connects
- `docs/architecture/linkedin-reach.md` — where impressions come from
- `backend/lambda/admin/linkedin_analytics.py` — credentials, OAuth, daily cap
- `backend/lambda/admin/linkedin_api.py` — `r_basicprofile` member read
- `backend/lambda/admin/linkedin_metrics.py` — analytics token for profile impressions
- `backend/lambda/admin/linkedin.py` — route the analytics connect and the shared callback
- `backend/lambda/admin/linkedin_plan.py` — overview includes the analytics connection
- `backend/lambda/admin/test_linkedin.py`
- `backend/lambda/admin/test_linkedin_api.py`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.test.tsx`
- `apps/admin_web/src/hooks/useLinkedIn.ts`
- `apps/admin_web/src/lib/linkedinModel.ts`
- `apps/admin_web/src/lib/mock/routes/linkedin.ts`
- `apps/admin_web/src/lib/mock/routes/context.ts`
- `apps/admin_web/src/pages/LinkedInCallbackPage.tsx`

## Invariants this change preserves

- Posting still requests only `openid profile w_member_social`, plus organization scopes when company pages are included
- Page impressions still come from organizational share statistics on the posting token
- A failed impression read keeps a count already stored, and a first miss stays empty for six hours
- Tokens stay out of the SPA
- Disconnecting posting leaves the analytics connection in place, and the reverse

## Done when

- `python3 -m unittest discover -p 'test_*.py'` in `backend/lambda/admin` passes
- `npm run test:unit` in `apps/admin_web` passes
- `python3 scripts/check_file_length.py` passes
- Under `npm run dev:mock`, Settings shows Connect analytics apart from posting, and connecting it records the analytics connection

## Rollback

Revert the branch commit. The extra secret fields are ignored by the previous code. Disconnect the analytics app in LinkedIn if a token should stop being used.

## Open questions

None.
