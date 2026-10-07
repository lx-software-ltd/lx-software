"""Unit tests for the Cognito admin gate (Pre Sign-up + Pre Token Generation)."""

import unittest
from unittest.mock import patch

from handler import ADMIN_GROUP, NotAuthorizedError, lambda_handler

ALLOWED = "owner@example.com"
UNLISTED = "stranger@example.com"


def _event(
    trigger: str,
    email: str | None,
    groups: list[str] | None = None,
    username: str = "Google_123",
) -> dict:
    attrs = {} if email is None else {"email": email, "email_verified": "true"}
    request: dict = {"userAttributes": attrs}
    if groups is not None:
        request["groupConfiguration"] = {
            "groupsToOverride": groups,
            "iamRolesToOverride": [],
            "preferredRole": None,
        }
    return {
        "triggerSource": trigger,
        "userPoolId": "ap-southeast-1_test",
        "userName": username,
        "request": request,
        "response": {},
    }


def _override_groups(result: dict) -> list[str] | None:
    details = result.get("response", {}).get("claimsOverrideDetails")
    if not details:
        return None
    return details["groupOverrideDetails"]["groupsToOverride"]


class PreTokenGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(
            "os.environ", {"ADMIN_EMAIL_ALLOWLIST": f" {ALLOWED.upper()} , "}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_allowlisted_federated_user_gets_admin_group(self) -> None:
        result = lambda_handler(
            _event("TokenGeneration_HostedAuth", ALLOWED, groups=[]), None
        )
        self.assertEqual(_override_groups(result), [ADMIN_GROUP])

    def test_allowlist_match_is_case_and_whitespace_insensitive(self) -> None:
        result = lambda_handler(
            _event("TokenGeneration_HostedAuth", f"  {ALLOWED.title()} ", groups=[]),
            None,
        )
        self.assertEqual(_override_groups(result), [ADMIN_GROUP])

    def test_unlisted_federated_user_is_refused_a_token(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(
                _event("TokenGeneration_HostedAuth", UNLISTED, groups=[]), None
            )

    def test_unlisted_user_with_other_groups_is_refused(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(
                _event("TokenGeneration_HostedAuth", UNLISTED, groups=["viewer"]),
                None,
            )

    def test_missing_email_is_refused(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(_event("TokenGeneration_HostedAuth", None, groups=[]), None)

    def test_refresh_for_unlisted_user_is_refused(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(
                _event("TokenGeneration_RefreshTokens", UNLISTED, groups=[]), None
            )

    def test_native_admin_group_member_keeps_token_without_allowlist(self) -> None:
        result = lambda_handler(
            _event(
                "TokenGeneration_Authentication",
                UNLISTED,
                groups=[ADMIN_GROUP],
                username="bootstrap",
            ),
            None,
        )
        self.assertIsNone(_override_groups(result))
        self.assertEqual(
            result["request"]["groupConfiguration"]["groupsToOverride"],
            [ADMIN_GROUP],
        )

    def test_empty_allowlist_still_denies_everyone_but_group_members(self) -> None:
        with patch.dict("os.environ", {"ADMIN_EMAIL_ALLOWLIST": ""}):
            with self.assertRaises(NotAuthorizedError):
                lambda_handler(
                    _event("TokenGeneration_HostedAuth", ALLOWED, groups=[]), None
                )
            result = lambda_handler(
                _event(
                    "TokenGeneration_Authentication",
                    ALLOWED,
                    groups=[ADMIN_GROUP],
                    username="bootstrap",
                ),
                None,
            )
            self.assertIsNone(_override_groups(result))

    def test_group_configuration_is_optional(self) -> None:
        result = lambda_handler(_event("TokenGeneration_HostedAuth", ALLOWED), None)
        self.assertEqual(_override_groups(result), [ADMIN_GROUP])
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(_event("TokenGeneration_HostedAuth", UNLISTED), None)


class PreSignUpTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict("os.environ", {"ADMIN_EMAIL_ALLOWLIST": ALLOWED})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unlisted_google_account_cannot_be_created(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(_event("PreSignUp_ExternalProvider", UNLISTED), None)

    def test_allowlisted_google_account_is_created_unchanged(self) -> None:
        event = _event("PreSignUp_ExternalProvider", ALLOWED)
        result = lambda_handler(event, None)
        self.assertIs(result, event)
        self.assertEqual(result["response"], {})

    def test_self_sign_up_is_refused_for_unlisted_email(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(
                _event("PreSignUp_SignUp", UNLISTED, username=UNLISTED), None
            )

    def test_admin_create_user_is_not_gated(self) -> None:
        event = _event("PreSignUp_AdminCreateUser", UNLISTED, username=UNLISTED)
        self.assertIs(lambda_handler(event, None), event)


if __name__ == "__main__":
    unittest.main()
