# Plan: LinkedIn analytics reactions and comments

**Status**: Done
**Zone**: yellow

## Goal

Profile posts store lifetime reactions and comments from the same analytics app that already stores impressions. Each count is one `memberCreatorPostAnalytics` call (`REACTION` or `COMMENT`, `TOTAL`) on the analytics token. Posts with no engagement count are read first. A post from the last 7 days is read again every six hours, a post from day 8 through day 30 once a day, and an older stored count stays. The development-tier cap remains 80 calls per UTC day, and one post can spend up to three of them.

## Non-goals

- No new LinkedIn permission, reconnect, route, or secret
- No repost count
- Company-page impressions and reactions stay on the posting token
- While the analytics app is disconnected, profile reactions stay on the posting app's social-actions read

## Files

- `docs/plans/linkedin-analytics-engagement.md` (this plan)
- `docs/deployment/admin-website.md`
- `docs/architecture/linkedin-reach.md`
- `backend/lambda/admin/linkedin_api.py`
- `backend/lambda/admin/linkedin_metrics.py`
- `backend/lambda/admin/test_linkedin.py`
- `backend/lambda/admin/test_linkedin_api.py`
- `apps/admin_web/src/lib/linkedinModel.ts`
- `apps/admin_web/src/components/linkedin/LinkedInPublishedSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInPublishedSection.test.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.tsx`

## Invariants this change preserves

- The analytics app still requests only `r_member_postAnalytics r_basicprofile`
- A failed read keeps a count already stored, and a first miss waits six hours
- The daily cap skips further analytics calls and does not fill profile reactions from the posting token
- Page posts do not call `memberCreatorPostAnalytics`
- Tokens stay out of the SPA

## Done when

- `python3 -m unittest discover -p 'test_*.py'` in `backend/lambda/admin` passes
- `python3 -m ruff check backend/lambda/admin/linkedin_api.py backend/lambda/admin/linkedin_metrics.py` passes
- `npm run test:unit` in `apps/admin_web` passes
- The posted table shows an impression count with no reaction line when reactions were never read

## Rollback

Revert the commit. Stored impression counts remain. Reaction and comment cells go back to the posting app's social-actions read.

## Open questions

None. The development tier's response for `REACTION` and `COMMENT` is confirmed by the first production pass after deploy, against the creator export for the 29 October post.
