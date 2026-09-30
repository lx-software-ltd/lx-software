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

## Analytics

`VITE_GTM_ID` (a `GTM-XXXXXXX` container id) makes `src/lib/gtm.ts` load
Google Tag Manager; GA4 is configured inside that container. Empty means no
Google script is requested. Browsers sending Global Privacy Control or Do
Not Track are never tracked.

`src/lib/analytics.ts` pushes the site's own events onto `dataLayer`
(`contact_click`, `faq_toggle`, `project_open`, `project_navigate`,
`nav_click`, `page_not_found`, `media_error`) only after the container
loaded. GA4 enhanced measurement covers page views, scroll, outbound
clicks and downloads on its own. `scripts/configure-public-analytics.py`
keeps the GTM tag/trigger/variables and the GA4 custom dimensions in step
with that list; a unit test fails when the two drift. Console setup and the
CloudFront CSP hosts are in
[`docs/deployment/public-website.md`](../../docs/deployment/public-website.md#google-analytics-4-and-tag-manager).

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
