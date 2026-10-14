# Plan: LinkedIn brief writer hint

**Status**: Ready
**Zone**: yellow

## Goal

Make the OpenRouter slug that writes scene, expression, and caption
visible, and give hint text after a textbox or textarea twice the
usual gap before the next field.

Those three fields are written by the same draft Model as the post
(`settings.model`, else `OPENROUTER_MODEL` / `OpenRouterModel`, default
`mistralai/mistral-medium-3`). They are not written by the Picture
model. Settings currently does not say that, and a hint under a text
control sits on the same `g-2` gutter as a field with no hint.

## Non-goals

- No separate model for the picture brief
- No change to the default draft or image slugs
- No contracts, CDK, or deploy changes

## Files

- `docs/plans/linkedin-brief-writer-hint.md` (this plan)
- `apps/admin_web/src/lib/linkedinModel.ts` — `linkedinDraftModel`
- `apps/admin_web/src/lib/linkedinModel.test.ts`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.tsx` — Model and Picture model hints
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.test.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx` — scene hint names the writer
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`
- `apps/admin_web/src/styles/tables.css` — extra gutter under a text-control hint
- `apps/admin_web/docs/UI_COMPONENTS.md` — hint spacing
- `apps/admin_web/e2e/mobile-smoke.spec.ts` — Settings and draft copy
- `docs/deployment/admin-website.md` — Model also writes the brief

## Invariants this change preserves

- Scene, expression, and caption still come from `draft_model(settings)`
- Picture model still only draws the panel
- An empty Model field still uses the stack `OpenRouterModel`
- LinkedIn rows stay on the `LINKEDIN#` prefix and out of `/records`

## Done when

- `npm run test:unit` in `apps/admin_web` covers `linkedinDraftModel` and the new hints
- `npm run lint` in `apps/admin_web` passes
- `npm run test:e2e` in `apps/admin_web` still passes
- Under `npm run dev:mock`, Settings names the writer and a hint after a
  text field has a double bottom gap

## Rollback

Revert the branch commit.

## Open questions

None.
