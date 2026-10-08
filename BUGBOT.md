# Bugbot

Review for behavior, security, and contract drift. Mechanical checks
already cover formatting, file length, focused tests, and agent-rule shape.

## Zones

Red paths need an explicit human approval noted in the pull request.
The list is `docs/architecture/zones.md`. Flag a red-path edit that
does not mention that approval.

## Invariants

- Do not hardcode secrets. Secret CDK parameters set `noEcho`.
- Personal data stays off the hashed denylist. The public site owner
  name in `site.json` and the product mailboxes are the exceptions.
- Admin routes keep `_require_admin`. Owner-only routes stay on the
  list in `dispatch.py`.
- Model calls go through `openrouter_client.py` and never run inside
  an HTTP request.
- The HTTP API keeps one shared Lambda invoke permission.
- Public website copy stays in `site.json`.

## Skip

- Do not ask to move rules back into `.cursorrules`. That file is a
  pointer. Rules live in `.cursor/rules/`.
- Do not ask for a file-length split below the allowance recorded in
  `scripts/file-length-allowlist.txt`. The allowance only shrinks.
- Do not file issues from `NOTE:` or `SECURITY NOTE:` comments.
