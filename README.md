# LX Software websites

This repository hosts the LX Software **public** marketing site and a
separate **admin** console. Both are Vite + React Router SPAs with Bootstrap 5.
Static assets deploy to private S3 buckets and are served through CloudFront.

## Quick start (public site)

```bash
cd apps/public_www
npm install
npm run dev
```

## Quick start (admin console)

```bash
cd apps/admin_web
npm install
npm run dev
```

Copy `apps/admin_web/.env.example` to `.env` and fill in Cognito and API values.

Infra deploy expects GitHub variable **`ADMIN_GOOGLE_CLIENT_ID`**, secret **`ADMIN_GOOGLE_CLIENT_SECRET`** (Google OAuth client secret, passed to CDK with `noEcho`), and variable **`ADMIN_FEDERATED_EMAIL_ALLOWLIST`**; see `docs/deployment/admin-website.md`.

## Documentation

- Architecture: `docs/architecture/overview.md`, `docs/architecture/security.md`
- Executive Board design: `docs/architecture/executive-board.md`
- AWS / GitHub OIDC setup and CDK Bootstrap: `docs/deployment/setup.md`
- Deploying the public site: `docs/deployment/public-website.md`
- Deploying and operating the admin site: `docs/deployment/admin-website.md`
