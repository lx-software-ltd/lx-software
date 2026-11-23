# Plan: Dry-run cdk-deploy

**Status**: In progress
**Zone**: red

## Goal

Before the existing CDK deploy, compare `cdk-deploy` with that step. `npx cdk deploy`, `npx cdk destroy`, and `npx cdk bootstrap` are recorded and not executed. Mutating `aws` calls are recorded and not executed. Read-only CloudFormation describes still run. The comparison is `continue-on-error: true`. The deploy step stays the current script.

## Non-goals

- No switch. The job still deploys with the existing `npx cdk deploy` after the comparison.
- No pin change. The checkout `ref` is not a `uses` pin.
- No second deploy. A stub that fails its self-test stops the comparison before the current script runs.

## Files

`.github/workflows/deploy-backend.yml`, this plan.

## Invariants this change preserves

- The real deploy step's `run` and `env` stay as they are on `main`.
- Credentials still come from `aws-oidc` with `secrets.AWS_ACCOUNT_ID`.
- The comparison prints stack names, flags, and parameter names. It does not print parameter values.

## Done when

Workflow conformance passes. After merge, a `main` run prints `Dry run matches the current deploy (N planned CDK changes)` and the real step still deploys. Only then does a follow-up replace the script. A mismatch stays on the comparison step.

## Rollback

Revert the pull request. The next run is the current deploy with no comparison.

## Open questions

None.
