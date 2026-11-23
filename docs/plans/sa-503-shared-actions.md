# Plan: SA-503 shared AWS actions

**Status**: In progress
**Zone**: red

`.pre-commit-config.yaml` is red. This pull request changes only its `rev`, because workflow conformance allows one `lx-software-ltd/actions` commit and that rev has to be the same commit. The deploy, diff, bootstrap, and key workflows are red. No workflow is dispatched.

## Goal

Pin every shared action and the pre-commit rev to `b40bb0725bf84f25a38641f6ca5ec6f4c2f14f98`, the current `actions` `main`, with `# main 2026-11-23`. Call `aws-oidc` from the deploy, diff, bootstrap, and key workflows. `cdk-diff.yml` calls `cdk-bootstrap-check` and `cdk-diff`. `deploy-admin-web.yml` reads `UserPoolClientId`, `CognitoDomain`, and `AdminApiBaseUrl` with `cfn-stack-outputs`. The https checks stay in the workflow. The account id is `secrets.AWS_ACCOUNT_ID` only.

## Non-goals

- No `pull_request` trigger on CDK Diff. The workflow stays `workflow_dispatch`.
- No replacement of the inline bootstrap check in `deploy-backend.yml`. Removing `cdk bootstrap` from that workflow is C24.
- No second actions commit.
- No account id in git. No deploy, bootstrap, or key-management run. `json` from `cfn-stack-outputs` is read in the same job and is not a job output.

## Files

`.github/workflows/cdk-diff.yml`, `deploy-backend.yml`, `deploy-admin-web.yml`, `deploy-public-website.yml`, `cdk-bootstrap.yml`, `manage-api-keys.yml`, the other workflow pins, `.pre-commit-config.yaml`, this plan.

## Invariants this change preserves

- Public website credentials stay after `npm ci` and the build.
- Admin web still runs `npm ci` before assuming the role, then reads the stack, then builds.
- Admin web still refuses a Cognito domain or API URL that is not `https://`.
- CDK Diff still names stacks only when the dispatch input is set. An empty input diffs every stack.
- Backend deploy still checks bootstrap with the inline read.
- The account id is not placed in an `if` expression.

## Done when

Workflow conformance in enforce mode reports one actions commit. No workflow calls `configure-aws-credentials`.

## Rollback

Revert this pull request. The previous pin is `9235676200771b2f93bc01ac85f3de1392133182`.

## Open questions

None.
