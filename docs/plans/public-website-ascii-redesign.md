# Public website redesign — ASCII cinematic single page

Developer plan for `www.lx-software.com` (`apps/public_www`). The site
described here is built. Sections 2–10 are the brief; section 11 records
the decisions that shipped.

## 1. Brief (condensed)

- One vertical page: **Who I Am**, **What I Do**, **Projects**, **Contact
  Me**, natural section heights, fixed black top nav with smooth scroll, a
  thin scroll-progress bar, a bottom bar (Privacy Policy, Terms & Conditions)
  that only appears at the end of the page.
- Retro terminal meets cinematic harbour footage: white monospace type on
  black, phosphor green `#00FF00`, amber `#FFB000`, cyan `#00FFFF` used
  sparingly; scanlines, grain, vignette, CRT curvature, blinking cursor,
  ASCII dividers, glitch — all as CSS/JS overlays, all tasteful and cheap.
- Full-screen background video of Hong Kong harbour, **pre-slowed to 0.25×
  as a rendered file**, no audio, autoplay / loop / muted / playsinline,
  `object-fit: contain` (never crop; black letterboxing), poster fallback,
  delivered from Cloudflare (R2 + CDN or Stream).
- `prefers-reduced-motion`: video paused, poster shown, effects off.
- Separate `/privacy` and `/terms` pages in the same style.
- Technical SEO + LLM SEO (`llms.txt`, FAQ, schema.org), accessibility,
  mobile-first, performance.

## 2. Current state (what the developer starts from)

| Item | Today | Plan |
|------|-------|------|
| Stack | Vite 8, React 19, React Router 7, TanStack Query 5, Bootstrap 5 (`apps/public_www`) | Keep. Repo rules require this stack; Bootstrap stays for grid/utilities and is re-themed with CSS tokens (`data-bs-theme="dark"` + overrides). |
| Routes | `/`, `/about`, `/contact`, `*` | `/` (single page), `/privacy`, `/terms`, `/wechat` (QR page). `/about` and `/contact` are dropped with no redirects. |
| Content | `public/content.json` fetched with TanStack Query | Copy lives in `src/content/site.json` and is bundled at build time. The shipped site does not use TanStack Query. |
| Footer | `NewsletterForm` (WP8 double opt-in, needs `VITE_PUBLIC_API_URL`) + copyright | Removed from the public site. The bottom bar is copyright plus Privacy Policy and Terms. |
| Hosting | S3 + CloudFront (`backend/infrastructure/lib/public-website-stack.ts`), Cloudflare DNS gray-cloud, deploy via `scripts/deploy/deploy-public-website.sh` | Unchanged for HTML/JS/CSS. Video and poster move to a Cloudflare-served media host. |
| Video | `apps/public_www/public/openrouter-video-gen-vid-…mp4` — 3.85 MB, 1280×720, 24 fps, 121 frames (5.04 s), H.264 + AAC | **Move out of `public/`** (it is copied into `dist/` and synced to S3 on every deploy and pushed to `main` already triggered **Deploy Public Website**). Keep the master at `apps/public_www/media/source/hk-harbour-master.mp4`; render the deliverables offline (§5). |

## 3. Design

### 3.1 Tokens (`src/styles/tokens.css`)

```css
:root {
  --bg: #000;
  --fg: #fff;
  --fg-dim: #b3b3b3;
  --accent-green: #00ff00;
  --accent-amber: #ffb000;
  --accent-cyan:  #00ffff;
  --overlay: rgba(0, 0, 0, .55);          /* keeps text ≥ 4.5:1 over the video */
  --font-mono: 'IBM Plex Mono', 'JetBrains Mono', ui-monospace, 'Courier New', monospace;
  --nav-h: 48px;                            /* text row, no corner mark */
  --radius-logo: 14px;
}
```

Contrast on black: white 21:1, green 15.3:1, amber 11.3:1, cyan 16.7:1. Over
the video the `--overlay` layer sits between video and content so those
ratios hold on the brightest frame (harbour sky). Accent colours are for
hover/focus, `[ ]` bracket highlights, the cursor, and the progress bar only;
body text stays white.

Fonts are self-hosted (`@fontsource/ibm-plex-mono` regular + bold, latin
subset, `font-display: swap`). No Google Fonts request.

### 3.2 Mockup (desktop, 1280 wide)

