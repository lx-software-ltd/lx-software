# Harbour background

`source/hk-harbour-master.mp4` is the uploaded clip (1280×720, 24 fps, about
5 seconds, with an audio track that the render drops).

`render.sh` builds a silent 0.25× loop with motion-compensated interpolation
and a 1.5 second crossfade, then writes the delivery files into
`../public/media/`:

| File | Role |
|------|------|
| `hk-harbour-v1-720.mp4` / `.webm` | Desktop rendition |
| `hk-harbour-v1-480.mp4` / `.webm` | Narrow-screen rendition |
| `hk-harbour-v1-poster.jpg` / `.webp` | Poster. The WebP is also the LCP image |

The filenames carry `v1`. A new render is `v2`; do not overwrite a
published name. `media/build/` is intermediate and is not deployed.

Until `VITE_MEDIA_BASE_URL` points at Cloudflare R2, the site serves these
files from the same origin. Publishing them to R2 is
`scripts/cloudflare/publish-public-media.sh`.
