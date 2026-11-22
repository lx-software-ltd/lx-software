# Plan: Require the security-summary check

**Status**: Draft
**Zone**: red

`verify-rulesets.yml` is a red path. The job id stays `security-summary`. The display name becomes `security-summary`, which is the check name `main-protection` will require. This pull request does not edit the organisation ruleset.

## Goal

The security gate's `name:` is `security-summary`. `verify-rulesets` passes `required-checks: lint test security-summary`.

## Non-goals

The owner adds `security-summary` to `main-protection` after the Monday 23 Nov 14:15 HKT run, or once every caller is merged. Until that edit, the weekly verify run will fail this new input.

## Files

`.github/workflows/security.yml`, `.github/workflows/verify-rulesets.yml`, this plan.

## Invariants this change preserves

`security.yml` still runs on every pull request to `main`, with no path filter, including Dependabot. The job id and `needs` stay. `lint` and `test` stay required.

## Done when

The display name and the verify-rulesets input are `security-summary`.

## Rollback

Revert this pull request.

## Open questions

None.
