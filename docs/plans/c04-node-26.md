# Plan: Node 26 and the actions pin

**Status**: Draft
**Zone**: red

The pre-commit `rev` is a red path. Pair B also pins `verify-rulesets.yml`, which is red. Deploy workflows that still pass an older Node version are red. Gate G2 already covers the hook repository. This pull request does not change hook behaviour: `9235676` does not touch the hook scripts or `verify-rulesets`. No deploy workflow is run.

## Goal

Move every `lx-software-ltd/actions` pin and the pre-commit `rev` from `61b67ed4f686659433f6ca4cb10c80707e365cd0` to `9235676200771b2f93bc01ac85f3de1392133182`. Finish C04: the shared `setup-node` action is called without `node-version`, so its default `26` applies. A direct `actions/setup-node` call that is not already `26` passes `"26"`.

## Non-goals

Stages 5 and 6. SA-701 and SA-702. Flutter version pins. No deploy, bootstrap, or key-management workflow is triggered.

## Files

`.github/workflows/*.yml`, `.pre-commit-config.yaml`, this plan.
`lighthouse-public-website.yml` drops the quotes around `statuses`.

## Invariants this change preserves

- One actions commit. `workflow-conformance` stays `mode: enforce`.
- `lint` and `test` stay the required check names.
- Direct `actions/setup-node` calls that already pass `"26"` stay as they are. That action has no organisation default.
- No long-lived AWS key is added.

## Done when

No workflow passes `node-version: lts/*`, `24`, or `22.22.2`. Every shared `setup-node` call omits `node-version`. The actions pin and the pre-commit `rev` are `9235676200771b2f93bc01ac85f3de1392133182`.

## Rollback

Revert this pull request. The previous pin stays valid.

## Open questions

None.
