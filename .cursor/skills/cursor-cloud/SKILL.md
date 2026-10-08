---
name: cursor-cloud
description: Run the LX Software apps in the cloud-agent VM without AWS credentials.
---

# Cursor Cloud

`.cursor/install.sh` installs npm dependencies, boto3, and ruff, and writes a placeholder `apps/admin_web/.env` when one is missing. Do not overwrite an existing `.env`.

| Service | Command | Port |
| --- | --- | --- |
| Public website | `cd apps/public_www && npm run dev` | 5173 |
| Admin console | `cd apps/admin_web && npm run dev` | 5174 |
| Admin fixtures | `cd apps/admin_web && npm run dev:mock` | 5174 |

`dev:mock` signs in with a fake admin token and serves `src/lib/mock/fixtures.ts`. Use it for UI work. CDK synth and deploy need AWS credentials and are not part of local website development.

Placeholder `VITE_*` values are not secrets. Real Cognito and API values stay in the developer environment or GitHub Actions variables.

Before committing Python, `python3 -m ruff check backend/lambda scripts` matches CI. The shell hook blocks `cdk deploy`, `aws delete-*`, and the live-mutation scripts listed in `.cursor/rules/scripts.mdc`.
