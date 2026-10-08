---
name: add-admin-route
description: Add an admin HTTP route across the Lambda, the CDK integration, the SPA client, and the mock API.
---

# Add an admin route

1. Handle the route in `backend/lambda/admin/dispatch.py` and call the existing `_require_admin` (`http_common.py`). Adding that route is yellow. Changing `_require_admin`, or `write_blocked` in `board_public_api.py`, is red (`docs/architecture/zones.md`). Follow that owner-only list rather than inventing a second one.
2. Register the path with `SharedPermissionLambdaIntegration`. Do not add a per-route Lambda permission.
3. Call it from `apps/admin_web` through `adminFetch`.
4. Add the fixture response in `src/lib/mock/routes/` and `src/lib/mock/fixtures.ts` so `npm run dev:mock` serves it.
5. Add a line to `docs/deployment/admin-website.md` when the route is something an operator runs.
6. Cover the handler in the matching `test_*.py`.

Writes that the public API must not expose stay off `/public/*`. A public route also needs an authorizer decision: JWT, API key scope, or the documented unauthenticated token routes.
