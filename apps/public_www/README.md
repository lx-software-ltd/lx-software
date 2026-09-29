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
and WhatsApp show "Not configured" and the video is served from
`public/media/`.

## Build and test

```bash
npm test
npm run build
npm run preview
```

The Vite build emits `llms.txt`, `llms-full.txt`, `sitemap.xml`, `robots.txt`,
and the JSON-LD block in `index.html` from `public/content.json`. A Person
node is included only when `VITE_OWNER_NAME` is set.

## Content

Edit `public/content.json` for the biography, services, projects, FAQ, and
the draft legal pages. `site.updated` is the sitemap `lastmod`.

## Video

See `media/README.md`. Cloudflare R2 publishing is
`scripts/cloudflare/publish-public-media.sh`.
