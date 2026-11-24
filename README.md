# LX Software websites

[LX Software](https://www.lx-software.com) offers fractional CTO and CIO
work for Hong Kong startups: part-time technology leadership, AI and
automation, cloud and microservice architecture, and technical due
diligence. This repository hosts that **public** marketing site and a
separate **admin** console. The admin console is private. It holds the
finance books, statement import, banking sync, and the Siu Tin Dei
Executive Board.

This repository is public. Secrets and private personal data stay out of
git.

## What is here

| Path | What it is |
| --- | --- |
| `apps/public_www/` | The public site. Vite and React Router with hand-written CSS, pre-rendered to static HTML at build time. |
| `apps/admin_web/` | The admin console. Vite and React Router with TanStack Query and Bootstrap 5. |
| `backend/infrastructure/` | The AWS CDK app. Static assets deploy to private S3 buckets and are served through CloudFront. |
| `backend/lambda/` | The Python Lambda code: the admin API, the public API key authorizer, and the Cognito pre-token hook. |
| `contracts/` | Constants shared by the admin console, the admin Lambda, and CDK. |
| `scripts/` | Checks, contract sync, key management, and deploy scripts. |
| `docs/` | Architecture, deployment runbooks, and legal notes. |

## Working here

Read [`AGENTS.md`](AGENTS.md) before changing anything. The zone map,
[`docs/architecture/zones.md`](docs/architecture/zones.md), says which
paths need a plan or an approval first.

### Quick start (public site)

```bash
cd apps/public_www
npm install
npm run dev
```

### Quick start (admin console)

```bash
cd apps/admin_web
npm install
npm run dev
```

Copy `apps/admin_web/.env.example` to `.env` and fill in Cognito and API values.

Infra deploy expects GitHub variable **`ADMIN_GOOGLE_CLIENT_ID`**, and production environment secrets **`ADMIN_GOOGLE_CLIENT_SECRET`** (Google OAuth client secret, CDK `noEcho`) and **`ADMIN_FEDERATED_EMAIL_ALLOWLIST`** (comma-separated admin emails, CDK `noEcho`); see `docs/deployment/admin-website.md`.

## Documentation

- Architecture: `docs/architecture/overview.md`, `docs/architecture/security.md`
- Agent rules: `AGENTS.md`, `.cursor/rules/`, `docs/architecture/zones.md`
- Executive Board design: `docs/architecture/executive-board.md`
- AWS / GitHub OIDC setup and CDK Bootstrap: `docs/deployment/setup.md`
- Deploying the public site: `docs/deployment/public-website.md`
- Deploying and operating the admin site: `docs/deployment/admin-website.md`

## Security

To report a vulnerability, follow [`SECURITY.md`](SECURITY.md). Do not
open a public issue.

## Licence

Licensed under the Apache License, Version 2.0. The full text is in
[`LICENSE`](LICENSE). The fonts in `backend/lambda/admin/fonts/` keep
their own licence, the SIL Open Font License in `OFL.txt` there.
