# Deploying the public website

Prerequisites (OIDC provider, `GitHubActionsRole`, CDK Bootstrap, GitHub
environment variables) are in [`setup.md`](./setup.md).

## Variables used by this deploy

Set these on the **production** environment (the deploy job uses
`environment: production`). Vite inlines every `VITE_*` value into the
public JavaScript, so they are variables, not secrets. Leave telephone
or WhatsApp empty to show "Not configured".

| Variable | Required | Description |
|----------|----------|-------------|
| `AWS_ACCOUNT_ID` | yes, to deploy | Target AWS account ID |
| `AWS_REGION` | yes, to deploy | Target AWS region |
| `CDK_PARAM_FILE` | for CDK | Path to parameter file, e.g. `backend/infrastructure/params/production.json` |
| `PUBLIC_WEBSITE_STACK_NAME` | no | Stack that owns the bucket and distribution. Default `lxsoftware-public-www` |
| `VITE_MEDIA_BASE_URL` | no | `https://media.lx-software.com` (no trailing slash). Empty keeps serving `/media/*` from this site |
| `VITE_CONTACT_TEL` | no | Telephone, E.164 with a leading `+`. Empty shows "Not configured" |
| `VITE_CONTACT_WHATSAPP` | no | WhatsApp digits only, country code, no `+`. Empty shows "Not configured" |
| `VITE_CONTACT_EMAIL` | no | Mailto target. Empty uses `hello@lx-software.com` |
| `VITE_CONTACT_WECHAT_ID` | no | Shown on `/wechat`. Empty leaves the placeholder |
| `VITE_CONTACT_LINKEDIN` | no | LinkedIn profile URL or `in/<slug>`. Drives the contact icon, the JSON-LD `sameAs`, and `llms.txt`. Empty shows "Not configured" |
| `VITE_GTM_ID` | no | Google Tag Manager web container id (`GTM-XXXXXXX`). Empty ships the site without Tag Manager or GA4. See [Google Analytics 4 and Tag Manager](#google-analytics-4-and-tag-manager) |

`ADMIN_API_BASE_URL` is no longer read by this workflow. The public site
does not call the admin API.

`VITE_OWNER_NAME` is retired. The schema.org `Person` node, the `<title>`,
the meta description, Open Graph tags, and the FAQ come from
`apps/public_www/src/content/site.json` (`site.owner`, `site.role`,
`site.title`, `site.description`, `site.keywords`). Editing that file is the
only step needed to change the public copy.

## Pages and pre-rendering

The site is one React Router app, but every route is written to static
HTML at build time so crawlers, link previews, and AI assistants see the
copy without running JavaScript. `vite.config.ts` runs a second SSR build
of `src/entry-server.tsx` after the client bundle, renders each route from
`scripts/site-seo.ts` with `react-dom/static`, and writes
`dist/<route>.html` plus `dist/<route>/index.html` (the second form is for
`vite preview` and the Lighthouse static server). Each file carries that
page's `<title>`, meta description, canonical, Open Graph tags, JSON-LD
graph, and the site CSS inlined into a `<style>` tag. `main.tsx` hydrates
the server markup when it is present and falls back to `createRoot` for
the dev server. Set `PUBLIC_WWW_PRERENDER=0` to skip pre-rendering during a
build. The build fails if a route renders without an `<h1>` or without
inline CSS.

Service and about pages come from `pages[]` in
`apps/public_www/src/content/site.json`. Each entry has a `slug` (the
route), `navLabel`, `title`, `metaTitle` (70 characters or fewer),
`description` (70 to 200 characters), `intro`, optional `service` (the
`whatIDo.services[].title` that links to it with `href`), `sections[]`
(`heading`, `paragraphs`, `bullets`), and optional `faq[]`. Adding a page is
a new `pages[]` entry; the route, sitemap, `llms.txt`, JSON-LD (`WebPage`,
`BreadcrumbList`, `Service`, `FAQPage`) and bottom-bar link follow from it.
`src/lib/content.test.ts` checks slugs, lengths, and that no page says
"interim".

## Lighthouse

**Lighthouse Public Website** (`.github/workflows/lighthouse-public-website.yml`)
runs on pull requests that touch `apps/public_www/**`, every Monday, and on
demand. It builds `apps/public_www` with the production variables, serves
`dist/` locally, and runs Lighthouse CI against `/`,
`/fractional-cto-hong-kong`, `/about`, `/privacy`, `/terms`, and `/wechat`
(or the `page_paths` input, comma or newline separated). The audit blocks
the Tag Manager and Analytics hosts (`blockedUrlPatterns`), so the runs do
not count as sessions on the production GA4 property. Each
URL is audited 3 times and assertions use the median run. Every category
must score 0.9 or better. The gate also fails on a distorted image, an
offscreen image, a render-blocking resource, simulated LCP above 4 s, total
blocking time above 200 ms, or unused JavaScript whose estimated savings
exceed 400 ms (`apps/public_www/.lighthouserc.json`). The simulated LCP is the harbour poster, and that number moves by several hundred milliseconds between runs, so the cap sits at 4 s. The HTML reports are uploaded as the
`lighthouse-public-www-results` artifact, and the run posts a commit status
when `GITHUB_TOKEN` can write statuses.

## Build locally

```bash
cd apps/public_www
npm install
npm run build
```

Output lands in `apps/public_www/dist`.

## Deploy to S3 + CloudFront

**Deploy Public Website** runs on pushes to `main` that touch
`apps/public_www/**` or `scripts/deploy/**`,
or manually. It builds the site, then uploads `dist/` and invalidates the
distribution. Hashed files under `assets/` go up first and are cached for a
year. Every `.html`, `.txt`, and `.xml` file plus `site.webmanifest` is
copied with `Cache-Control: no-cache` and is never written as immutable.
Each pre-rendered page is uploaded twice: as `dist/<route>.html` and under
the extensionless key `<route>`, because CloudFront maps the request
`/about` straight to the S3 key `about` (the 403 → `index.html` fallback
remains for unknown paths and for `/about/` with a trailing slash). Other
unhashed directories that Vite copies from `public/` (including `images/`
and the `<route>/index.html` copies) are uploaded the same way, with a
content type and `no-cache`. `media/` syncs with `--size-only`. Retired
hashed assets are deleted only after the new shell is uploaded.

```bash
PUBLIC_WEBSITE_STACK_NAME=lxsoftware-public-www \
  bash scripts/deploy/deploy-public-website.sh
```

The script reads the stack outputs `PublicWebsiteBucketName` and
`PublicWebsiteDistributionId`.

After the CloudFront invalidation the script submits every sitemap URL to
[IndexNow](https://www.indexnow.org/) (Bing, Yandex, Naver, Seznam, Yep;
Google does not take part and reads `sitemap.xml` instead). The key is
`apps/public_www/public/indexnow.txt`, served at `/indexnow.txt`; it is
public by design, not a secret. The ping never fails the deploy: a 4xx/5xx,
missing `curl`, or a missing key file is logged and the job continues. Set
`INDEXNOW_DISABLED=1` to skip it. A new key is any 8 to 128 character
string of letters, digits, and dashes written to that file.

The distribution sends a content security policy that allows images and
video from `'self'` and `https://media.lx-software.com`, scripts from
`'self'` and `https://www.googletagmanager.com`, and analytics hits to
`https://*.google-analytics.com` and `https://*.analytics.google.com`.
Inline scripts are blocked. It also sends
`Cross-Origin-Opener-Policy: same-origin`.
`backend/infrastructure/test/public-website-stack.test.ts` pins the CSP list.

## Google Analytics 4 and Tag Manager

The site loads one Google Tag Manager container (`apps/public_www/src/lib/gtm.ts`)
when `VITE_GTM_ID` is set at build time. GA4 is configured inside the
container, so a measurement id never lands in this repository. The loader
does nothing when the visitor's browser sends Global Privacy Control or Do
Not Track; the privacy policy in `src/content/site.json` (section "Analytics") says
so and must stay in step with what the container does.

Creating the Google properties needs the owner's Google account. GitHub
Actions cannot do it, so this is a one-time manual run:

1. **GA4 property.** [analytics.google.com](https://analytics.google.com) →
   Admin → Create → Property. Name `LX Software`, reporting time zone
   `Hong Kong (GMT+08:00)`, currency `HKD`. Business details are optional.
2. **Web data stream.** In that property, Admin → Data streams → Add stream
   → Web. URL `https://www.lx-software.com`, stream name `lx-software.com`.
   Leave **Enhanced measurement** on: its *Page changes based on browser
   history events* setting is what records `page_view` for React Router
   navigation on this single-page site. Copy the **Measurement ID**
   (`G-XXXXXXXXXX`).
3. **Recommended GA4 settings.** Admin → Data settings → Data retention →
   `14 months`. Admin → Data streams → the web stream → Configure tag
   settings → Define internal traffic → add your own IP so your visits can
   be filtered, then Admin → Data filters → set *Internal Traffic* to
   Active.
4. **GTM container.** [tagmanager.google.com](https://tagmanager.google.com)
   → Create Account. Account `LX Software`, country `Hong Kong`, container
   name `www.lx-software.com`, platform **Web**. Dismiss the install
   snippet; this repository already loads `gtm.js`. Copy the container id
   (`GTM-XXXXXXX`).
5. **Google tag in GTM.** Tags → New → **Google Tag**. Tag ID = the
   `G-XXXXXXXXXX` from step 2. Trigger **Initialization - All Pages**.
   Save, then **Submit** and publish the version. Do not add Custom HTML
   tags: the CloudFront CSP blocks inline scripts, and any other vendor
   host would need adding to `public-website-stack.ts` first.
6. **Wire the site.** GitHub → repository Settings → Environments →
   `production` → Variables → add `VITE_GTM_ID` = `GTM-XXXXXXX`. Run
   **Deploy Public Website** (`workflow_dispatch`) so the bundle is rebuilt
   with the id. If the CSP change in `backend/infrastructure/` has not been
   deployed yet, run **Deploy Backend** first; without it the browser
   blocks `gtm.js`.
7. **Verify.** Open `https://www.lx-software.com` in a browser without a
   content blocker, then GA4 → Reports → Realtime should show the visit
   within a minute. The browser network tab shows `gtm.js?id=GTM-…`,
   `gtag/js?id=G-…`, and `collect` requests. No request to Google should
   appear when the browser has GPC enabled. GTM **Preview** (Tag Assistant)
   works for the tag-firing checks; the debug badge may report CSP
   warnings for its own styling because only the `googletagmanager.com`
   host is allowed.

To switch analytics off again, clear `VITE_GTM_ID` and redeploy the site.
The CSP entries can stay.

### Site events

Enhanced measurement sees page views (including React Router navigation),
scroll depth, clicks on outbound `http(s)` links, downloads and form
interactions. It does not see `tel:` / `mailto:` links, in-site routes,
`<details>` toggles, carousel buttons or a 404 route. For those the site
pushes its own events onto `dataLayer` from
`apps/public_www/src/lib/analytics.ts`, only after the container loaded (so
GPC / DNT visitors still send nothing):

| Event | Parameters | Fired by |
|-------|------------|----------|
| `contact_click` | `channel` (`tel`, `email`, `whatsapp`, `wechat`, `linkedin`), `destination` (scheme, host or route, never the number or address) | contact icons |
| `faq_toggle` | `question`, `state` (`open` / `closed`) | FAQ `<details>` |
| `project_open` | `project`, `destination` | `[ open ]` on a project card |
| `project_navigate` | `direction` (`next` / `prev`), `method` (`button` / `keyboard`) | carousel controls |
| `nav_click` | `section` | top navigation, hero scroll cue |
| `cta_click` | `page` (the content page slug) | the call-to-action block on service and about pages |
| `page_not_found` | `path` | the 404 route |
| `media_error` | `source` | every harbour video source failed |

Inside GTM one Custom Event trigger (`Site events`, regex over those names)
fires one GA4 event tag (`GA4 event - site events`, event name `{{Event}}`)
that forwards every parameter through `DL - <param>` Data Layer variables.
GA4 has one event-scoped custom dimension per parameter so they show up in
reports, and `contact_click` / `project_open` are key events. Adding an
event means editing `SiteEvent` in `analytics.ts`, the two tuples at the top
of `scripts/configure-public-analytics.py` (a unit test fails when they
differ), and running `apply` below.

### Managing GA4 and GTM from a service account

`scripts/configure-public-analytics.py` compares the property and the live
container with the setup above and fixes the differences:

```bash
python3 -m pip install google-auth
export LXSOFTWARE_GOOGLE_SERVICE_ACCOUNT_JSON='{...}'   # or GOOGLE_APPLICATION_CREDENTIALS=/path/key.json
export LXSOFTWARE_GA4_PROPERTY_ID=123456789
export LXSOFTWARE_GTM_ACCOUNT_ID=1234567890
export LXSOFTWARE_CONTAINER_ID=GTM-XXXXXXX
python3 scripts/configure-public-analytics.py check   # exit 1 on drift
python3 scripts/configure-public-analytics.py apply   # GA4 patches + new GTM version, published
```

`check` reads only. `apply` patches time zone / currency / 14-month
retention / enhanced measurement / e-mail redaction, creates missing custom
dimensions and key events, then creates a fresh GTM workspace with the
missing variables, trigger and tags, creates a version and publishes it
(`--no-publish` stops before publishing). When the `Site events` trigger or
the event tag already exist but lag the event / parameter lists, the
workspace rewrites them in place (the tag keeps its firing triggers and
measurement id). It never deletes anything and never adds a second Google
tag; a container whose Google tag carries a different measurement id is
reported for the owner to decide.

### Traffic report

`scripts/report-public-analytics.py` prints a read-only Markdown report
from the GA4 Data API and the Search Console API with the same service
account: 7 / 28 / 90-day totals, channels, source / medium, countries,
landing pages, pages, event counts, `contact_click` by channel, FAQ
questions, projects opened, CTA clicks by page, then Search Console totals,
top queries, top pages, and sitemap status.

```bash
python3 scripts/report-public-analytics.py                 # 28-day window, Markdown
python3 scripts/report-public-analytics.py --days 90 --json
python3 scripts/report-public-analytics.py --no-gsc --out /tmp/report.md
```

It needs the [Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
and the [Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com)
enabled, Viewer on the GA4 property, and the service account added as a
user on the Search Console domain property (`sc-domain:lx-software.com`,
override with `LXSOFTWARE_GSC_PROPERTY`). The window ends yesterday because
the current day is incomplete. A GA4 dimension that does not exist yet (for
example `customEvent:page` before `apply` has run) is reported inside its
table rather than failing the run.

One-time prerequisites (owner's Google account; the four Cloud Agent
secrets above are already set):

1. **APIs.** In the Cloud project that owns the service account, enable
   the [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com)
   and the [Tag Manager API](https://console.cloud.google.com/apis/library/tagmanager.googleapis.com).
   No billing account is needed. Until then every call fails with
   `SERVICE_DISABLED`, which the script prints with both links.
2. **GA4 access.** Admin → Property access management → add the service
   account e-mail with the **Editor** role.
3. **GTM access.** Admin → User management → add the same e-mail with
   container permission **Publish**.
4. **User-provided data collection.** Admin → Data collection and
   modification → Data collection → *Allow user-provided data collection*
   is **on** by default on a new property and is not exposed by the Admin
   API. The privacy policy promises analytics only, so switch it **off**.
   The published `gtag/js` config shows the current state
   (`__ogt_1p_data_v2` → `vtp_isAutoEnabled`).

## Media (Cloudflare R2)

The slowed silent harbour loop is rendered by
`apps/public_www/media/render.sh` into `apps/public_www/public/media/`.
Bucket `lx-software-media` is live, and `media.lx-software.com` is a proxied
CNAME on the `lx-software.com` zone. The v1 renditions are uploaded with
`Cache-Control: public, max-age=31536000, immutable`. A ranged GET of the
720p MP4 returns 206, and a repeat request is a Cloudflare cache HIT.

The site still plays `/media/*` from this origin until the production
variable is set and **Deploy Public Website** runs again:

```text
VITE_MEDIA_BASE_URL=https://media.lx-software.com
```

No trailing slash. After that deploy is serving the R2 URLs, the video
renditions and the master can leave git. The posters stay in
`apps/public_www/public/media/` because the page preloads them from this
origin. Do not rewrite history with Git LFS. Re-running
`scripts/cloudflare/publish-public-media.sh` treats an existing bucket and
custom domain as success.

`www.lx-software.com` stays a grey-cloud CNAME to CloudFront. Do not proxy
it. The apex is a Worker custom domain (`AAAA 100::`, proxied) for
`lx-software-apex-redirect`. A Single Redirect
(`http.host eq "lx-software.com"`) 301s to
`concat("https://www.lx-software.com", http.request.uri.path)` and keeps
the query; that rule runs before Workers, so HTTPS never reaches a
literal `https://www.lx-software.com/*` destination. The Worker on
`lx-software.com/*` is the HTTP / fallback path. Publish with
`python3 scripts/cloudflare/publish-apex-redirect.py apply`
(`CLOUDFLARE_API_TOKEN` needs Workers edit, zone Workers Routes, and
Zone Redirect Rules Edit, plus `CLOUDFLARE_ACCOUNT_ID`).
`publish-apex-redirect.py check` should report 301s for HTTP and HTTPS
and refuse a star destination. Do not restore the dummy `192.0.2.1` A
record unless you are removing the custom domain. Tiered Cache is off.
The media hostname is already caching from the object `Cache-Control`,
so an extra cache rule is optional.

## Troubleshooting

Bootstrap and IAM errors (`SSM parameter /cdk-bootstrap/... not found`,
`could not be used to assume ... deploy-role`) are covered in
[`setup.md`](./setup.md#troubleshooting).
