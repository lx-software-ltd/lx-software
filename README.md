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
| [`apps/public_www/`](apps/public_www/) | The public site. Vite and React Router with hand-written CSS, pre-rendered to static HTML at build time. |
| [`apps/admin_web/`](apps/admin_web/) | The admin console. Vite and React Router with TanStack Query and Bootstrap 5. |
| [`backend/infrastructure/`](backend/infrastructure/) | The AWS CDK app. Static assets deploy to private S3 buckets and are served through CloudFront. |
| [`backend/lambda/`](backend/lambda/) | The Python Lambda code: the admin API, the public API key authorizer, and the Cognito pre-token hook. |
| [`contracts/`](contracts/) | Constants shared by the admin console, the admin Lambda, and CDK. |
| [`scripts/`](scripts/) | Checks, contract sync, key management, and deploy scripts. |
| [`docs/`](docs/) | Architecture, deployment runbooks, and legal notes. |

## Working here

Read [`AGENTS.md`](AGENTS.md) before changing anything. The zone map,
[`docs/architecture/zones.md`](docs/architecture/zones.md), says which
paths need a plan or an approval first.

## Documentation

- [`docs/architecture/overview.md`](docs/architecture/overview.md): the
  two sites and the three stacks.
- [`docs/architecture/security.md`](docs/architecture/security.md):
  sign-in, API authorization, uploads, and logging.
- [`docs/architecture/zones.md`](docs/architecture/zones.md): which paths
  need a plan or an approval first.
- [`docs/architecture/executive-board.md`](docs/architecture/executive-board.md):
  the Siu Tin Dei Executive Board.
- [`docs/architecture/linkedin-reach.md`](docs/architecture/linkedin-reach.md):
  LinkedIn reach.
- [`docs/deployment/setup.md`](docs/deployment/setup.md): AWS, GitHub
  OIDC, and CDK bootstrap.
- [`docs/deployment/public-website.md`](docs/deployment/public-website.md):
  deploying the public site.
- [`docs/deployment/admin-website.md`](docs/deployment/admin-website.md):
  deploying and operating the admin site.
- [`docs/legal/README.md`](docs/legal/README.md): where the privacy
  policy and terms live.
- [`docs/plans/README.md`](docs/plans/README.md) and
  [`docs/research/README.md`](docs/research/README.md): open plans and
  research memos.

## Security

To report a vulnerability, follow [`SECURITY.md`](SECURITY.md). Do not
open a public issue.

## Licence

Licensed under the Apache License, Version 2.0. The full text is in
[`LICENSE`](LICENSE). The fonts in `backend/lambda/admin/fonts/` keep
their own licence, the SIL Open Font License in
[`OFL.txt`](backend/lambda/admin/fonts/OFL.txt) there.
