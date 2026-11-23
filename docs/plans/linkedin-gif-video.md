# Plan: LinkedIn GIF and iPad video

**Status**: Done
**Zone**: yellow

## Goal

A draft can take a GIF or a video chosen on an iPad, not only a PNG or JPEG.
A GIF stays a GIF and is posted through the Images API. An iPad camera clip
(usually a QuickTime movie) is prepared in the browser as an H.264 MP4 and
posted through the Videos API once LinkedIn has finished processing it.

## Non-goals

- No server-side transcode and no new HTTP route
- No change to the 1.5 MB cap for a stored PNG or JPEG
- Character photos stay PNG or JPEG
- No multi-image post, captions file, or custom thumbnail
- Sound on a clip the browser has to re-encode is best-effort. An MP4 already
  under the cap is stored unchanged, soundtrack included

## Files

- `docs/plans/linkedin-gif-video.md` (this plan)
- `docs/deployment/admin-website.md`
- `apps/admin_web/src/lib/linkedinModel.ts`
- `apps/admin_web/src/lib/fitLinkedInImage.ts`
- `apps/admin_web/src/lib/fitLinkedInVideo.ts`
- `apps/admin_web/src/lib/fitLinkedInImage.test.ts`
- `apps/admin_web/src/lib/fitLinkedInVideo.test.ts`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`
- `apps/admin_web/src/lib/mock/routes/linkedin.ts`
- `backend/lambda/admin/linkedin_media.py`
- `backend/lambda/admin/linkedin_video.py`
- `backend/lambda/admin/linkedin_store.py` (delegate the byte check; do not grow)
- `backend/lambda/admin/linkedin.py` (publish through the video helper; do not grow)
- `backend/lambda/admin/test_linkedin_media.py`
- `backend/lambda/admin/test_linkedin_video.py`
- `scripts/file-length-allowlist.txt` (lower the entries that shrink)

## Invariants this change preserves

- A stored PNG or JPEG stays at or under `IMAGE_BYTE_MAX`, with the same magic bytes
- A character photo is still rejected unless it is a PNG or JPEG
- A GIF is not re-encoded to JPEG
- Rows stay on the `LINKEDIN#` prefix
- `public_image` does not return the LinkedIn video URN
- A video that LinkedIn is still processing does not use a publish attempt

## Limits

- GIF and stored MP4: 3 MB, so the base64 JSON body stays under the API Gateway and Lambda response caps
- Browser will open a source video up to 80 MB, then re-encode clips longer than a pass-through MP4
- Pass-through only when the MP4 major brand is `isom`, `iso2`, `mp41`, `mp42`, `avc1`, or `M4V `
- Re-encode is 3 to 90 seconds. A pass-through MP4 may be up to 30 minutes
- LinkedIn's own floor is 75 KB and 3 seconds

## Done when

- `python3 -m unittest test_linkedin_media.py test_linkedin_video.py` in `backend/lambda/admin` passes
- `npm run test:unit`, `npm run lint`, and `npm run build` in `apps/admin_web` pass
- `python3 -m ruff check backend/lambda/admin/linkedin_media.py backend/lambda/admin/linkedin_video.py backend/lambda/admin/linkedin.py backend/lambda/admin/linkedin_store.py` passes
- The mock draft accepts a GIF and an MP4 in the browser

## Rollback

Revert the commit that adds GIF and video attachments.

## Open questions

None.