```
┌──────────────────────────────────────────────────────────────────────────┐ ← 2px progress bar (accent green), fixed
│ ┌────┐                          Who I Am   What I Do   Projects   Contact │ ← fixed nav, black, 72px
│ │ LX │                                                                   │
│ └────┘                                                                   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│        ░░░░░░░░░░░░░░░░ harbour video (contain, letterboxed) ░░░░░░░░░░  │
│                                                                          │
│   > LX SOFTWARE_                                    ← hero, cursor blinks│
│   Independent software studio, Hong Kong.                                │
│   [ scroll ↓ ]                                                           │
│                                                                          │
│ ─────────────────────── ═══ ─────────────────────── ═══ ──────────────── │ ← ASCII divider
│                                                                          │
│ ## WHO I AM                                                              │
│ Bio paragraph (placeholder). Second paragraph says the biography         │
│ will be replaced. No portrait.                                           │
│                                                                          │
│ ## WHAT I DO                                                             │
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│ │ > service 1 │ │ > service 2 │ │ > service 3 │ │ > service 4 │          │
│ │   text      │ │   text      │ │   text      │ │   text      │          │
│ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘          │
│ skills: [react] [typescript] [aws] [cdk] [python] …                      │
│                                                                          │
│ ## PROJECTS                                              ◄  ●○○○  ►      │
│ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──          │ ← horizontal scroll-snap
│ │ ▓▒░ ascii  │ │ ▓▒░ ascii  │ │ ▓▒░ ascii  │ │ ▓▒░ ascii  │ │            │   draggable, buttons
│ │ Title      │ │ Title      │ │ Title      │ │ Title      │ │            │
│ │ desc       │ │ desc       │ │ desc       │ │ desc       │ │            │
│ │ [ open → ] │ │ [ open → ] │ │ [ open → ] │ │            │ │            │
│ └────────────┘ └────────────┘ └────────────┘ └────────────┘ └──          │
│                                                                          │
│ ## CONTACT ME                                                            │
│   ┌───┐        ┌───┐        ┌───┐        ┌───┐                           │
│   │ ☏ │        │ @ │        │ W │        │ 微 │                           │
│   └───┘        └───┘        └───┘        └───┘                           │
│   [ TEL ]      [ EMAIL ]    [ WHATSAPP ]  [ WECHAT ]                     │
│                                                                          │
│ ## FAQ  (LLM SEO; collapsible <details>)                                 │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│ © 2026 LX Software                          Privacy Policy · Terms       │ ← bottom bar, in normal flow
└──────────────────────────────────────────────────────────────────────────┘
```

Mobile (390 wide): nav collapses to logo + a `[ menu ]` toggle that opens a
full-width black dropdown; the 16:9 video sits letterboxed in the middle of
the viewport with black bars above and below (this is the brief's
`object-fit: contain` choice — the video is small in portrait, the effects
and hero text carry the screen). Service cards stack; the carousel keeps
horizontal snap with one card + peek; contact icons wrap 2×2.

### 3.3 Logo and favicon

- The LX mark is the favicon and the apple touch icon. It is not in the nav. The nav is the section links only, 48px, with no bottom border. The harbour video starts at the bottom edge of that bar (`object-fit: contain`, `object-position: center top`) so there is no empty band between the nav and the picture.
- Favicon set in `public/`: `favicon.svg` (same mark), `favicon-32.png`, `apple-touch-icon.png` (180, no transparency), `site.webmanifest`, plus `og-image.png` 1200×630 (poster frame + logo + name; also the Twitter card).

### 3.4 Effects layer (`src/components/CinemaLayer.tsx` + `src/styles/effects.css`)

One fixed, `pointer-events: none`, `aria-hidden` wrapper with three
children. Everything is CSS; no per-frame JavaScript.

| Effect | Implementation | Cost control |
|--------|----------------|--------------|
| Dark overlay | `.overlay { background: var(--overlay) }` | none |
| Scanlines | `repeating-linear-gradient(0deg, transparent 0 2px, rgba(0,0,0,.25) 2px 3px)` | static |
| Film grain | SVG `feTurbulence` tile as a data-URI background on a layer with `inset: -20%`. The animation is `transform: translate3d` so it stays on the compositor | `will-change: transform`; the layer is hidden on reduced motion |
| Vignette | `radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,.8) 100%)` | static |
| CRT curvature | `border-radius: 1.5% / 2.5%` + `box-shadow: inset 0 0 120px rgba(0,0,0,.6)` on the video frame | subtle; true barrel distortion (WebGL) is out of scope |
| Cursor | `.cursor::after { content: '█'; animation: blink 1s steps(1) infinite }` | one element in the hero |
| Glitch | on `h2:hover` / `:focus-visible` and once on section enter: two `::before/::after` copies with `clip-path` keyframes and 2px accent offsets, 600 ms | `prefers-reduced-motion` removes it |
| ASCII divider | `<hr class="ascii-divider" aria-hidden>` with `::before { content: '─── ═══ ───' }` repeated via `overflow: hidden; white-space: nowrap` | static text |

