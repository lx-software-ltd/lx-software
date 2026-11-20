# Plan: Pin Verify GitHub Rulesets

**Status**: In progress
**Zone**: yellow

Parent plan: [Shared actions repository and CI convergence](https://github.com/lx-software-ltd/actions/blob/61d2a581a1d880533982bada88923ad1b6431700/docs/plans/shared-actions-and-ci-convergence.md), step SA-304.

A pull request is opened.

## Goal

Replace the inline ruleset script with the composite action so this repository takes gate G1 before the same contract lands on the repositories whose Monday run fails.

The Monday failure this fixes is on evolvesprouts and siutindei, not this repository. This pilot takes the same contract before those two.

Gate G1: expected reviews exactly 0, required checks exactly lint and test.

Pin:

`lx-software-ltd/actions/verify-rulesets@61d2a581a1d880533982bada88923ad1b6431700` # main 2026-11-20

## Non-goals

No other workflow. No run of this workflow from the pull request, from `workflow_dispatch`, or from the Monday schedule. No require-jobs or setup-action pin change. No edit to `lint.yml`, `test.yml`, `security.yml`, the deploy workflows, `cdk-diff.yml`, bootstrap, or key workflows.

## Files

- `.github/workflows/verify-rulesets.yml`
- `docs/plans/sa-304-verify-rulesets.md`
- `docs/architecture/security.md` (two sentences that named the deleted script and said a review count other than 0 does not fail)

Deleted:

- `scripts/verify_github_rulesets.py`
- `scripts/test_verify_github_rulesets.py`

Search of the tree found no other workflow, test runner, or import that calls those files. `test.yml` discovers `scripts/test_*.py` in the `check-contracts` job (`python3 -m unittest discover -s scripts -p 'test_*.py'`), so deleting the test removes it from that discover. `docs/plans/sa-205-require-jobs.md` records that the same unittest passed for SA-205. That sentence is history for that change, not a caller, and stays.

## Invariants this change preserves

The workflow name stays Verify GitHub Rulesets. The schedule stays cron `0 9 * * 1`. `workflow_dispatch` stays. Permissions stay `contents: read`. The job id stays `verify-branch-protection` with no job name, so the check name stays `verify-branch-protection`. The runner stays `ubuntu-26.04`. The checkout step stays `actions/checkout@v7`.

`verify-rulesets.yml` does not run on `pull_request`. Its triggers are the Monday cron and `workflow_dispatch`, so the pull request will not execute it. This change does not dispatch the workflow.

## Path filters

Deleting the two scripts is a `scripts/**` change.

`lint.yml` `pull_request` has no path filter, so a pull request runs `lint.yml` for any path. `lint.yml` `push` to `main` includes `scripts/**`, so deleting these files makes `lint.yml` run on a push to `main`.

`test.yml` `pull_request` has no path filter, so a pull request runs `test.yml` for any path. `test.yml` `push` to `main` lists `apps/public_www/**`, `apps/admin_web/**`, and `backend/infrastructure/**`. It does not list `scripts/**`, so deleting `scripts/**` does not make `test.yml` run on a push to `main`.

## Done when

The verify step uses the pin above and passes `token` from `github.token`, `expected-reviews` `"0"`, and `required-checks` `lint test`. The two scripts are gone, and no test imports the deleted module. `docs/architecture/security.md` no longer says the weekly job runs `scripts/verify_github_rulesets.py`, and it no longer says a review count other than 0 does not fail.

Check-run names recorded on main `326acc85fd7f80079b3fefb4551260590c6ef6aa` before the edit, from the checks API (`total_count` 8, filter latest):

- Check Node.js lockfiles
- Checkov IaC Security
- CodeQL Analysis (javascript)
- CodeQL Analysis (python)
- PII denylist
- Secret Scanning
- Security Summary
- Semgrep SAST

## Rollback

Revert the pull request.

## Open questions

None.
