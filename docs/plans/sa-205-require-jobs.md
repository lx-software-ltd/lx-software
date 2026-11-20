# Plan: Pin lint and test gates to require-jobs

**Status**: In progress
**Zone**: yellow

Parent plan: Shared actions repository and CI convergence, `lx-software-ltd/actions` `docs/plans/shared-actions-and-ci-convergence.md`, step SA-205.

`findingalpha` #72 merged first, at `d924cc4b1bdee7477b49b3352eccd7a4762639ea`. This pull request merges after that.

## Goal

Replace only the inline gate step in the `lint` job of `.github/workflows/lint.yml` and the `test` job of `.github/workflows/test.yml` with `lx-software-ltd/actions/require-jobs` at `1a3cca7c38163f8164c262323601c34a4df5b7a4`.

## Non-goals

- Any other action pin.
- Deploy, security, and PII files.
- Job ids, job names, `needs` lists, `if: always()`, `runs-on: ubuntu-26.04`, permissions, and every other step.
- Adding or renaming jobs.

## Files

- `.github/workflows/lint.yml`
- `.github/workflows/test.yml`
- `docs/plans/sa-205-require-jobs.md`

## Invariants this change preserves

- Step names stay `Require every lint job` and `Require every test job`.
- `if: always()` stays on both gate jobs.
- Existing `needs` lists, job ids, job names, `runs-on: ubuntu-26.04`, and permissions stay.
- Every other step stays.

## Check names on main

Rollout step 2. `main` `6a986bfcbd28c4c604c821501e385a87c2e8f99c` is a push whose path filters skip `lint.yml` and `test.yml`, so those jobs did not run. github-actions check names:

- Check Node.js lockfiles
- Checkov IaC Security
- CodeQL Analysis (javascript)
- CodeQL Analysis (python)
- PII denylist
- Secret Scanning
- Security Summary
- Semgrep SAST

## Check names on the pull request head

Rollout step 4. Head `0bee24a356fbfdd00110399a414e41e079ee7792`. The eight names above are present. These twelve are the jobs in `lint.yml` and `test.yml`, which that path filter skipped on `main`:

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

`lint` and `test` succeeded. Checkov, CodeQL, and Semgrep OSS are `github-advanced-security` uploads on the pull request. They are code-scanning results, not renamed jobs.

## Done when

Both gate steps call the pinned action with `needs-json: ${{ toJson(needs) }}`. The lists above are the rollout evidence. `python3 -m unittest scripts/test_verify_github_rulesets.py` still passes. No test asserts the inline gate text. This pull request stays open until `findingalpha` #72 has merged, which it has.

## Rollback

Revert this pull request. The inline Python gate steps return, and `main` protection keeps the previous commit reachable. No other workflow, deploy, or PII file is in the change, so nothing else rolls back.

## Open questions

None.