Layering (z-index): video 0 → overlay 1 → scanlines/grain/vignette 2 →
content 10 → nav 20 → progress bar 30.

## 4. Front-end architecture

### 4.1 Files

```
apps/public_www/
├── index.html                      static meta, preload poster (JSON-LD injected at build)
├── media/source/hk-harbour-master.mp4   original upload (not served)
├── media/README.md                 render commands (§5)
├── scripts/site-seo.ts             JSON-LD, llms, sitemap, robots from content.json
├── public/
│   ├── content.json                extended; site.updated is the sitemap lastmod
│   ├── favicon.svg, favicon-32.png, apple-touch-icon.png, site.webmanifest
│   ├── og-image.png
│   └── media/                      harbour renditions until R2 is live
└── src/
    ├── styles/tokens.css, effects.css, site.css
    ├── components/
    │   ├── TopNav.tsx, ScrollProgress.tsx, BottomBar.tsx
    │   ├── BackgroundVideo.tsx, CinemaLayer.tsx
    │   ├── AsciiDivider.tsx
    │   ├── ProjectCarousel.tsx, ContactIcons.tsx, Faq.tsx
    ├── lib/
    │   ├── content.ts, media.ts, contact.ts, carouselIndex.ts
    │   ├── motion.ts, useActiveSection.ts, useSectionKeys.ts
    │   └── seo.ts (document.title / canonical per route)
    └── pages/home.tsx, legal.tsx, wechat.tsx, not-found.tsx
```

`robots.txt`, `sitemap.xml`, `llms.txt`, and `llms-full.txt` are emitted by
the Vite plugin. They are not tracked under `public/`.

### 4.2 Behaviour

- **Single page**: sections are `<section id="who-i-am" aria-labelledby>`
  etc. Nav links are React Router `<Link to="/#what-i-do">`. On the home
  page a click calls `navigate` when the hash changes and
  `scrollIntoView({ behavior: motionOk ? 'smooth' : 'auto' })`. A direct
  visit to `/#projects`, including from a legal page, scrolls once the
  section exists. `scroll-margin-top` on sections clears the nav.
  `useActiveSection` (IntersectionObserver, `rootMargin: -40% 0px -55%`) sets
  `aria-current="true"` on the matching link.
- **Progress bar**: `ScrollProgress` updates `transform: scaleX()` from a
  passive scroll listener wrapped in `requestAnimationFrame`.
- **Bottom bar**: ordinary `<footer>` at the end of the document — not
  sticky — so it "appears only at the end".
- **Keyboard**: `Tab` order is nav → hero → sections → carousel → footer.
  `useSectionKeys` maps `ArrowDown`/`ArrowUp` (and `j`/`k`) to next/previous
  section only when `document.activeElement` is `body` (not inside the
  carousel, a form control, or a `<details>`), so native arrow scrolling is
  only replaced when nothing has focus. Behind a `keyboardSections` flag in
  `content.json` so it can be turned off if it feels wrong.
