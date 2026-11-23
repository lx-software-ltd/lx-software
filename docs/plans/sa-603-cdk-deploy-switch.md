# Plan: Switch Deploy Backend to cdk-deploy

**Status**: In progress
**Zone**: red

## Goal

Replace the lx-software CDK deploy script with `cdk-deploy`. The dry run on `main` printed `Dry run matches the current deploy (2 planned CDK changes)` on runs `45116136708`, `45127095535`, and `45136439530`. The script still deployed after each comparison.

## Non-goals

- No other workflow. The public and admin website uploads already use `s3-cloudfront-deploy`.
- No change to stack order, parameter names, or the allow-list check.

## Files

`.github/workflows/deploy-backend.yml`, this plan.

## Invariants this change preserves

- `lxsoftware-public-www` deploys first. The allow-list is checked before `lxsoftware` and `lxsoftware-admin-web`.
- An empty `SIUTINDEI_BOARD_META_VERIFY_TOKEN` does not send `lxsoftware:SiutindeiBoardMetaVerifyToken`.
- Credentials still come from `aws-oidc` with `secrets.AWS_ACCOUNT_ID`.
- The plan keeps `unprefixed-prefix` `lxsoftware-public-www:`.

## Done when

Workflow conformance passes. After merge, the first Deploy Backend reports no CloudFormation changes apart from Lambda functions.

## Rollback

Revert the pull request. The next run uses the shell deploy again.

## Open questions

None.
