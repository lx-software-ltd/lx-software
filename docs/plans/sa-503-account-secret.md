# Plan: SA-503 account id secret

**Status**: Merged in lx-software #674 (`b96868b`).
**Zone**: red

The deploy, diff, bootstrap, and key workflows change which value they read. No actions pin moves. No workflow is dispatched.

## Goal

Workflows read `secrets.AWS_ACCOUNT_ID`. They no longer read `vars.AWS_ACCOUNT_ID`. Deploy Public Website on main (`45038917904`) skipped its credentials step because that variable is empty, then the upload ran without a region. The credentials step stays after the build. A step `if` checks `vars.AWS_REGION` only, so the account id is not placed in an `if` expression.

## Non-goals

- No switch to `aws-oidc` or `cfn-stack-outputs`. That is a later pull request.
- No change to the actions pin or `.pre-commit-config.yaml`.
- No deploy, bootstrap, or key-management run.

## Files

`.github/workflows/deploy-public-website.yml`, `deploy-admin-web.yml`, `deploy-backend.yml`, `cdk-diff.yml`, `cdk-bootstrap.yml`, `manage-api-keys.yml`, the deployment docs named below, this plan.

## Invariants this change preserves

- Public website credentials stay after `npm ci` and the build.
- `AWS_REGION` stays a variable.
- The actions pin is unchanged.
- The account id is not written into git. Logs mask a secret.

## Done when

No workflow contains `vars.AWS_ACCOUNT_ID`. No `if` expression contains `secrets.AWS_ACCOUNT_ID`.

## Rollback

Revert this pull request. The previous expression is `vars.AWS_ACCOUNT_ID`.

## Open questions

None.
