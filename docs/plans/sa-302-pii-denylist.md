# SA-302 — shared PII check

**Status**: This pull request
**Zone**: yellow

## Intent

Call `pii-denylist` from CI instead of `scripts/check_pii.py`. Gate G2 is approved. The local script, shell wrapper, and unit test stay until SA-307.

## What changed

The CI jobs that ran `python3 scripts/check_pii.py` call `lx-software-ltd/actions/pii-denylist`. Every `lx-software-ltd/actions` pin in this repository is `f33bc376b6745fcf47a4af88e436ce14b8e55c9b`, the merge that put the action on `main`. Inputs, runners, and the normalization unit test stay.

## Rollback

Revert this pull request.
