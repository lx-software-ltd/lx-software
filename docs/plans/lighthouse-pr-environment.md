# Plan: Lighthouse on a pull request

**Status**: In progress
**Zone**: yellow

The audit job changes which GitHub environment it selects. It does not deploy.

## Goal

A pull request that changes the public website or this workflow can run Lighthouse. Run `45095850596` on lx-software #675 failed in 3 seconds, before any step: `refs/pull/675/merge` is not allowed to deploy to `production`. That environment's deployment branch policy allows only `main`. The same rejection is on every pull request since the job started selecting `production` in #661. The Monday schedule on `main` still passes.

The schedule and `workflow_dispatch` jobs keep `environment: production`, so they still read the production `VITE_*` variables. The pull-request job does not select `production`. Dependabot stays skipped.

## Non-goals

- No change to the production deployment branch policy. Opening it would let other production workflows run from a pull request.
- No `pull_request_target`. That would build pull-request code with the production environment.
- No change to the score thresholds.

## Files

`.github/workflows/lighthouse-public-website.yml`, this plan.

## Invariants this change preserves

- The weekly audit on `main` still uses the production variables and still blocks the GTM and GA4 hosts.
- Dependabot pull requests still do not run the audit.

## Done when

A pull request run of this workflow starts the audit steps. It is not rejected for the production environment.

## Rollback

Revert this pull request.

## Open questions

None.
