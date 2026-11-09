# Plan: Clear Deploy Admin Web build warnings

**Status**: Done
**Zone**: red (deploy workflow, owner-requested) and yellow (`apps/admin_web/src`)

## Goal

Remove the two actionable warnings from the Deploy Admin Web run:
the npm `EBADENGINE` warning (jest-dom needs Node 22 or newer, but the workflow pins Node 20),
and the Vite warning about a chunk over 500 kB (the entry chunk was 892 kB).

## Non-goals

- Pinning the runner image. Later pinned in `docs/plans/pin-ci-runners.md`.
- Raising `chunkSizeWarningLimit`.

## Files

- `.github/workflows/deploy-admin-web.yml`: `node-version: "lts/*"`, matching the other workflows.
- `apps/admin_web/src/pages/StatementBookPage.tsx`: lazy-load the Executive Board, LinkedIn and Resume tabs inside `LazyPage`.

## Invariants this change preserves

- Every tab renders the same content. It shows the shared `LazyPage` loading line until its chunk arrives.
- A chunk that fails to load is caught by `RouteErrorBoundary`.

## Done when

`npm run build` prints no chunk-size warning, and `npm run lint`, `tsc --noEmit` and `npm run test:unit` pass.

## Rollback

Revert the commit.

## Open questions

None.
