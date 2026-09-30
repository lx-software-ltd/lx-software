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
the JSON-LD block, and the `<title>` / meta / Open Graph tags in `index.html`
from `public/content.json` (`{{token}}` placeholders in `index.html`). The
JSON-LD graph is `WebSite`, `Organization` + `ProfessionalService` (with the
services as `makesOffer`), `Person` (from `site.owner` / `site.role`),
`WebPage`, and `FAQPage`. `VITE_CONTACT_LINKEDIN` adds the LinkedIn contact
icon and the `sameAs` links.

## Content

Edit `public/content.json` for the title, description, keywords, biography,
services, projects, FAQ, and the legal pages. `site.updated` is the sitemap
`lastmod`. A project with a `url` gets an `[ open ]` link; one with an empty
`url` and a `status` shows the status instead.

## Lighthouse

`.lighthouserc.json` is used by the manual **Lighthouse Public Website**
workflow. Run it locally with a built `dist/`:

```bash
npx @lhci/cli autorun
```

## Video

See `media/README.md`. Cloudflare R2 publishing is
`scripts/cloudflare/publish-public-media.sh`.
