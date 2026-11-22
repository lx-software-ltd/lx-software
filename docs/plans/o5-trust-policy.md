# Plan: Narrow the GitHub Actions trust document

**Status**: Draft
**Zone**: yellow

## Goal

The public trust document lists exactly the four product repositories. The account id stays the placeholder `ACCOUNT_ID`. The owner applies the same document to `GitHubActionsRole` in IAM.

## Non-goals

No IAM API call. No deploy. The `actions` repository is not a trusted subject.

## Files

`docs/architecture/github-actions-trust-policy.json`, this plan.

## Invariants this change preserves

The federated principal and the audience stay as they are. No account id is written.

## Done when

The `sub` condition is the four `repo:lx-software-ltd/<name>:*` values and nothing else.

## Rollback

Revert this pull request. IAM is unchanged until the owner applies the document.

## Open questions

None.
