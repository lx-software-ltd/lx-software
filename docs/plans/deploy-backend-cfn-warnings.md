# Plan: Clear Deploy Backend CloudFormation Validate warnings

**Status**: Done
**Zone**: red (`backend/infrastructure/**`)

The owner asked to clear the Deploy Backend log, then to fix the review of
the first revision. This revision is that fix. The first revision
acknowledged `W1030` on the whole `lxsoftware` stack. That acknowledgement
also hid an unrelated empty-certificate resource added in review, so it is
gone.

## Goal

Remove the three `WARNING` lines from Deploy Backend synth. Run
`44276938389` (18 Nov 2026, Hong Kong) printed
`CloudFormation-Validate::W1030` because `CognitoCustomDomainName` and
`CognitoCustomDomainCertificateArn` defaulted to `""`, and the validator
substitutes those defaults into `Auth/HostedUICustomDomain` before
`UseCustomAuthDomain` applies.

`allowedPattern` does not change that check. `Fn::If` with `AWS::NoValue`
adds warnings. The defaults are now schema-valid placeholders that the
condition treats as unset, the same as `""`.

Also stop the pip "new release" notice from Lambda bundling. The bundling
script passes `--disable-pip-version-check` and sets
`PIP_DISABLE_PIP_VERSION_CHECK=1`.

## Non-goals

- A stack-wide or resource-wide acknowledgement of `W1030`.
- Changing production's hostname or certificate. `params/production.json`
  still supplies both.
- The git checkout `hint:` line from `actions/checkout`.

## Files

- `backend/infrastructure/lib/cognito-custom-domain.ts`
- `backend/infrastructure/lib/admin-parameters.ts`
- `backend/infrastructure/lib/constructs/auth.ts`
- `backend/infrastructure/lib/constructs/python-lambda.ts`
- `backend/infrastructure/test/lxsoftware-stack.test.ts`
- `backend/infrastructure/test/python-lambda.test.ts`
- `backend/infrastructure/params/README.md`

## Invariants this change preserves

- An empty custom-domain parameter still selects the prefix domain.
- The disabled defaults select the prefix domain too.
- Production still supplies `auth.lx-software.com` and its ACM ARN.
- User pool, app client, and domain logical IDs stay.
- `W1030` is still reported for a resource whose certificate default is empty.

## Done when

- `CDK_SKIP_PYTHON_PIP=1 npx cdk synth` for every stack prints no
  `CloudFormation Validate` `WARNING`.
- The stack test shows the probe resource still reports `W1030`.
- `npm test` and `npm run build` in `backend/infrastructure` pass.
- pip 25.0.1, the version in the deploy log, prints the upgrade notice,
  and the bundling script's install does not.

## Rollback

Revert the commits. The next deploy prints the three warnings and the pip
notice again. Live Hosted UI values come from `params/production.json`,
not from the template defaults.

## Open questions

None.
