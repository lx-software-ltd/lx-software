# Plan: Clear open code scanning alerts

**Status**: Done
**Zone**: red

## Goal

Clear the open Semgrep alerts. The usage-pull log no longer contains a
credential word. Each remaining `urlopen` either already targets a fixed
https API or gains an https check, and carries the same in-source
Semgrep mark the other API clients use.

## Non-goals

- No change to Cloudflare, OpenRouter, or analytics behaviour.
- No new live API calls.

## Files

- `backend/lambda/admin/openrouter_usage_pull.py`
- `scripts/configure-public-analytics.py`
- `scripts/report-public-analytics.py`
- `scripts/sync-ses-sending-dns.py`
- `scripts/cloudflare/publish-apex-redirect.py`
- `scripts/mint-openrouter-app-keys.py`

## Invariants this change preserves

The usage pull still records `management_key_missing` when the field is
absent. Analytics and DNS scripts still call the same https APIs.

## Done when

`python3 -m unittest backend/lambda/admin/test_openrouter_usage_pull.py`
passes.

## Rollback

Restore the previous log text and remove the https checks and comments.

## Open questions

None.
