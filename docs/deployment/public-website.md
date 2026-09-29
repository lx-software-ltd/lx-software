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