- **Carousel** (`ProjectCarousel`): a region with `aria-roledescription="carousel"`, a `<ul>` with `scroll-snap-type: x mandatory`, `overscroll-behavior-x: contain`, cards `scroll-snap-align: start`. Mouse drag uses pointer capture (threshold 6px, suppress the card link click after a drag). Touch scrolling is left to the browser, and `pointercancel` clears a drag so snap cannot stick off. Prev/Next buttons are `disabled` at the ends. The index treats `scrollLeft` within 1px of the maximum as the last card, so Next can reach "6 of 6". `aria-live="polite"` announces the position. Card art is a brand logo (`logo` in content.json, rendered as a decorative image) when the project has one, otherwise a `<pre aria-hidden>` block from `ascii`. Accent green border and title on hover/focus-within.
- **Contact**: four items with inline SVG (`aria-hidden`) and visible ASCII labels `[ TEL ]`. Values are **build-time env**, not source (repo PII rule: phone numbers must not appear in source or docs): `VITE_CONTACT_TEL` (E.164), `VITE_CONTACT_WHATSAPP` (digits only → `https://wa.me/<digits>`), `VITE_CONTACT_EMAIL` (default `hello@lx-software.com`), `VITE_CONTACT_WECHAT_ID`, `VITE_CONTACT_LINKEDIN` (profile URL or `in/<slug>`; fifth icon). Pass them as production GitHub variables in **Deploy Public Website**. An empty telephone, WhatsApp, or LinkedIn value is a plain note, "Not configured", with no link role. WeChat: `weixin://dl/chat?<id>` is unreliable on desktop, so the icon links to `/wechat` (QR image `public/wechat-qr.png` + the ID as text); on a WeChat-capable mobile UA it tries the `weixin://` link first. The schema.org Person node comes from `content.json` `site.owner`.
- **Legal pages**: `/privacy`, `/terms` render `content.json` `legal.privacy` / `legal.terms` (array of `{ heading, paragraphs[] }`) inside the same layout: nav, cinema layer, video **paused and poster only** (legal text needs stillness), bottom bar. Placeholder text until counsel supplies copy.
- **Reduced motion / data**: `useReducedMotion` combines `matchMedia('(prefers-reduced-motion: reduce)')`, `matchMedia('(prefers-reduced-data: reduce)')`, `navigator.connection?.saveData`. When true: `<html data-motion="off">`, `BackgroundVideo` renders only `<img src=poster>`, `effects.css` zeroes every `animation` and `transition`, `scroll-behavior: auto`.

### 4.3 `BackgroundVideo.tsx`

```tsx
<div className="bg-video" aria-hidden="true">
  {motionOk ? (
    <video
      ref={ref}
      autoPlay muted loop playsInline
      preload={isMobile ? 'metadata' : 'auto'}
      poster={POSTER_URL}
      disablePictureInPicture disableRemotePlayback
      onCanPlay={() => ref.current?.play().catch(showPoster)}
    >
      {/* rendition picked in JS (matchMedia) because <source media> on <video> is not reliable */}
      <source src={pick('webm')} type="video/webm" />
      <source src={pick('mp4')}  type="video/mp4" />
    </video>
  ) : (
    <img src={POSTER_URL} alt="" />
  )}
</div>
```

- `object-fit: contain; width: 100%; height: 100%; background: #000;` on a
  `position: fixed; inset: 0` wrapper.
- iOS autoplay needs `muted` + `playsinline` (present). iOS Low Power Mode
  and some Android data-saver modes reject `play()`; the catch shows the
  poster and leaves it (no tap-to-play button — the video is decoration).
- `document.visibilitychange` and an IntersectionObserver on the hero pause
  the video when the tab is hidden; it keeps playing while scrolling because
  it is fixed behind every section.
- Browsers without `<video>` see the poster `<img>` (also the `<noscript>`).

## 5. Video pipeline (rendered offline, checked into `media/README.md`)

Source: 121 frames at 24 fps = 5.04 s. At 0.25× that is ~20 s. Plain
`setpts=4*PTS` would hold each frame four times (6 fps look); use
motion-compensated interpolation to 96 fps first, then stretch to 24 fps.
`minterpolate` is slow (2 m 43 s for this clip on 4 cores) but it runs once.
Every command below was run against the uploaded master; the measured
outputs are in the comments.

