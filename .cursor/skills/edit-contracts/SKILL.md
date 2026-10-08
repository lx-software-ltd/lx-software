---
name: edit-contracts
description: Change a shared constant in contracts/*.json and sync the generated copies.
---

# Edit a shared contract

1. Edit `contracts/*.json` only. Do not hand-edit `apps/admin_web/src/lib/contracts/generated.ts`, the Python constants module, or the CDK copy.
2. Run `python3 scripts/sync-contracts.py`.
3. Run `python3 scripts/check-contracts.py`.
4. Commit the JSON and the generated files together.
5. An unknown `lxsoftware:*` key fails `cdk deploy`. Parameter names follow `.cursor/rules/infrastructure-cdk.mdc`.

`python3 scripts/check-contracts.py` is also a CI job. A contract change that skips the sync fails that job.
