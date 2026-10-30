# Plan: Resume OpenRouter key

**Status**: Done
**Zone**: red for `contracts/openrouter-apps.json`. The implement request covers that write.

## Goal

Resume model calls use a named inference key, the same way LinkedIn does. The catalog id is `resume`, the OpenRouter key name is `lxsoftware:resume`, and the admin secret field is `resume`.

## Non-goals

Minting the key or writing Secrets Manager from this change. The owner runs **Actions → Mint OpenRouter App Keys** and merges the `resume` field into the existing secret.

## Files

- `contracts/openrouter-apps.json` and the copies `scripts/sync-contracts.py` writes
- `backend/lambda/admin/test_openrouter_usage.py`, `scripts/test_mint_openrouter_app_keys.py`
- `docs/deployment/admin-website.md`, `backend/infrastructure/params/README.md`, `backend/infrastructure/lib/admin-parameters.ts`

## Invariants this change preserves

One OpenRouter invoice. Each catalog app keeps its own key. `management` stays a Management API key. Resume still books usage as service `resume`.

## Done when

`python3 scripts/sync-contracts.py` and `python3 scripts/check-contracts.py`. `python3 -m unittest test_openrouter_usage.py test_openrouter_client.py` in `backend/lambda/admin`. `python3 scripts/test_mint_openrouter_app_keys.py`.

## Rollback

Remove the catalog row and redeploy. Leave the secret field in place; it is unused once the code no longer asks for it.

## Open questions

None. The owner mints `lxsoftware:resume` after this merges and pastes that value into the `resume` field.
