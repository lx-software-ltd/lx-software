# Plan: second-round API review on L3

**Status**: Done
**Zone**: red for the admin web stack wiring and `scripts/deploy/check-admin-spa-settings.sh`. The review approves those edits. Green for the SPA config checker.

## Goal

Import only the resolved admin API origin into the admin web template. Keep the authorizer cache at 60 seconds with `Authorization` and source IP. Run the admin SPA config check from the deploy settings script, and refuse a non-https redirect.

## Non-goals

Do not edit `wire_format.py` or `wireFormat.ts`. Do not set the authorizer cache to zero. Do not export the disabled execute-api URL as a second CSP origin.

## Files

- `backend/infrastructure/bin/app.ts` and `lib/admin-http-api.ts`
- `backend/infrastructure/test/lxsoftware-app-conditions.test.ts`
- `scripts/check_admin_spa_config.py`, its test, and `scripts/deploy/check-admin-spa-settings.sh`
- `docs/plans/2026-11-26-board-alias-wire-cache.md`

## Invariants this change preserves

- `UseApiCustomDomain` stays in the API stack. The admin web imports `lxsoftware-AdminApiBaseUrl`.
- The authorizer identity source is `Authorization` plus source IP, and `AuthorizerResultTtlInSeconds` stays 60.
- An unset `ADMIN_SPA_CONFIG_URL` still skips the live config check.

## Done when

`npm test` and `npm run build` in `backend/infrastructure` pass. `python3 -m unittest discover -s scripts -p 'test_check_admin_spa_config.py' -v` passes, including `file://` and an http redirect with no network.

## Rollback

Revert this commit. The admin web would import a second origin, and the deploy script would stop running the Python config check.

## Open questions

None.
