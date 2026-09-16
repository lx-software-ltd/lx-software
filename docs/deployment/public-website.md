# Deploying the public website

Prerequisites (OIDC provider, `GitHubActionsRole`, CDK Bootstrap, GitHub
environment variables) are in [`setup.md`](./setup.md).

## Variables used by this deploy

| Variable | Description | Example |
|----------|-------------|---------|
| `AWS_ACCOUNT_ID` | Target AWS account ID | `588024549699` |
| `AWS_REGION` | Target AWS region | `ap-southeast-1` |
| `CDK_PARAM_FILE` | Path to parameter file | `backend/infrastructure/params/production.json` |
| `PUBLIC_WEBSITE_STACK_NAME` | Stack that owns the S3 bucket / CloudFront distribution | `lxsoftware-public-www` |
| `ADMIN_API_BASE_URL` | Admin HTTP API origin (no trailing slash). Inlined at build as `VITE_PUBLIC_API_URL` for `NewsletterForm`. | `https://xxxx.execute-api.ap-southeast-1.amazonaws.com` |

## Build locally

```bash
cd apps/public_www
npm install
VITE_PUBLIC_API_URL=https://xxxx.execute-api.ap-southeast-1.amazonaws.com npm run build
```

Without `VITE_PUBLIC_API_URL` the newsletter form throws "not configured"
at submit. **Deploy Public Website** reads `vars.ADMIN_API_BASE_URL` and
fails the build if it is empty. Output lands in `apps/public_www/dist`.

## Deploy to S3 + CloudFront

**Deploy Public Website** runs on pushes to `main` that touch
`apps/public_www/**`, `backend/infrastructure/**` or `scripts/deploy/**`,
or manually. It builds the
site, then runs the deploy script, which syncs `dist/` to the bucket and
invalidates the distribution:

```bash
PUBLIC_WEBSITE_STACK_NAME=lxsoftware-public-www \
  bash scripts/deploy/deploy-public-website.sh
```

The script reads the stack outputs `PublicWebsiteBucketName` and
`PublicWebsiteDistributionId`.

## Troubleshooting

Bootstrap and IAM errors (`SSM parameter /cdk-bootstrap/... not found`,
`could not be used to assume ... deploy-role`) are covered in
[`setup.md`](./setup.md#troubleshooting).
