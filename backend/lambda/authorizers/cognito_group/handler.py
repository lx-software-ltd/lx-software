"""
Optional API Gateway Lambda authorizer that validates Cognito JWTs and groups.

The lxsoftware-admin HTTP API uses API Gateway v2 ``HttpJwtAuthorizer`` plus in-handler
checks of ``cognito:groups`` in ``backend/lambda/admin/handler.py`` instead; see
``docs/architecture/security.md``.
"""
