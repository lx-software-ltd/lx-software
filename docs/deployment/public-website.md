# Deploying the public website

Prerequisites (OIDC provider, `GitHubActionsRole`, CDK Bootstrap, GitHub
environment variables) are in [`setup.md`](./setup.md).

## Variables used by this deploy

Set these on the **production** environment (the deploy job uses
`environment: production`). Vite inlines every `VITE_*` value into the
public JavaScript, so they are variables, not secrets. Leave a contact
variable empty to keep that icon disabled.

| Variable | Required | Description |
|----------|----------|-------------|
| `AWS_ACCOUNT_ID` | yes, to deploy | Target AWS account ID |
| `AWS_REGION` | yes, to deploy | Target AWS region |
| `CDK_PARAM_FILE` | for CDK | Path to parameter file, e.g. `backend/infrastructure/params/production.json` |
| `PUBLIC_WEBSITE_STACK_NAME` | no | Stack that owns the bucket and distribution. Default `lxsoftware-public-www` |
| `VITE_MEDIA_BASE_URL` | no | Harbour video host, no trailing slash. Empty serves `/media/*` from this site. After R2 is live: `https://media.lx-software.com` |
| `VITE_CONTACT_TEL` | no | Telephone, E.164 with a leading `+`. Empty shows "Not configured" |
| `VITE_CONTACT_WHATSAPP` | no | WhatsApp digits only, country code, no `+`. Empty shows "Not configured" |
| `VITE_CONTACT_EMAIL` | no | Mailto target. Empty uses `hello@lx-software.com` |
| `VITE_CONTACT_WECHAT_ID` | no | Shown on `/wechat`. Empty leaves the placeholder |
| `VITE_OWNER_NAME` | no | schema.org Person name. Empty omits the Person node |

`ADMIN_API_BASE_URL` is no longer read by this workflow. The public site
does not call the admin API.

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
video from `'self'` and `https://media.lx-software.com`.

## Media (Cloudflare R2)

The slowed silent harbour loop is rendered by
`apps/public_www/media/render.sh` into `apps/public_www/public/media/`.
The site plays it from the same origin until `VITE_MEDIA_BASE_URL` is set.

R2 is **not enabled** on the Cloudflare account yet. The API returns error
10042 (`Please enable R2 through the Cloudflare Dashboard`) and that
switch cannot be flipped from the API. After enabling R2 and accepting the
terms:

```bash
CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... \
  bash scripts/cloudflare/publish-public-media.sh
```

The script creates bucket `lx-software-media`, attaches the custom domain
`media.lx-software.com` on the `lx-software.com` zone, and uploads the
versioned renditions with `Cache-Control: public, max-age=31536000, immutable`.

Then set the production variable `VITE_MEDIA_BASE_URL` to
`https://media.lx-software.com` and redeploy. Confirm a ranged response:

```bash
curl -I -H 'Range: bytes=0-1' https://media.lx-software.com/hk-harbour-v1-720.mp4
```

`www.lx-software.com` stays a grey-cloud CNAME to CloudFront. Do not proxy
it. The apex is already proxied; leave that record alone. A cache rule for
`media.lx-software.com` (cache eligible, edge and browser TTL respect the
origin `Cache-Control`) needs a token that can edit zone rulesets. The
current token can read DNS and tiered-cache settings and cannot write
rulesets (HTTP 403). Add that rule in the dashboard after the hostname
exists. Tiered Cache is currently off; turn it on for the zone once the
media hostname is serving traffic.

## Troubleshooting

Bootstrap and IAM errors (`SSM parameter /cdk-bootstrap/... not found`,
`could not be used to assume ... deploy-role`) are covered in
[`setup.md`](./setup.md#troubleshooting).
