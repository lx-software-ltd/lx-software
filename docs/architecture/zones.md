# Agent work zones

Autonomy follows blast radius. A person draws this map. A change that
touches more than one zone uses the stricter zone. If implementation
spreads into a stricter zone, stop and ask.

## Red

Plan in chat and wait for explicit approval before any write. A human
pairs on the change.

- `backend/infrastructure/**`
- `backend/lambda/public_api_authorizer/**`
- `backend/lambda/pre_token_generation/**`
- `backend/lambda/admin/board_code.py`
- `_require_admin` in `backend/lambda/admin/http_common.py`
- The owner-only route list in `backend/lambda/admin/board_public_api.py` (`write_blocked`)
- `contracts/**`
- `scripts/deploy/**`
- `scripts/cloudflare/**`
- `scripts/check-pii.sh`
- `scripts/check_pii.py`
- `scripts/pii-denylist.sha256`
- `scripts/manage-public-api-keys.py`
- `scripts/mint-openrouter-app-keys.py`
- `.github/workflows/deploy-*.yml`
- `.github/workflows/manage-api-keys.yml`
- `.github/workflows/mint-openrouter-keys.yml`
- `.github/workflows/verify-rulesets.yml`
- `.cursor/hooks.json`
- `.cursor/hooks/**`
- `.pre-commit-config.yaml`

`board_code.py` dispatches workflows in the siutindei repository.
Changing `_require_admin` or `write_blocked` is red. Adding a route in
`dispatch.py` that calls those helpers is yellow.

## Yellow

Write a short plan from `docs/plans/_template.md` before editing. Add
or update tests first, then implement.

- Remaining `backend/lambda/**`
- `apps/admin_web/src/**`

## Green

Implement and verify. Summarise intent in the pull request.

- `apps/public_www/**` outside deploy scripts
- `docs/**`
- Test-only edits that do not sit on a red path

Hooks still format edits and block destructive commands in every zone.
CI remains the merge gate.
