# Security policy

This policy covers the code in this repository and whatever is deployed from it. Every `lx-software-ltd` repository carries the same policy. Only the last section, [This repository](#this-repository), differs.

## Supported versions

Only the latest `main` is supported. Earlier commits do not receive fixes.

## Report a vulnerability

Report it privately through GitHub. Open the **Security** tab of this repository and choose **Report a vulnerability**. Do not open a public issue, pull request, or discussion.

Include:

- what is affected and what an attacker could do with it
- the steps to reproduce it
- the commit or URL you tested
- a fix or mitigation, if you have one

Do not put a live credential or anyone's personal data in the report. Say where you found it.

## What to expect

| Step | Target |
| --- | --- |
| First response | Within 48 hours |
| Status update | Within 7 days |
| Fix for a critical finding | Within 24 to 48 hours |
| Fix for a high finding | Within 7 days |
| Fix for a medium finding | Within 30 days |
| Fix for a low finding | Within 90 days |

You get updates while the fix is in progress and a note when it ships. The advisory credits you unless you ask to stay anonymous.

## Rules every repository follows

- **No secrets and no private personal data in git.** Secrets live in GitHub Actions secrets or AWS Secrets Manager. Gitleaks and a hashed personal-data denylist run on every pull request to `main`. GitHub secret scanning and push protection are on.
- **Changes reach `main` by pull request.** The `main-protection` ruleset blocks force-push and deletion, and requires the `lint`, `test`, and `security-summary` checks.
- **Security checks gate the merge.** `security-summary` fails unless every job in `.github/workflows/security.yml` succeeded. That workflow also runs every Monday.
- **Dependencies are pinned and watched.** Third-party GitHub Actions are pinned by full commit SHA. Dependabot opens version updates and security updates.
- **CI holds no long-lived AWS key.** Every workflow starts from `contents: read`. A job that calls AWS assumes a role through GitHub OIDC.

## This repository

`lx-software` deploys the LX Software public website and a private admin console with its backend API.

- `security.yml` runs Checkov, CodeQL, the personal-data denylist, Gitleaks, pip-audit, Bandit, npm audit, and Semgrep. `lint.yml` checks the lockfiles. Both gates are required.
- The owner name on the public website is published on purpose. It is not on the personal-data denylist.
- Known limitations: the admin distribution gets a web ACL only when `WafWebAclArn` is set. The stacks here do not set up CloudTrail.

The controls for sign-in, API authorization, uploads, the Executive Board, and logging are in [`docs/architecture/security.md`](docs/architecture/security.md).
