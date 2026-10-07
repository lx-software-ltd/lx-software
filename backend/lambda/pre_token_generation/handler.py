"""Cognito admin gate: Pre Sign-up and Pre Token Generation for the admin pool.

The admin user pool has exactly one audience, the LX admin console, so every
identity in it must be an administrator. The same Lambda is wired to two
triggers and fails closed on both:

* ``PreSignUp_ExternalProvider`` (first Google sign-in) raises unless the
  federated email is on ``ADMIN_EMAIL_ALLOWLIST``, so an unknown Google
  account never becomes a Cognito user.
* ``TokenGeneration_*`` raises unless the email is on the allow-list or the
  user already holds the ``admin`` group in the pool (the native bootstrap
  administrator). Cognito turns the exception into a sign-in error, so an
  unlisted account receives no ID / access / refresh token at all instead
  of a valid token that merely lacks the group. Matching users get the
  ``admin`` group override as before.

``AdminCreateUser`` (the bootstrap custom resource) is the only sign-up path
that is not gated: an operator with ``cognito-idp:AdminCreateUser`` already
controls the pool.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ADMIN_GROUP = "admin"
DENIED_MESSAGE = "This account is not authorized."

PRE_SIGN_UP_PREFIX = "PreSignUp_"
PRE_SIGN_UP_ADMIN_CREATE = "PreSignUp_AdminCreateUser"


class NotAuthorizedError(Exception):
    """Raised to make Cognito refuse the sign-up or the token issuance."""


def _norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _allowlist() -> set[str]:
    raw = os.environ.get("ADMIN_EMAIL_ALLOWLIST", "")
    return {_norm_email(x) for x in raw.split(",") if _norm_email(x)}


def _current_groups(event: dict[str, Any]) -> list[str]:
    cfg = (event.get("request") or {}).get("groupConfiguration") or {}
    raw = cfg.get("groupsToOverride")
    if not isinstance(raw, list):
        return []
    return [str(g) for g in raw if g]


def _log(**fields: Any) -> None:
    logger.info(json.dumps({"tag": "admin_auth_gate", **fields}))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    trigger = str(event.get("triggerSource") or "")
    attrs = (event.get("request") or {}).get("userAttributes") or {}
    email = _norm_email(attrs.get("email"))
    allow = _allowlist()
    matched = bool(email) and email in allow
    groups = _current_groups(event)
    in_admin_group = ADMIN_GROUP in groups
    common = {
        "trigger_source": trigger,
        "user_pool_id": event.get("userPoolId"),
        "username": event.get("userName"),
        "email": email,
        "email_verified": attrs.get("email_verified"),
        "allowlist_size": len(allow),
        "matched_admin": matched,
        "in_admin_group": in_admin_group,
    }

    if trigger.startswith(PRE_SIGN_UP_PREFIX):
        if trigger == PRE_SIGN_UP_ADMIN_CREATE:
            _log(decision="allow_admin_create_user", **common)
            return event
        if not matched:
            _log(decision="deny_sign_up", **common)
            raise NotAuthorizedError(DENIED_MESSAGE)
        _log(decision="allow_sign_up", **common)
        return event

    if matched:
        _log(decision="grant_admin", **common)
        event.setdefault("response", {})
        event["response"]["claimsOverrideDetails"] = {
            "groupOverrideDetails": {
                "groupsToOverride": [ADMIN_GROUP],
                "iamRolesToOverride": [],
                "preferredRole": None,
            }
        }
        return event
    if in_admin_group:
        _log(decision="keep_admin_group", **common)
        return event
    _log(decision="deny_token", **common)
    raise NotAuthorizedError(DENIED_MESSAGE)