```bash
cd apps/public_www/media
mkdir -p build out

# 1. Slow to 0.25×, drop audio (the master carries an AAC track), 24 fps output
ffmpeg -i source/hk-harbour-master.mp4 -an \
  -vf "minterpolate=fps=96:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,setpts=4*PTS,format=yuv420p" \
  -r 24 -c:v libx264 -preset slow -crf 18 -movflags +faststart \
  build/hk-harbour-slow.mp4                      # measured: 19.875 s, 477 frames, no audio

# 2. Seamless loop: crossfade the last 1.5 s into the first 1.5 s so the
#    loop point is invisible. The output starts and ends on the same frame.
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 build/hk-harbour-slow.mp4)
T=$(python3 -c "print(round($D - 1.5, 3))")   # measured: 18.375
ffmpeg -i build/hk-harbour-slow.mp4 -filter_complex "
  [0:v]split[m][t];
  [t]trim=start=$T,setpts=PTS-STARTPTS[tail];
  [m]trim=end=$T,setpts=PTS-STARTPTS[main];
  [tail][main]xfade=transition=fade:duration=1.5:offset=0[v]" \
  -map "[v]" -c:v libx264 -preset slow -crf 18 -movflags +faststart \
  build/hk-harbour-loop.mp4                      # measured: 18.375 s, 441 frames

# 3. Delivery renditions (versioned filenames → immutable caching)
for h in 720 480; do
  ffmpeg -i build/hk-harbour-loop.mp4 -vf "scale=-2:${h}" \
    -c:v libx264 -profile:v high -level 4.1 -pix_fmt yuv420p -crf 23 -preset slow \
    -g 48 -keyint_min 48 -sc_threshold 0 -movflags +faststart \
    out/hk-harbour-v1-${h}.mp4
  ffmpeg -i build/hk-harbour-loop.mp4 -vf "scale=-2:${h}" \
    -c:v libsvtav1 -crf 34 -preset 6 -g 48 -pix_fmt yuv420p \
    out/hk-harbour-v1-${h}.webm
done

# 4. Poster (first frame == loop frame) and OG image base
ffmpeg -i build/hk-harbour-loop.mp4 -frames:v 1 -q:v 3 out/hk-harbour-v1-poster.jpg
ffmpeg -i build/hk-harbour-loop.mp4 -frames:v 1 -c:v libwebp -quality 80 out/hk-harbour-v1-poster.webp
```

Measured on the master (CRF 23, `-preset fast` for the check; `slow` will
be a little smaller): 720p MP4 4.4 MB, 480p MP4 2.0 MB, 480p AV1 about
1.7 MB. The checked-in AV1 files and `render.sh` use SVT `-preset 6`.
Poster JPEG 169 KB / WebP 114 KB.
The footage is a night skyline with a junk boat crossing mid-clip; frame 0
and the last frame are identical (verified with a contact sheet), and the
boat is absent at the loop point, so the crossfade only touches water and
lights. Review step: play `build/hk-harbour-loop.mp4` on loop and check
the crossfade region for ghosting on the boat's wake (interpolation
artefacts). If the ping-pong alternative (append the reversed clip) looks
better, use `-vf reverse` + `concat` instead of the xfade — it doubles the
length and is trivially seamless but the boat travels backwards.

## 6. Cloudflare setup (`docs/deployment/public-website.md` gets a "Media" section)

The site itself stays on S3 + CloudFront. Only the video and poster move.
Two options; **Option A is recommended** for a ~19 s looping clip.

### Option A — R2 + Cloudflare CDN (recommended)

1. R2 → Create bucket `lx-software-media` (location hint APAC).
2. Bucket → Settings → Custom domains → add `media.lx-software.com`
   (must be a zone on this account; Cloudflare adds the proxied CNAME).
3. Upload `out/*` with `Content-Type` set (`video/mp4`, `video/webm`,
   `image/jpeg`, `image/webp`) and
   `Cache-Control: public, max-age=31536000, immutable`. Filenames carry
   `-v1`; a re-render is `-v2`, never an overwrite.
   ```bash
   wrangler r2 object put lx-software-media/hk-harbour-v1-720.mp4 \
     --file out/hk-harbour-v1-720.mp4 --content-type video/mp4 \
     --cache-control "public, max-age=31536000, immutable"
   ```
4. Rules → Cache Rules: hostname `media.lx-software.com` → Eligible for
   cache, Edge TTL "Use cache-control header", Browser TTL "Respect origin".
   R2 serves `Accept-Ranges`, which Safari needs for `<video>`.
5. Speed → Tiered Cache: on (fewer R2 reads).
6. No CORS needed for plain `<video src>`. If hls.js is ever added, add a
   CORS policy for `https://www.lx-software.com` on the bucket.
7. R2 has no egress charge; cost is storage + Class B reads that miss the
   cache.

### Option B — Cloudflare Stream

Adaptive bitrate, HLS/DASH, thumbnails and MP4 downloads for one upload.
Use when the clip grows (longer loop, 1080p) or several renditions become a
burden.

1. Stream → Upload `build/hk-harbour-loop.mp4` (already slowed; Stream does
   not change playback speed). Note the video UID.
2. Settings: `requireSignedURLs=false`, Allowed origins
   `www.lx-software.com`, enable **MP4 downloads** (gives
   `/downloads/default.mp4` as a plain-`<video>` fallback).
