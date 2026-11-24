# Plan: Name the dependency workflow Dependency Submission

**Status**: Done
**Zone**: `.github/workflows/dependency-graph.yml` is unlisted in `docs/architecture/zones.md`. Red workflow paths are `.github/workflows/deploy-*.yml`, `manage-api-keys.yml`, `mint-openrouter-keys.yml`, and `verify-rulesets.yml`. This file is the dependency submission workflow, and it is not one of those. Yellow is remaining `backend/lambda/**` and `apps/admin_web/src/**`. This plan is under `docs/**`, which is green.

## Goal

The Actions tab uses title case. GitHub's built-in Dependency Graph entry sits next to this workflow, so the workflow display name must be Dependency Submission. The check and submit job display names use the same title.

## Non-goals

- Renaming the workflow file, the job ids `check` and `submit`, or any step name
- Changing action pins, triggers, permissions, or comments
- Editing `.pre-commit-config.yaml`
- Adding a Sync Labels workflow or renaming Deploy iOS
- Adding tests for display strings

## Files

- `docs/plans/2026-11-24-dependency-submission-name.md` (this plan)
- `.github/workflows/dependency-graph.yml` — workflow `name:` and the `check` and `submit` job `name:` fields

## Invariants this change preserves

- Job ids stay `check` and `submit`
- The dependency-graph action pin stays `lx-software-ltd/actions/dependency-graph@7d93bef212616595c866a76b03862eb72abbb746 # main 2026-11-23`
- Triggers, permissions, `if` conditions, and step names stay as they are
- The workflow file name stays `dependency-graph.yml`

## Done when

`python3` on `workflow-conformance/check_workflows.py` from `lx-software-ltd/actions` at `7d93bef212616595c866a76b03862eb72abbb746`, with `CONFORMANCE_MODE=enforce`, `CONFORMANCE_PROFILE=product`, `CONFORMANCE_ROOT` set to this checkout, and `CONFORMANCE_ALIGNMENT=warn`, prints `Workflow conformance passed.`

## Rollback

Revert the commit. The Actions tab shows the previous display names. Submission behavior is unchanged because only `name:` strings change.

## Open questions

None.
