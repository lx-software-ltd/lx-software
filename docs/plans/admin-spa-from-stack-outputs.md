# Plan: Admin SPA settings from stack outputs

**Status**: Done
**Zone**: red (deploy workflows and `backend/infrastructure/params`) and yellow (`apps/admin_web/src`). Approved in chat.

## Goal

Stop copying admin SPA settings into GitHub variables.

- **Deploy Admin Web** reads `UserPoolClientId`, `CognitoDomain`, and `AdminApiBaseUrl` from the `lxsoftware` stack. `CognitoDomain` stays a full `https://` origin.
- The admin SPA no longer requires `VITE_COGNITO_USER_POOL_ID`.
- `lxsoftware-admin-web:AdminWebCertificateArn` lives in `params/production.json`, the same us-east-1 certificate the public site and the Cognito custom domain already use.

## Non-goals

- Deriving WhatsApp from the telephone.
- Removing the optional `VITE_CONTACT_EMAIL` override. Production should leave that variable and `VITE_OWNER_NAME` unset; the mailto address is `site.email`.
- Moving `AWS_ACCOUNT_ID`, `AWS_REGION`, `CDK_BOOTSTRAP_QUALIFIER`, or `CDK_PARAM_FILE`.
- Deleting GitHub variables from this change. Delete them after this is on `main`.

## Files

- `.github/workflows/deploy-admin-web.yml`
- `.github/workflows/deploy-backend.yml`
- `.github/workflows/test.yml`
- `backend/infrastructure/params/production.json`
- `apps/admin_web/src/lib/config.ts` and `config.test.ts`
- Deployment docs and the admin env examples

## Invariants this change preserves

- Sign-in, token, revoke, and logout URLs are absolute `https` URLs. A bare hostname fails the deploy.
- The admin CloudFront certificate stays the issued us-east-1 certificate already in the parameter file.
- Google client id, the email allow-list, and the bootstrap email stay GitHub variables. Phone numbers and personal inboxes stay out of git.

## Done when

`npm run test:unit` and `npm run lint` pass in `apps/admin_web`. The production.json parameter test passes in `backend/infrastructure`.

## Rollback

Revert the commit. Until then, keep the old GitHub variables in place so `main` can still deploy.

## Open questions

None.
