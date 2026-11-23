# Plan: Read-only workflow tokens

**Status**: In progress
**Zone**: yellow

Parent plan: Shared actions repository and CI convergence, step SA-102.

## Goal

lint.yml, test.yml, and check-lockfiles.yml set permissions contents read at the top. No job in these files asks the token for more.

## Non-goals

No job logic change. No runner change. Gate jobs lint and test stay inline. verify-rulesets.yml already sets contents read.

## Files

- .github/workflows/lint.yml
- .github/workflows/test.yml
- .github/workflows/check-lockfiles.yml
- docs/plans/sa-102-workflow-contents-read.md

## Invariants this change preserves

Checkout still works. Checks named lint and test stay. No secret is added.

## Done when

Each of the three workflows has a top-level permissions block of contents read, and no job overrides it.

## Rollback

Revert the pull request.
