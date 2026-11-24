# Plan: Bandit mark on the GitHub retry assert

**Status**: In progress
**Zone**: yellow

## Goal

Keep the assert in `board_github_http.py` that Bandit still reports after
test files are excluded. The line narrows the type after the retry loop
and carries `# nosec B101`.

## Non-goals

- No skip list on the Bandit action.
- No `# nosec` on test files. Tests next to the Lambda code are excluded
  by the workflow input `**/test_*.py`.
- The seeded `Random` in `board_review_sample.py` already had `# nosec B311`.
  That comment stays as it was.

## Files

- `backend/lambda/admin/board_github_http.py`

## Invariants this change preserves

The assert stays. The comment only tells Bandit the line was reviewed.

## Done when

`bandit -r backend/lambda -x '**/test_*.py'` exits 0.

## Rollback

Remove the comment. The security job fails again on this assert.

## Open questions

None.
