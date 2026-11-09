# Plan: Clear today's remaining CI warnings

**Status**: Done
**Zone**: yellow

## Goal

Close `urllib.error.HTTPError` after the admin Lambda reads it, and move the finance-quotes Vitest mock to module scope.

Today's GitHub Actions logs (74 runs, 9 November 2026 Hong Kong) still print two warnings on current `main`:

- Python 3.14 `ResourceWarning: Implicitly cleaning up <HTTPError ...>` during the admin unit tests. `HTTPError` is a temporary-file wrapper and must be closed.
- Vitest: `vi.mock("./auth")` inside `beforeEach` in `financeQuotes.test.ts`. The call is hoisted, and a future Vitest will reject the nested call.

## Non-goals

- Pinning `ubuntu-latest`. The runner image is already Ubuntu 26.04. The migration notice is GitHub's, and several workflows that use the label are red-zone.
- Re-fixing `glob@10.5.0`, npm `allowScripts`, and the admin Node engine warning. Later runs today no longer print them.
- Dependabot's `ca-certificates.crt` rehash line. It comes from Dependabot's updater, not this repo.
- CodeQL's one-off bundle 504. The action already falls back and the job succeeded.

## Files

- `backend/lambda/admin/*.py` HTTP error handlers (`board_catalog_import`, `board_crawl`, `board_github`, `board_meta`, `board_places`, `board_research`, `board_stores`, `bank_sync`, `linkedin_api`, `openrouter_client`, `openrouter_usage_pull`, `proxies`)
- Tests that already raise `HTTPError`: `test_board_catalog_import.py`, `test_board_tools.py`, `test_board_wp2.py`, `test_board_wp7.py`, `test_openrouter_client.py`
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
