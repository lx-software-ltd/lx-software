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
`apps/public_www/public/content.json` (`site.owner`, `site.role`,
`site.title`, `site.description`, `site.keywords`). Editing that file is the
only step needed to change the public copy.

## Lighthouse

**Lighthouse Public Website** (`.github/workflows/lighthouse-public-website.yml`)
is manual. It builds `apps/public_www` with the production variables, serves
`dist/` locally, and runs Lighthouse CI against `/` (or the `page_paths`
input, comma or newline separated). Every category must score 0.9 or better
(`apps/public_www/.lighthouserc.json`). The HTML reports are uploaded as the
`lighthouse-public-www-results` artifact.

## Build locally

```bash
cd apps/public_www
npm install
npm run build
```

Output lands in `apps/public_www/dist`.

## Deploy to S3 + CloudFront

**Deploy Public Website** runs on pushes to `main` that touch
`apps/public_www/**`, `backend/infrastructure/**` or `scripts/deploy/**`,
or manually. It builds the site, then uploads `dist/` and invalidates the
distribution. Hashed files under `assets/` go up first and are cached for a
year. `index.html`, `content.json`, robots, the sitemap, `llms.txt`,
`llms-full.txt`, and `site.webmanifest` are copied with
`Cache-Control: no-cache` and are never written as immutable. `media/`
syncs with `--size-only`. Retired hashed assets are deleted only after the
new shell is uploaded.

```bash
PUBLIC_WEBSITE_STACK_NAME=lxsoftware-public-www \
  bash scripts/deploy/deploy-public-website.sh
```

The script reads the stack outputs `PublicWebsiteBucketName` and
`PublicWebsiteDistributionId`.

The distribution sends a content security policy that allows images and
video from `'self'` and `https://media.lx-software.com`, scripts from
`'self'` and `https://www.googletagmanager.com`, and analytics hits to
`https://*.google-analytics.com` and `https://*.analytics.google.com`.
Inline scripts are blocked. `backend/infrastructure/test/public-website-stack.test.ts`
pins that list.

## Google Analytics 4 and Tag Manager

The site loads one Google Tag Manager container (`apps/public_www/src/lib/gtm.ts`)
when `VITE_GTM_ID` is set at build time. GA4 is configured inside the
container, so a measurement id never lands in this repository. The loader
does nothing when the visitor's browser sends Global Privacy Control or Do
Not Track; the privacy policy in `content.json` (section "Analytics") says
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
(`--no-publish` stops before publishing). It never deletes anything and
never adds a second Google tag; a container whose Google tag carries a
different measurement id is reported for the owner to decide.

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
it. The apex is already proxied; leave that record alone. Tiered Cache is
off. The media hostname is already caching from the object `Cache-Control`,
so an extra cache rule is optional.

## Troubleshooting

Bootstrap and IAM errors (`SSM parameter /cdk-bootstrap/... not found`,
`could not be used to assume ... deploy-role`) are covered in
[`setup.md`](./setup.md#troubleshooting).
