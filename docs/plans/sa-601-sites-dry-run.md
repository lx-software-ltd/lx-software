# Plan: Dry-run the public and admin website deploys

**Status**: In progress
**Zone**: red

## Goal

Before each existing upload, compare `s3-cloudfront-deploy` with the current script. The public site uses profile `public-routes`. The admin site uses `admin-hashed`. Each comparison is `continue-on-error: true`. The public comparison sets `INDEXNOW_DISABLED=1` for that invocation only.

## Non-goals

- No switch. Both upload steps stay the shell scripts.
- No pin change. The checkout of the deploy action is a `ref`, not a `uses` pin.
- No second IndexNow ping from the comparison.

## Files

`.github/workflows/deploy-public-website.yml`, `.github/workflows/deploy-admin-web.yml`, the two deployment docs, this plan.

## Invariants this change preserves

- Credentials still come from `aws-oidc` with `secrets.AWS_ACCOUNT_ID`.
- The real public step still pings IndexNow. The real admin step is still `bash scripts/deploy/deploy-admin-www.sh` with no extra env.

## Done when

Workflow conformance passes. After merge, a `main` run of each workflow prints `Dry run matches the current deploy (N planned S3 changes)` and the script still uploads. Only then does a follow-up replace that script.

## Rollback

Revert the pull request.

## Open questions

None.
