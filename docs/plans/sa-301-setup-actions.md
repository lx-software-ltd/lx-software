# Plan: Pin CI setup-node and setup-python

**Status**: In progress
**Zone**: yellow

Parent plan: [Shared actions repository and CI convergence](https://github.com/lx-software-ltd/actions/blob/61d2a581a1d880533982bada88923ad1b6431700/docs/plans/shared-actions-and-ci-convergence.md), step SA-301. `findingalpha` #73 is the pattern.

## Goal

Call `lx-software-ltd/actions` `setup-node` and `setup-python` at `61d2a581a1d880533982bada88923ad1b6431700` (`# main 2026-11-20`) from the CI workflows. Each caller keeps the Node or Python version it uses today. Move the `require-jobs` pin in `lint.yml` and `test.yml` from `1a3cca7c38163f8164c262323601c34a4df5b7a4` to that same commit.

## Non-goals

No Node 26 switch. No Python default substitution. No deploy, bootstrap, cdk-diff, or key-workflow edit. No `v*` tag. No `runs-on` change. No PII script or denylist edit. No change to gate `needs` lists.

## Pin

`61d2a581a1d880533982bada88923ad1b6431700` (`61d2a58`) `# main 2026-11-20`

The pin is `61d2a58` so this pull request and the ruleset pull request use one actions SHA.

## Files

- `.github/workflows/lint.yml`
- `.github/workflows/test.yml`
- `.github/workflows/check-lockfiles.yml`
- `.github/workflows/security.yml`
- `.github/workflows/lighthouse-public-website.yml`
- `docs/plans/sa-301-setup-actions.md`

`npm ci` is folded into `setup-node` where that following step is exactly `npm ci` in the lockfile directory. `install` stays at the default. Check Node.js lockfiles passes only `node-version`. Its shell loop that runs `npm ci` stays.

## Workflows left on `actions/setup-node@v7`

These stay on `actions/setup-node@v7`. They are not `lx-software-ltd/actions` pins.

- `.github/workflows/deploy-admin-web.yml`
- `.github/workflows/deploy-backend.yml`
- `.github/workflows/deploy-public-website.yml`
- `.github/workflows/cdk-diff.yml`
- `.github/workflows/cdk-bootstrap.yml` (bootstrap)
- `.github/workflows/manage-api-keys.yml` (keys; no setup-node or setup-python step)
- `.github/workflows/mint-openrouter-keys.yml` (keys; no setup-node or setup-python step)

`.github/workflows/verify-rulesets.yml` and `.github/workflows/apex-redirect-probe.yml` have no setup-node or setup-python step and are not edited.

## Versions each caller still passes

| Workflow | Job | Action | Version |
| --- | --- | --- | --- |
| lint.yml | Lint Public Website | setup-node | `lts/*` |
| lint.yml | Lint Admin Web | setup-node | `lts/*` |
| lint.yml | Build CDK | setup-node | `lts/*` |
| lint.yml | Lint Python | setup-python | `3.12` |
| lint.yml | Validate agent harness | setup-python | `3.12` |
| test.yml | Test Public Website | setup-node | `lts/*` |
| test.yml | Build Admin Web | setup-node | `lts/*` |
| test.yml | Admin Web viewport smoke | setup-node | `lts/*` |
| test.yml | Test Infrastructure | setup-node | `lts/*` |
| check-lockfiles.yml | Check Node.js lockfiles | setup-node | `lts/*` |
| security.yml | Checkov IaC Security | setup-node | `lts/*` |
| security.yml | Checkov IaC Security | setup-python | `3.12` |
| security.yml | CodeQL Analysis | setup-python | `3.12` |
| security.yml | PII denylist | setup-python | `3.12` |
| lighthouse-public-website.yml | Lighthouse audit | setup-node | `lts/*` |

Python callers pass only `python-version`. They do not pass `requirements`. The pip install steps that follow stay. The CodeQL step keeps `if: matrix.language == 'python'`.

## Invariants this change preserves

Job names stay. Checkout stays on `actions/checkout@v7`. Later lint, build, test, and Playwright steps stay. Gate jobs keep `needs`, `if: always()`, the step name, and `needs-json`. `runs-on` stays `ubuntu-26.04` on every job this change touches. No secret is added.

## Check names on main

`github-actions` check-run names on `main` `326acc85fd7f80079b3fefb4551260590c6ef6aa`, from `gh api repos/lx-software-ltd/lx-software/commits/326acc85fd7f80079b3fefb4551260590c6ef6aa/check-runs` before this edit:

- Check Node.js lockfiles
- Checkov IaC Security
- CodeQL Analysis (javascript)
- CodeQL Analysis (python)
- PII denylist
- Secret Scanning
- Security Summary
- Semgrep SAST

The push path filters on `lint.yml` and `test.yml` skipped those workflows. The merge did not touch the paths those filters list, so their jobs did not run. This pull request adds these job names:

- Admin Web viewport smoke
- Build Admin Web
- Build CDK
- Check shared contracts
- Lint Admin Web
- Lint Public Website
- Lint Python
- Test Infrastructure
- Test Public Website
- Validate agent harness
- lint
- test

Changing `lighthouse-public-website.yml` also runs Lighthouse audit on the pull request. That job did not run on this main commit. Checkov, CodeQL, and Semgrep OSS from `github-advanced-security` may appear only on the pull request.

## Done when

The five workflow files contain no `actions/setup-node@v7`, no `actions/setup-python@v7`, and no `1a3cca7`. Every `lx-software-ltd/actions` reference in those files is `61d2a581a1d880533982bada88923ad1b6431700`. Deploy, cdk-diff, bootstrap, and key workflows are unchanged.

## Rollback

Revert the pull request.

## Open questions

None.
