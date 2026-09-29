# LX Software public website

Single-page site: black background, monospace type, a slowed silent harbour
video, and four sections (Who I Am, What I Do, Projects, Contact Me).
Privacy Policy and Terms & Conditions are separate pages.

## Getting started

```bash
npm install
npm run dev
```

The dev server is `http://localhost:5173/`. Copy `.env.example` if you want
contact links or a Cloudflare media host. With the variables empty, telephone
and WhatsApp render as disabled icons and the video is served from
`public/media/`.

## Build

```bash
npm run build
npm run preview
```

`prebuild` regenerates `public/llms.txt`, `public/llms-full.txt`,
`public/sitemap.xml`, `public/robots.txt`, and the JSON-LD block in
`index.html` from `public/content.json`.

## Content

Edit `public/content.json` for the biography, services, projects, FAQ, and
the draft legal pages. Re-run `node scripts/generate-seo.mjs` (or `npm run
build`) afterwards.

## Video

See `media/README.md`. Cloudflare R2 publishing is
`scripts/cloudflare/publish-public-media.sh`.
