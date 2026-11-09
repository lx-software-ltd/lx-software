# Plan: Clear today's remaining CI warnings

**Status**: Done
**Zone**: yellow

## Goal

Close `urllib.error.HTTPError` after the admin Lambda reads it, and move the finance-quotes Vitest mock to module scope.

Today's GitHub Actions logs (74 runs, 9 November 2026 Hong Kong) still print two warnings on current `main`:

- Python 3.14 `ResourceWarning: Implicitly cleaning up <HTTPError ...>` during the admin unit tests. `HTTPError` is a temporary-file wrapper and must be closed.
- Vitest: `vi.mock("./auth")` inside `beforeEach` in `financeQuotes.test.ts`. The call is hoisted, and a future Vitest will reject the nested call.

## Non-goals

- Pinning `ubuntu-latest`. That is `docs/plans/pin-ci-runners.md`. CodeQL's streaming download has no switch in `codeql-action` v4.
- Re-fixing `glob@10.5.0`, npm `allowScripts`, and the admin Node engine warning. Later runs today no longer print them.
- Dependabot's `rehash` line. It is printed by GitHub's updater image, not this repo.

## Files

- `backend/lambda/admin/http_common.py` reads and closes the `HTTPError`. The handlers call it. The eight files already over the length ceiling stay at the recorded length.
- Tests that already raise `HTTPError`: `test_board_catalog_import.py`, `test_board_tools.py`, `test_board_wp2.py`, `test_board_wp7.py`, `test_openrouter_client.py`, `test_http_common.py`
- `apps/admin_web/src/lib/financeQuotes.test.ts`
- `.github/workflows/security.yml` — retry the gitleaks download. One run today failed with curl exit 22 on a GitHub 504. This file is not a red-zone workflow.

## Invariants this change preserves

- Error bodies and status codes stay the same. `close()` runs after `read()`.
- A 404 GitHub GET still returns `None`. Rate-limit waits stay the same.
- The finance quotes tests still stub `ensureFreshTokens` for every case.

## Done when

- `python3 -m unittest` for the touched admin test modules passes, and those tests assert `HTTPError.fp.closed`.
- `npx vitest run src/lib/financeQuotes.test.ts` in `apps/admin_web` passes with no nested-mock warning.

## Rollback

Revert the commit. No data or contract change.

## Open questions

None.
