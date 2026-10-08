# AGENTS.md

## Cursor Cloud specific instructions

Applies to Cursor agents working in this repository.

## Bootstrap

1. Always-applied constraints are in `.cursor/rules/00-repository-core.mdc`. Path-scoped rules in `.cursor/rules/` attach for the area you edit.
2. Procedures live in `.cursor/skills/*/SKILL.md`.
3. `.cursorrules` is a pointer. Do not add rules there.
4. Operational detail lives in `docs/architecture/` and `docs/deployment/`. The Executive Board is `docs/architecture/executive-board.md`. Admin operations are `docs/deployment/admin-website.md`. The public site is `docs/deployment/public-website.md`.

## Zones

Autonomy follows blast radius. The map is `docs/architecture/zones.md`. The stricter zone wins. If scope grows into a stricter zone, stop and ask.

- **Red.** Plan in chat and wait for explicit approval before any write.
- **Yellow.** Write a short plan under `docs/plans/` from `docs/plans/_template.md`, add or update tests first, then implement.
- **Green.** Implement and verify. Summarise intent in the pull request.

## Cursor Cloud

| Service | Path | Dev command | Port |
| --- | --- | --- | --- |
| Public website | `apps/public_www/` | `npm run dev` | 5173 |
| Admin console | `apps/admin_web/` | `npm run dev` | 5174 |
| Admin fixtures | `apps/admin_web/` | `npm run dev:mock` | 5174 |

Copy `apps/admin_web/.env.example` to `.env` for a real API. `npm run dev:mock` needs no AWS. Read `.cursor/skills/cursor-cloud/SKILL.md` before running services.

Lint and test with `npm run lint`, `npm test`, and `npm run build` in `apps/public_www`, `apps/admin_web`, and `backend/infrastructure`. Admin `npm test` runs Vitest and the Python unit tests. `npm run test:unit` is Vitest only. `npm run test:e2e` is the Playwright smoke.

## Evidence

A change is done when the `verify-change` skill's checks pass and the pull request template is filled in. Hooks format edits and block destructive shell commands. Cloud agents do not fire the `stop` hook. CI remains the merge gate.

## Hooks

`.cursor/hooks.json` denies force-push, pushes to `main`, `git reset --hard`, deleting `main`, `rm -rf` outside the repository and `/tmp`, `cdk deploy` and `cdk destroy`, `aws delete-*`, and the live-mutation scripts named in `.cursor/rules/scripts.mdc`. It asks before `git commit --amend`.