3. Playback: do **not** use the Stream `<iframe>` player (it breaks
   `object-fit: contain`, overlays and autoplay control). Use the HLS
   manifest `https://customer-<code>.cloudflarestream.com/<uid>/manifest/video.m3u8`
   natively on Safari and via `hls.js` (lazy `import()`) elsewhere; poster
   from `/thumbnails/thumbnail.jpg?time=0s&height=720`.
4. Billing is per minute stored and per minute delivered; a looping
   background on every visit makes delivered minutes add up.

### Common

- CSP on the distribution (`public-website-stack.ts`):
  `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://media.lx-software.com; media-src 'self' https://media.lx-software.com; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`.
- `index.html` preloads the same-origin poster (`fetchpriority="high"`).
  A preconnect to `https://media.lx-software.com` is added only when
  `VITE_MEDIA_BASE_URL` is set. The video is `preload="metadata"` below
  900px and `preload="auto"` otherwise.
- `src/lib/media.ts` reads `VITE_MEDIA_BASE_URL` when a URL is built.
  Empty serves `/media/*` from this site. The poster stays same-origin.

## 7. SEO and LLM SEO

- `index.html` (home is the only page most crawlers and OG scrapers will
  see): `<title>`, meta description, keywords, author,
  `<link rel="canonical" href="https://www.lx-software.com/">`,
  Open Graph (`og:type=website`, `og:image` 1200×630), Twitter
  `summary_large_image`, `theme-color`, `lang="en"`. Since the 2026-09-30
  content update these are `{{token}}` placeholders filled from
  `content.json` (`site.title`, `site.description`, `site.keywords`,
  `site.owner`) by the same Vite plugin, so the head and the page copy
  cannot drift.
- JSON-LD is injected at build by the Vite plugin in `vite.config.ts`:
  `WebSite`, `Organization` + `ProfessionalService` (services as
  `makesOffer`), `Person` (from `site.owner` / `site.role`), `WebPage`, and
  `FAQPage` from `content.json`. `VITE_CONTACT_LINKEDIN` adds `sameAs` to
  the Person and Organization nodes. (`VITE_OWNER_NAME` is retired.)
- Per-route title/canonical via `seo.ts` (`useEffect`). Optional stretch:
  prerender `/privacy` and `/terms` to static HTML with `react-dom/server`
  in a `postbuild` script, plus a CloudFront Function that rewrites
  `/privacy` → `/privacy/index.html` (OAC S3 origins do not resolve index
  documents). Without it those pages still work (SPA fallback via the
  existing 403/404 → `/index.html` error responses) but share the home
  meta tags.
- `robots.txt`, `sitemap.xml` (`/`, `/privacy`, `/terms`, `/wechat`,
  `lastmod` from `content.json` `site.updated`), `llms.txt`, and
  `llms-full.txt` are emitted into `dist/` by the same plugin. They are
  not tracked under `public/`.
- Semantic HTML: one `<h1>` in the hero, `<h2>` per section, `<nav>`,
  `<main>`, `<footer>`, `<address>` around contact links, `<details>` FAQ.
  Nothing important lives only in ASCII art (`<pre aria-hidden>` always
  sits next to real text).

## 8. Performance budget

- LCP ≤ 2.5 s on a mid-range Android over 4G: poster preloaded, video
  `preload="metadata"` on mobile, fonts subset (< 60 KB total), no
  third-party scripts.
- JS ≤ 120 KB gzipped (React + Router + Query already ≈ 70 KB). No
  animation library; `hls.js` only in Option B and lazy-loaded.
- Effects layer is fixed elements with CSS animations only; measure
  with DevTools Performance — target no long tasks and paint time < 4 ms
  per frame on a 2019 laptop. `contain: paint` on the layer. Sections are
  not `content-visibility: auto`, because that changes their height after
  a hash scroll and leaves the heading in the wrong place.
- Deploy uploads `assets/` with a year-long immutable cache first, copies
  each root file on its own (`no-cache` for the shell and the SEO files),
  syncs `media/` with `--size-only`, then deletes retired hashed assets.
  One `sync --delete` of the whole tree is not used: it would cache
  `index.html` as immutable until a second copy landed.
- Lighthouse ≥ 95 Performance / 100 Accessibility / 100 SEO / 100 Best
  Practices on mobile before sign-off.

## 9. Accessibility checklist

- Every interactive element reachable by keyboard with a visible
  `:focus-visible` outline (2px accent cyan, offset 2px).
