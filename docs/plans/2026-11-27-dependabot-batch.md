# Plan: Batch routine Dependabot updates

**Status**: Done
**Zone**: yellow

## Goal

Add `.github/workflows/dependabot-batch.yml` from the shared template.
The workflow opens one pull request for the routine Dependabot updates
in this repository. The owner merges that pull request.

## Non-goals

No change to `.github/dependabot.yml`. No batch of workflow changes,
major updates, or the `actions-pin` group. No merge from this workflow.

## Files

- `.github/workflows/dependabot-batch.yml`
- `scripts/test_dependabot_batch_workflow.py`
- `docs/plans/README.md`

## Invariants this change preserves

Top-level permissions stay `contents: read`. The job sets
`actions: write`, `checks: read`, `contents: write`, and
`pull-requests: write`. The action pin is the same commit as the other
workflows. The workflow is not a required check.

## Done when

`python3 -m unittest scripts/test_dependabot_batch_workflow.py -v`
passes, and workflow conformance accepts the file against the template.

## Rollback

Delete `.github/workflows/dependabot-batch.yml` and
`scripts/test_dependabot_batch_workflow.py`.

## Open questions

None.
