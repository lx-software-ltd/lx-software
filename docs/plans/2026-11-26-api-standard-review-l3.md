# Plan: second-round API review on L3

**Status**: Done
**Zone**: red for the admin web stack wiring and `scripts/deploy/check-admin-spa-settings.sh`. The review approves those edits.

## Goal

Import only the resolved admin API origin into the admin web template. Keep the authorizer cache at 60 seconds with `Authorization` and source IP. The deploy settings script rejects an `AdminApiBaseUrl` that contains `execute-api`.

## Non-goals

Do not edit `wire_format.py` or `wireFormat.ts`. Do not set the authorizer cache to zero. Do not export the disabled execute-api URL as a second CSP origin.

## Files

- `backend/infrastructure/bin/app.ts` and `lib/admin-http-api.ts`
- `backend/infrastructure/test/lxsoftware-app-conditions.test.ts`
- `scripts/deploy/check-admin-spa-settings.sh`
- `docs/plans/2026-11-26-board-alias-wire-cache.md`

## Invariants this change preserves

- `UseApiCustomDomain` stays in the API stack. The admin web imports `lxsoftware-AdminApiBaseUrl`.
- The authorizer identity source is `Authorization` plus source IP, and `AuthorizerResultTtlInSeconds` stays 60.
- The deploy script does not fetch a config.json. It fails when the resolved API URL contains `execute-api`.

## Done when

`npm test` and `npm run build` in `backend/infrastructure` pass. The deploy settings script rejects an execute-api `AdminApiBaseUrl`.

## Rollback

Revert this commit. The admin web would import a second origin.

## Open questions

None.
