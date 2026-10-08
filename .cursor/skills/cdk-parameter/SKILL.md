---
name: cdk-parameter
description: Add a CDK parameter with the right prefix, a params file entry, and the Jest guard.
---

# Add a CDK parameter

1. Pick the prefix. Board-only controls are `SiutindeiBoard*`. Product resources the stack integrates with are `Siutindei*` or `Evolvesprouts*`. Stack-wide knobs (Cognito, OpenRouter, inbound mail, Enable Banking, public origins) stay unprefixed.
2. Add the `CfnParameter` in the stack. Secret values set `noEcho: true`.
3. Add the key to `backend/infrastructure/params/*.json` for each environment that deploys it. An unknown `lxsoftware:*` key fails `cdk deploy`.
4. Keep the Lambda environment variable short (`BOARD_*`, `OUTREACH_*`). Do not rename existing env vars to match the new prefix.
5. Extend the Jest guard in `backend/infrastructure/test/lxsoftware-stack.test.ts` when the parameter is a new board or product prefix.
6. Mention the parameter in `docs/deployment/admin-website.md` when an operator has to set it.
