# Plan: LinkedIn iPad image read

**Status**: Done
**Zone**: yellow

## Goal

An iPad photo over 1.5 MB currently fails with "The picture could not be read."
Safari cannot turn a full-size camera original into a JPEG in one canvas draw,
and `canvas.toBlob` often returns null. Decode and scale that photo so the
upload still stores a JPEG under `IMAGE_BYTE_MAX`.

## Non-goals

- No change to the 1.5 MB stored cap
- No server-side image decode
- No new image types stored (HEIC is re-encoded to JPEG before save)

## Files

- `docs/plans/linkedin-ipad-image-read.md` (this plan)
- `apps/admin_web/src/lib/fitLinkedInImage.ts`
- `apps/admin_web/src/lib/fitLinkedInImage.test.ts`
- `apps/admin_web/src/lib/linkedinModel.ts` — file-input accept list
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInSettingsCard.tsx`
- `docs/deployment/admin-website.md`

## Invariants this change preserves

- Stored pictures stay at or under `IMAGE_BYTE_MAX`
- A resized PNG stays a JPEG on a white matte
- JPEG quality stays at or above 0.7
- LinkedIn rows stay on the `LINKEDIN#` prefix

## Done when

- `npm run test:unit` in `apps/admin_web` covers a null `toBlob`, an iPad-sized
  step-down, `image/jpg`, and HEIC re-encoded to JPEG
- `npm run lint` and `npm run build` in `apps/admin_web` pass

## Rollback

Revert the commit that changes `fitLinkedInImage` for iPad decode.

## Open questions

None.
