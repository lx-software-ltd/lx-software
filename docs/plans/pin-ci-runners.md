# Plan: Pin CI runners and skip CodeQL streaming

**Status**: Done
**Zone**: red

The owner asked to finish the CI warning fixes left after `docs/plans/ci-log-warnings.md`. That includes the red-zone workflow files below. The edit on those files is only `runs-on`.

## Goal

Stop the `ubuntu-latest` migration notice, and stop CodeQL from warning when a streaming bundle download returns HTTP 504.

Today's runners already report `Image: ubuntu-26.04`. Pin that image so the label is not floating. CodeQL's streaming extract is what printed the 504 warning before it fell back to a normal download. Set `CODEQL_ACTION_ZSTD_BUNDLE_STREAMING_EXTRACTION` to `false` so init uses that download path directly.

## Non-goals

- Dependabot's `rehash: warning: skipping ca-certificates.crt`. The line is `openssl rehash` inside GitHub's updater image. `dependabot.yml` has no switch for it.
- Moving any job back to Ubuntu 24.04. The admin tests run on the image's Python 3.14.

## Files

- Every workflow `runs-on: ubuntu-latest`, including the red-zone files `.github/workflows/deploy-*.yml`, `manage-api-keys.yml`, `mint-openrouter-keys.yml`, and `verify-rulesets.yml`.
- `.github/workflows/security.yml` CodeQL job environment.

## Invariants this change preserves

- Deploy, key-mint, and ruleset jobs keep the same steps, secrets, and permissions.
- CodeQL still runs `security-extended` for JavaScript and Python. Only the bundle download path changes.

## Done when

No workflow still says `runs-on: ubuntu-latest`. The CodeQL job sets the streaming flag to false.

## Rollback

Revert the commit. `ubuntu-latest` again, and CodeQL streams the bundle when GitHub enables that flag.

## Open questions

None.
