# Plan: Pin lint and test gates to require-jobs

**Status**: Done
**Zone**: yellow

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

## Done when

Both gate steps call the pinned action with `needs-json: ${{ toJson(needs) }}`. `python3 -m unittest scripts/test_verify_github_rulesets.py` still passes. No test asserts the inline gate text.

## Rollback

Revert.

## Open questions

None.
