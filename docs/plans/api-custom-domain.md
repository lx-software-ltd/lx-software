# Plan: API hostname api.lx-software.com

**Status**: In review
**Zone**: red (`backend/infrastructure`, `scripts/cloudflare`, deploy workflows)

## Goal

The admin HTTP API answers on `https://api.lx-software.com`, the same
shape as findingalpha's `api.findingalpha.app`: a regional API Gateway
domain, TLS 1.2, mapped to the `$default` stage with no path prefix,
and a DNS-only Cloudflare CNAME to `ApiCustomDomainTarget`.

## Non-goals

- The admin SPA keeps calling `AdminApiBaseUrl` (the execute-api URL).
- Cloudflare does not proxy the hostname.
- The certificate is not created by the stack. It is an ACM certificate
  in ap-southeast-1, passed as `CDK_PARAM_API_CUSTOM_DOMAIN_CERTIFICATE_ARN`.

## Files

- `backend/infrastructure/lib/admin-api-domain.ts`
- `backend/infrastructure/lib/admin-http-api.ts`
- `backend/infrastructure/lib/admin-parameters.ts`
- `backend/infrastructure/params/production.json`
- `.github/workflows/deploy-backend.yml` and `cdk-diff.yml`
- `scripts/cloudflare/publish-api-domain.py`

## Invariants this change preserves

- Empty or disabled domain parameters create no domain and no mapping.
- `disableExecuteApiEndpoint` stays unset.
- `PublicApiBaseUrl`, when set, still wins over the custom hostname.
- The DNS record is not proxied and does not target the
  `<api-id>.execute-api` hostname.

## Done when

`npm test` in `backend/infrastructure` passes, and
`python3 -m unittest scripts/test_publish_api_domain.py scripts/test_agent_hooks.py`
passes. The hostname itself waits on the certificate secret and a
deploy; `publish-api-domain.py check` reports that until then.

## Rollback

Clear `ApiCustomDomainName` and `ApiCustomDomainCertificateArn` (or
remove the production secret) and deploy, then delete the `api` DNS
record. Do the deploy first so the record never points at a name that
no longer exists.

## Open questions

None. The cloud agent cannot request the ACM certificate or create the
API Gateway domain. Those happen on the next backend deploy after the
secret is set.
