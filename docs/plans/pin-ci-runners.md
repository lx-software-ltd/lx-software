# Plan: Pin CI runners to Ubuntu 26.04

**Status**: Done
**Zone**: red

The owner asked to finish the CI warning fixes left after `docs/plans/ci-log-warnings.md`. That includes the red-zone workflow files below. The edit on those files is only `runs-on`.

## Goal

Stop the `ubuntu-latest` migration notice. Today's runners already report `Image: ubuntu-26.04`. Pin that image so the label is not floating.

## Non-goals

- Dependabot's `rehash: warning: skipping ca-certificates.crt`. The line is `openssl rehash` inside GitHub's updater image. `dependabot.yml` has no switch for it.
- Moving any job back to Ubuntu 24.04. The admin tests run on the image's Python 3.14.
- Skipping CodeQL's streaming bundle download. `codeql-action` v4 streams a zstd bundle on Linux and does not read `CODEQL_ACTION_ZSTD_BUNDLE_STREAMING_EXTRACTION`. Setting it does not change the download. The action already falls back when the stream returns HTTP 504.

## Files

- Every workflow `runs-on: ubuntu-latest`, including the red-zone files `.github/workflows/deploy-*.yml`, `manage-api-keys.yml`, `mint-openrouter-keys.yml`, and `verify-rulesets.yml`.

## Invariants this change preserves

- Deploy, key-mint, and ruleset jobs keep the same steps, secrets, and permissions.
- CodeQL still runs `security-extended` for JavaScript and Python, and still downloads its bundle the way the action does today.

## Done when

No workflow still says `runs-on: ubuntu-latest`.

## Rollback

Revert the commit. Jobs use `ubuntu-latest` again.

## Open questions

None.