- Skip link (`Skip to content`) as the first focusable element.
- Nav: `<nav aria-label="Primary">`; active link `aria-current`.
- Carousel: region + roledescription, labelled buttons, live status, cards
  are list items, drag never the only way to move.
- Icons `aria-hidden` with adjacent text; `tel:`/`mailto:` links carry the
  human-readable value in the label.
- Video `aria-hidden` (decorative), no captions needed (no audio, no
  information).
- Reduced motion honoured (§4.2); the site is fully usable with effects
  off.
- Contrast verified over the brightest video frame with the overlay.
- Mobile menu: `[ menu ]` toggle with `aria-expanded`. Below 760px, opening the menu focuses the first link, Escape closes and returns focus, Tab cycles the links, and a pointerdown outside the menu closes it.

## 10. Work packages

| WP | Scope | Done when |
|----|-------|-----------|
| A. Media | Move master to `media/source/`, delete it from `public/`, run §5, write `media/README.md`, upload to R2 (Option A), DNS `media.lx-software.com` | Renditions play from `https://media.lx-software.com/…` with `Accept-Ranges` and immutable cache headers; loop seam reviewed |
| B. Shell | Tokens, fonts, `TopNav`, `Logo`, `ScrollProgress`, `BottomBar`, `CinemaLayer`, `BackgroundVideo`, reduced-motion hook, routes/redirects | Empty single page with video + effects, nav smooth-scrolls, reduced motion shows poster, Lighthouse a11y 100 |
| C. Sections | Who I Am, What I Do, Projects carousel, Contact icons, FAQ; `content.json` schema + placeholders; contact env vars in the deploy workflow | All content from JSON, carousel passes keyboard/drag/button tests, contact links resolve from env |
| D. Legal pages | `/privacy`, `/terms`, `/wechat` in the same layout | Pages render placeholder copy, video paused, bottom bar present |
| E. SEO | `index.html` meta, JSON-LD injected by the Vite plugin, `robots.txt`, `sitemap.xml`, `llms.txt`, `llms-full.txt` emitted into `dist/`, `seo.ts`, OG image | Rich Results test passes for Organization/WebSite/FAQPage; Person from `content.json` `site.owner`; `llms.txt` served |
| F. Infra | CSP `ResponseHeadersPolicy` in `public-website-stack.ts`, cache-control in the deploy script, GitHub variables (`VITE_CONTACT_*`, `VITE_MEDIA_BASE_URL`), docs update | `cdk diff` clean, deploy green, headers visible in production |
| G. Polish | Glitch tuning, grain density, mobile menu, performance pass, cross-browser (Safari iOS, Chrome Android, Firefox) | Budget in §8 met; iOS autoplays with muted/playsinline; Low Power Mode shows poster |

Suggested order: A in parallel with B; then C → D → E → F → G. Deploy behind
nothing — the site has no traffic-sensitive features — but keep the current
home in git history for rollback.

## 11. Decisions (29 Sep 2026)

1. **Newsletter:** removed from the public site. The board newsletter API
   stays for other clients.
2. **Video:** Option A, R2 plus two renditions. Bucket `lx-software-media`
   and `media.lx-software.com` are live (ranged GET returns 206). The
   renditions still ship on the site until `VITE_MEDIA_BASE_URL` is
   `https://media.lx-software.com` and the public site is redeployed.
3. **Loop:** crossfade.
4. **Arrow-key section jumps:** removed. The flag replaced native arrow
   scrolling and was off in `site.json`, so the hook never ran.
5. **Copy:** placeholders in `content.json`. Phone, WhatsApp, and WeChat ID
   are GitHub variables, not source.
6. **`/about` and `/contact`:** dropped. No redirects.

## 12. Risks

- `minterpolate` artefacts on fast-moving boats; mitigated by the review
  step and the ping-pong alternative.
- `object-fit: contain` on portrait phones leaves a small video in a black
  field; accepted by the brief, but the hero text and effects must carry
  the screen — check the mobile mockup early.
- iOS Low Power Mode blocks autoplay; poster fallback covers it.
- The shipped site does not use Bootstrap or TanStack Query. Colour comes
  from `src/styles/tokens.css`.
- The current `Deploy Public Website` trigger includes `apps/public_www/**`,
  so pushing the master video to `main` uploads 3.85 MB to S3 each time
  until it moves to `media/` (Vite only copies `public/`).
