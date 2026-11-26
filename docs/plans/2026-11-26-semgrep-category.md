# Plan: Refresh the Semgrep category the open alerts use

**Status**: Done
**Zone**: red

## Goal

The open Semgrep alerts stay visible because the scan uploads `semgrep` from `semgrep.yml`. They were filed under `.github/workflows/security.yml:semgrep`. Pin the Semgrep action that uploads both categories.

## Non-goals

The usage-pull log and the https checks stay as they are.

## Files

Every `lx-software-ltd/actions` pin and `.pre-commit-config.yaml`.

## Invariants this change preserves

Workflow text other than the pin stays the same. One pin is used everywhere. No live mutation script runs.

## Done when

Workflow conformance against the pinned actions checkout passes.

## Rollback

Restore the previous pin and the pre-commit rev.

## Open questions

None.
