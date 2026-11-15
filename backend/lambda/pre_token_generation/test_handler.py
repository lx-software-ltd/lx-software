"""Unit tests for the Cognito admin gate (Pre Sign-up + Pre Token Generation)."""

import json
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
    identities: str | None = None,
) -> dict:
    attrs = {} if email is None else {"email": email, "email_verified": "true"}
    if identities is not None:
        attrs["identities"] = identities
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


def _google_identities() -> str:
    return json.dumps([{"providerName": "Google", "providerType": "Google", "userId": "123"}])


def _override_groups(result: dict) -> list[str] | None:
    details = result.get("response", {}).get("claimsOverrideDetails")
    if not details:
        return None
    return details["groupOverrideDetails"]["groupsToOverride"]


class PreTokenGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict("os.environ", {"ADMIN_EMAIL_ALLOWLIST": f" {ALLOWED.upper()} , "})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_allowlisted_federated_user_gets_admin_group(self) -> None:
        result = lambda_handler(_event("TokenGeneration_HostedAuth", ALLOWED, groups=[]), None)
        self.assertEqual(_override_groups(result), [ADMIN_GROUP])

    def test_allowlist_match_is_case_and_whitespace_insensitive(self) -> None:
        result = lambda_handler(
            _event("TokenGeneration_HostedAuth", f"  {ALLOWED.title()} ", groups=[]),
            None,
        )
        self.assertEqual(_override_groups(result), [ADMIN_GROUP])

    def test_unlisted_federated_user_is_refused_a_token(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(_event("TokenGeneration_HostedAuth", UNLISTED, groups=[]), None)

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
            lambda_handler(_event("TokenGeneration_RefreshTokens", UNLISTED, groups=[]), None)

    def test_refresh_for_allowlisted_google_user_is_granted(self) -> None:
        result = lambda_handler(_event("TokenGeneration_RefreshTokens", ALLOWED, groups=[]), None)
        self.assertEqual(_override_groups(result), [ADMIN_GROUP])

    def test_allowlisted_native_user_is_refused_including_refresh(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(
                _event(
                    "TokenGeneration_RefreshTokens",
                    ALLOWED,
                    groups=[ADMIN_GROUP],
                    username="native-user",
                ),
                None,
            )

    def test_identities_attribute_counts_as_google(self) -> None:
        result = lambda_handler(
            _event(
                "TokenGeneration_RefreshTokens",
                ALLOWED,
                groups=[],
                username="native-looking",
                identities=_google_identities(),
            ),
            None,
        )
        self.assertEqual(_override_groups(result), [ADMIN_GROUP])

    def test_admin_group_membership_does_not_grant_a_token(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(
                _event(
                    "TokenGeneration_Authentication",
                    UNLISTED,
                    groups=[ADMIN_GROUP],
                    username="native-user",
                ),
                None,
            )

    def test_empty_allowlist_denies_group_members(self) -> None:
        with patch.dict("os.environ", {"ADMIN_EMAIL_ALLOWLIST": ""}):
            with self.assertRaises(NotAuthorizedError):
                lambda_handler(_event("TokenGeneration_HostedAuth", ALLOWED, groups=[]), None)
            with self.assertRaises(NotAuthorizedError):
                lambda_handler(
                    _event(
                        "TokenGeneration_Authentication",
                        ALLOWED,
                        groups=[ADMIN_GROUP],
                        username="Google_123",
                    ),
                    None,
                )

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

    def test_allowlisted_external_signup_without_google_username_is_refused(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(
                _event(
                    "PreSignUp_ExternalProvider",
                    ALLOWED,
                    username=ALLOWED,
                ),
                None,
            )

    def test_self_sign_up_is_refused_for_unlisted_email(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(_event("PreSignUp_SignUp", UNLISTED, username=UNLISTED), None)

    def test_self_sign_up_is_refused_for_allowlisted_email(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(_event("PreSignUp_SignUp", ALLOWED, username=ALLOWED), None)

    def test_admin_create_user_is_refused(self) -> None:
        with self.assertRaises(NotAuthorizedError):
            lambda_handler(_event("PreSignUp_AdminCreateUser", ALLOWED, username=ALLOWED), None)


if __name__ == "__main__":
    unittest.main()
