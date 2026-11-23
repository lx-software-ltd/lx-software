# Plan: Type-check every Node app

**Status**: Draft
**Zone**: yellow

## Goal

`lint.yml` type-checks every package that depends on TypeScript, and the `lint` gate waits for that job.

## Apps

Measured 22 Nov 2026. No errors.

| App | Command | Errors |
| --- | --- | --- |
| `apps/admin_web` | `tsc --noEmit -p tsconfig.app.json` and `tsc --noEmit -p tsconfig.node.json` | 0 |
| `apps/public_www` | same | 0 |
| `backend/infrastructure` | `tsc --noEmit` | 0 |

`apps/admin_web` and `apps/public_www` use a solution `tsconfig.json` that only lists project references. `tsc --noEmit` with no `-p` lists zero files and does not check `src`. The `typecheck` script checks both referenced projects.

## Non-goals

No mypy, no coverage floor, and no OpenAPI lint.

## Files

The three `package.json` scripts, `.github/workflows/lint.yml`, and this plan.

## Invariants this change preserves

The `lint` job id and its display name stay `lint`. Node stays on the `setup-node` default.

## Done when

The `lint` gate lists `type-check`, and that job runs `npm run typecheck` in each app above.

## Rollback

Revert this pull request.

## Open questions

None.
