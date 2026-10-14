# Plan: LinkedIn draft image resize

**Status**: Ready
**Zone**: yellow

## Goal

Stop rejecting a PNG or JPEG over 1.5 MB on LinkedIn draft (and character)
upload. The console resizes the photo in the browser so the stored file stays
under `IMAGE_BYTE_MAX`.

## Non-goals

- No change to the 1.5 MB stored cap (`IMAGE_BYTE_MAX`)
- No Lambda, API Gateway, or LinkedIn API payload change
- No new image types (still PNG and JPEG)
- No contracts or CDK

## Files

- `docs/plans/linkedin-draft-image-resize.md` (this plan)
- `apps/admin_web/src/lib/linkedinModel.ts` — mirrored `IMAGE_BYTE_MAX`
- `apps/admin_web/src/lib/linkedinModel.test.ts`
- `apps/admin_web/src/lib/fitLinkedInImage.ts` — pass-through or shrink
- `apps/admin_web/src/lib/fitLinkedInImage.test.ts`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.tsx`
- `docs/deployment/admin-website.md` — why 1.5 MB, and that the SPA resizes

## Invariants this change preserves

- Stored pictures stay at or under `IMAGE_BYTE_MAX` (1_500_000)
- Frontend `IMAGE_BYTE_MAX` stays the same number as `linkedin_store.py`
- Upload is still PNG or JPEG, sent as `contentType` + `dataBase64`
- LinkedIn rows stay on the `LINKEDIN#` prefix and out of `/records`
- Generated comics still use `_png_under_limit` on the worker

## Done when

- `npm run test:unit` in `apps/admin_web` covers pass-through, shrink, and a
  draft file over 1.5 MB that still uploads
- `npm run lint` in `apps/admin_web` passes
- Under `npm run dev:mock`, attaching a JPEG over 1.5 MB to a draft succeeds

## Rollback

Revert the branch commit that adds `fitLinkedInImage`.

## Open questions

None.
