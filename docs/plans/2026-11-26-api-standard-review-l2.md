# Plan: second-round API review on L2

**Status**: Done
**Zone**: yellow for the admin Lambda and the admin fixture. Red for the HTTP API, the authorizer, and `contracts/wire-format.json`. The review approves those infrastructure and contract edits.

## Goal

Keep CloudFormation conditions inside the stack that defines them. Stop the public API authorizer from reusing one IP's approval. Call the siutindei import routes under `/v1/admin`. Keep the stored Evolve Sprouts refund marker. Let `past_due` survive a wire round trip. Report a missing findingalpha checkout instead of hiding a hardcoded path.

## Non-goals

Do not edit `wire_format.py` or `wireFormat.ts`. Do not change findingalpha. Do not set the L3 authorizer cache to zero. L3 still lists the custom domain alone in the CSP.

## Files

- `backend/infrastructure/bin/app.ts`, `lib/admin-http-api.ts`, and the stack test
- `backend/infrastructure/lib/admin-api-authorizers.ts` and the authorizer assertion
- `backend/lambda/admin/board_catalog_import.py` and its test
- `backend/lambda/admin/evolvesprouts_finance.py` and the admin fixture
- `contracts/wire-format.json` (synced copies)
- `scripts/check-contracts.py`
- The AWS usage path in `aws_billing.py`, `docs/deployment/admin-website.md`, and `backend/infrastructure/params/README.md`
- `docs/plans/2026-11-26-board-alias-wire-cache.md`

## Invariants this change preserves

- The two-origin CSP stays on this branch: custom domain plus execute-api while the custom domain is on, and execute-api alone when it is off.
- The identity source stays source IP. The result cache TTL becomes 0 because that key is the IP alone.
- `SiutindeiAdminApiBaseUrl` stays the origin `https://api.siutindei.com`. The client appends `/v1/admin/...`.
- The refund line marker stays `[evolve-sprouts]`.
- Codec bytes stay identical to findingalpha commit `d61ab99df00e99df1b649f36a08fab6b9e48ad4d`. `bySubscription` and `byOnboardingStep` are product map fields in this repo's contract. findingalpha's `wire-format.json` is a different product file and is not byte-checked.

## Done when

The new condition test fails before the import fix and passes after it. `npm test` and `npm run build` in `backend/infrastructure` pass. The catalog import test asserts the full presign and import URLs. `python3 scripts/check-contracts.py` passes and prints the skip line when the checkout is absent.

## Rollback

Revert this commit. The admin web template names `UseApiCustomDomain` again, and the authorizer caches by IP for 60 seconds.

## Open questions

None.
