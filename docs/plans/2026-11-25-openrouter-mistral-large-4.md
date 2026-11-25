# Plan: Move OpenRouter default to Mistral Large 4

**Status**: Done
**Zone**: red (CDK parameter and production params) plus yellow
(statement-parser fallback and admin mock defaults)

## Goal

Replace the retired `mistralai/mistral-medium-3` slug with
`mistralai/mistral-large-4-0` so statement parse (and the LinkedIn /
resume fallback when Settings is blank) stops 404ing on OpenRouter.

## Non-goals

- No change to Executive Board chat / meeting / deep-dive models.
- No LinkedIn Settings override stored in DynamoDB.
- No PDF-engine change (`mistral-ocr` stays).

## Files

- `backend/infrastructure/lib/admin-parameters.ts`
- `backend/infrastructure/params/production.json`
- `backend/infrastructure/params/README.md`
- `backend/lambda/admin/openrouter_statement_parser.py`
- Admin mock / tests / docs that echo the stack default

## Invariants this change preserves

- `OPENROUTER_MODEL` remains one stack slug for statement parse, LinkedIn
  drafts, and resume when Settings leave the model blank.
- LinkedIn Settings can still pin a different slug.
- The file-parser plugin and `OpenRouterPdfEngine` are unchanged.

## Done when

- CDK default and `lxsoftware:OpenRouterModel` in production params are
  `mistralai/mistral-large-4-0`.
- Admin unit tests and the mock API agree on that slug.
- `python3 -m unittest` for the LinkedIn default-model test and
  `npm run test:unit` in `apps/admin_web` pass.

## Rollback

Set `lxsoftware:OpenRouterModel` (and the CDK default) back to a live
OpenRouter slug and redeploy.

## Open questions

None. OpenRouter still serves `mistralai/mistral-large-4-0`.
