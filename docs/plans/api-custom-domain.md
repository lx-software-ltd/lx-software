# Plan: API hostname api.lx-software.com

**Status**: Done. The one-off Cloudflare publisher was removed after the record was published.
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

## Invariants this change preserves

- Empty or disabled domain parameters create no domain and no mapping.
- `disableExecuteApiEndpoint` stays unset.
- `PublicApiBaseUrl`, when set, still wins over the custom hostname.
- The DNS record is not proxied and does not target the
  `<api-id>.execute-api` hostname.

## Done when

`npm test` in `backend/infrastructure` passes. The hostname is the
API Gateway domain `api.lx-software.com`, with a DNS-only CNAME in
Cloudflare. No publisher script remains in the repository.

## Rollback

Clear `ApiCustomDomainName` and `ApiCustomDomainCertificateArn` (or
remove the production secret) and deploy, then delete the `api` DNS
record. Do the deploy first so the record never points at a name that
no longer exists.

## Open questions

None.
