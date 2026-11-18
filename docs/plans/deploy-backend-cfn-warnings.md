# Plan: Clear Deploy Backend CloudFormation Validate warnings

**Status**: Done
**Zone**: red (`backend/infrastructure/**`; owner asked to fix the deploy log)

## Goal

Remove the three `WARNING` lines from Deploy Backend synth. Run
`44276938389` (18 Nov 2026, Hong Kong) printed
`CloudFormation-Validate::W1030` because `CognitoCustomDomainName` and
`CognitoCustomDomainCertificateArn` default to `""`, and the validator
substitutes those defaults into `Auth/HostedUICustomDomain` before
`UseCustomAuthDomain` applies.

Also stop the pip "new release" notice from Lambda bundling.

## Non-goals

- Changing the optional custom Hosted UI (empty still means prefix domain).
- Dummy certificate ARNs or domain names as parameter defaults.
- The git checkout `hint:` line from `actions/checkout`.

## Files

- `backend/infrastructure/lib/constructs/auth.ts` — acknowledge W1030 on
  the custom domain resource and the stack (the parameter-default finding
  is attributed to the stack).
- `backend/infrastructure/lib/constructs/python-lambda.ts` —
  `PIP_DISABLE_PIP_VERSION_CHECK=1` in the bundling script.
- `backend/infrastructure/test/lxsoftware-stack.test.ts` and
  `backend/infrastructure/test/python-lambda.test.ts`

## Invariants this change preserves

- `HostedUICustomDomain` still requires both custom-domain parameters.
- Parameter defaults stay empty. Production still supplies
  `params/production.json`.
- Logical IDs of the user pool, app client, and domain resources stay.

## Done when

- `CDK_SKIP_PYTHON_PIP=1 npx cdk synth lxsoftware` prints no
  `CloudFormation Validate` `WARNING`.
- `npm test` in `backend/infrastructure` passes.

## Rollback

Revert the commit. The next deploy prints the three warnings again.

## Open questions

None.
