# Plan: drop the board alias

**Status**: Done
**Zone**: red for the authorizer and the HTTP API routes. The task names those files.

## Goal

Remove the one-deploy board aliases and `x-api-key` acceptance. Keep the three sent email paths. The deploy script rejects an `AdminApiBaseUrl` that contains `execute-api`. It does not fetch a config.json.

## Non-goals

Do not remove `DisableExecuteApiEndpoint` or its preconditions. Do not edit `wire_format.py` or `wireFormat.ts`. Do not resurrect the Meta routes.

## Files

- `backend/lambda/admin/http_common.py` and `test_wire_http.py`
- `backend/lambda/public_api_authorizer/handler.py` and `test_handler.py`
- `backend/infrastructure/lib/admin-api-routes.ts`, `admin-api-authorizers.ts`, `admin-http-api.ts`, and the stack test
- `docs/api/partner.yaml`, `docs/api/legacy-paths.txt`
- `scripts/deploy/check-admin-spa-settings.sh`

## Invariants this change preserves

- `dispatch.py` stays at 1344 lines.
- The authorizer cache stays 60 seconds and includes source IP. The identity source is `Authorization` and source IP.
- When the custom domain is off, the execute-api URL keeps working.

## Done when

The authorizer tests, the wire tests, `npm test` in `backend/infrastructure`, and the API contract checker on `docs/api` pass.

## Rollback

Revert this commit. The old board URL and `x-api-key` start working again.

## Open questions

None.
