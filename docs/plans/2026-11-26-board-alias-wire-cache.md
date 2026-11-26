# Plan: board alias and wire cache

**Status**: Done
**Zone**: red for the authorizer, the HTTP API routes, and the authorizer identity source. The task names those files. Yellow for the admin Lambda and the admin client.

## Goal

Keep the previous board paths and `x-api-key` working for one deploy. Cache the wire contract. Pass the request path into the admin client's `fromWire`. Fail the contract check if the shared codec bytes drift from findingalpha.

## Non-goals

Do not edit `wire_format.py` or `wireFormat.ts`. Do not remove the Meta webhook aliases on this branch. Do not change `_require_admin` or `write_blocked`.

## Files

- `backend/lambda/admin/http_common.py` and its tests
- `backend/lambda/public_api_authorizer/handler.py` and `test_handler.py`
- `backend/infrastructure/lib/admin-api-routes.ts`, `admin-api-authorizers.ts`, `admin-http-api.ts`, and the stack test
- `docs/api/partner.yaml`, `docs/api/legacy-paths.txt`
- `apps/admin_web/src/lib/apiAdminClient.ts` and its test
- `scripts/check-contracts.py`
- `.cursor/skills/add-admin-route/SKILL.md`

## Invariants this change preserves

- `dispatch.py` stays at 1344 lines. The old board path is rewritten in `legacy_http_path`.
- New `/v1/partner/siutindei/board` responses stay snake_case.
- This branch lists `Authorization` and source IP, and the authorizer cache stays 60 seconds. A cache keyed only by source IP used a TTL of 0, because that key would reuse one caller's approval for every request from the address.
- The identity source lists both credential headers or neither.

## Done when

The authorizer tests, the wire tests, `npm test` in `backend/infrastructure`, and the API contract checker on `docs/api` pass. The checker reports no findings.

## Rollback

Revert this commit. Old board callers start receiving 404, and the authorizer accepts only Bearer.

## Open questions

None. The cache key omits both headers because HTTP API requires every listed identity source to be present, and callers send one header.
