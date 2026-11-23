# Plan: LinkedIn video review fixes

**Status**: Done
**Zone**: yellow

## Goal

A redraw keeps the LinkedIn video id with the held clip. A video LinkedIn is
still processing does not take the publish slot, does not send a failure
email, and does not stop the three-hour reminder. The browser budget for a
re-encoded clip includes the audio, and an iPad recorder's MP4 brand is
accepted when the codec is H.264.

## Non-goals

- No server-side transcode and no new HTTP route
- No change to the 1.5 MB cap for a stored PNG or JPEG
- The part upload still sends no Authorization header. LinkedIn's upload URL
  is pre-signed; the image upload is the call that sends the token

## Files

- `docs/plans/linkedin-gif-video-review.md` (this plan)
- `docs/plans/linkedin-gif-video.md` (brand rule)
- `docs/deployment/admin-website.md`
- `backend/lambda/admin/linkedin_image.py`
- `backend/lambda/admin/linkedin_video.py`
- `backend/lambda/admin/linkedin.py`
- `backend/lambda/admin/linkedin_store.py`
- `backend/lambda/admin/test_linkedin_video.py`
- `apps/admin_web/src/lib/fitLinkedInVideo.ts`
- `apps/admin_web/src/lib/fitLinkedInVideo.test.ts`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`
- `scripts/file-length-allowlist.txt` when a listed file shrinks

## Invariants this change preserves

- One successful publish per tick
- A video that is still processing does not use a publish attempt
- A stored PNG or JPEG stays at or under 1.5 MB
- `public_image` does not return the LinkedIn video id or the owner it belongs to
- A real publish failure still counts as an attempt and still sends the failure email

## Done when

- `python3 -m unittest test_linkedin_video.py` in `backend/lambda/admin` passes
- `npx vitest run src/lib/fitLinkedInVideo.test.ts src/components/linkedin/LinkedInDraftsSection.test.tsx` in `apps/admin_web` passes
- `npx playwright test e2e/linkedin-image-resize.spec.ts --project=desktop` in `apps/admin_web` passes
- `npm run lint` in `apps/admin_web` passes
- `python3 -m ruff check` on the touched Lambda modules passes

## Rollback

Revert the commit that fixes the video review.

## Open questions

None.
