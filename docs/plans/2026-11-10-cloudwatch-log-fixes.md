# Plan: CloudWatch log fixes

**Status**: Implemented
**Zone**: yellow

## Goal

Stop the failures seen in the last five days of CloudWatch logs for this stack:

- A staff tick hung until the 300s Lambda cap after a GitHub call, and code ticks failed on `RemoteDisconnected` / `IncompleteRead`.
- Staff steps failed with `OpenRouter request timed out: wall-clock budget exhausted` because one slow model used the whole budget and the client did not walk to the fallback.
- Competitor crawls kept fetching hosts that present a bad certificate or stay `EBUSY`.

## Non-goals

- Dead-letter queues in the Evolve Sprouts and Siu Tin Dei stacks, API-key rotation, and the URL-encoding bugs in `AwsApiProxyFunction`. Those services are not in this repository.
- Public board `404`/`400` responses for paths the API does not expose.
- Raising `staffStepMaxSeconds` or any other contract.

## Files

- `backend/lambda/admin/board_github.py` and `board_github_http.py`
- `backend/lambda/admin/openrouter_client.py` and `openrouter_fallback.py`
- `backend/lambda/admin/board_staff.py` and `board_staff_tokens.py`
- `backend/lambda/admin/board_crawl.py`
- `backend/lambda/admin/board_intel.py`
- Tests next to those modules.

## Invariants this change preserves

- GitHub writes are not retried.
- Rate-limit errors are not retried.
- A staff step that has no fallback model still uses its full wall-clock budget.
- A certificate failure is not treated as a busy file and retried.
- Personas still see aliases; no new routes; no contract edits.

## Done when

`python3 -m unittest` for the touched admin tests passes.

## Rollback

Revert the commit. No data migration.

## Open questions

None.
