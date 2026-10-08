---
name: verify-change
description: Choose the commands that prove a change and record the evidence in the pull request.
---

# Verify a change

Run the narrowest command that exercises the edit, then the area lint. Paste the commands and the result into the pull request.

- Public website: `npm test` and `npm run lint` in `apps/public_www`. `npm run build` when a route, `site.json`, or pre-render output changed.
- Admin web unit: `npm run test:unit` in `apps/admin_web`. `npm test` also runs the Python unit tests and is the right command when a Lambda changed with the SPA.
- Admin web browser: `npm run dev:mock`, then exercise the changed flow. `npm run test:e2e` when layout or navigation changed.
- One Lambda: `python3 -m unittest discover -p 'test_*.py' -v` in that Lambda directory (`backend/lambda/admin`, `public_api_authorizer`, `pre_token_generation`, or `siutindei_schema`).
- CDK: `npm test` and `npm run build` in `backend/infrastructure` when a stack changed.
- Contracts: `python3 scripts/sync-contracts.py` then `python3 scripts/check-contracts.py`.
- Personal data: `python3 scripts/check_pii.py`.
- Agent rules: `python3 scripts/validate_agent_rules.py`.

A UI behavior change is verified in the browser (click, type, submit, and the other screens that share the state).

## Done

The pull request lists the zone, the checks you ran, and whether docs or contracts changed. CI remains the merge gate. Cloud agents do not fire the `stop` hook.
