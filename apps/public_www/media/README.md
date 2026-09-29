# Harbour background

`source/hk-harbour-master.mp4` is the uploaded clip (1280×720, 24 fps, about
5 seconds, with an audio track that the render drops).

`render.sh` builds a silent 0.25× loop with motion-compensated interpolation
and a 1.5 second crossfade, then writes the delivery files into
`../public/media/`:

| File | Role |
|------|------|
| `hk-harbour-v1-720.mp4` / `.webm` | Desktop rendition. AV1 is SVT preset 6 |
| `hk-harbour-v1-480.mp4` / `.webm` | Narrow screens play the MP4 only. The webm is rendered and not selected |
| `hk-harbour-v1-poster.jpg` / `.webp` | Poster. The WebP is also the LCP image |

The filenames carry `v1`. A new render is `v2`; do not overwrite a
published name. `media/build/` is intermediate and is not deployed.

The same files are already on R2 at `https://media.lx-software.com`. The
site keeps serving them from this origin until `VITE_MEDIA_BASE_URL` is
that host and the public site is redeployed. Republishing is
`scripts/cloudflare/publish-public-media.sh`. The token needs Workers R2
Storage edit permission. A failed custom-domain attach stops the script.

## After R2 is verified

The page preloads the posters from this origin, so those files stay in
`public/media/`. Once a ranged GET of the 720p MP4 returns 206, the video
renditions and the master can leave git. The publish script prints the
`git rm` lines. Do not rewrite history with Git LFS; converting existing
blobs without a history rewrite only makes clones larger.
