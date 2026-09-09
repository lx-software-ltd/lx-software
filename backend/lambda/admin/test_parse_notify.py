"""Unit tests for statement-parse operator email."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import parse_notify


class TestNotifyRecipients(unittest.TestCase):
    def test_empty_disables(self) -> None:
        with patch.dict("os.environ", {"STATEMENT_PARSE_NOTIFY_EMAIL": ""}, clear=False):
            self.assertEqual(parse_notify.notify_recipients(), [])

    def test_splits_and_dedupes(self) -> None:
        with patch.dict(
            "os.environ",
            {"STATEMENT_PARSE_NOTIFY_EMAIL": "a@example.com, a@example.com, bad, b@x.co"},
            clear=False,
        ):
            self.assertEqual(
                parse_notify.notify_recipients(),
                ["a@example.com", "b@x.co"],
            )


class TestNotifyFromAddress(unittest.TestCase):
    def test_explicit_from_wins(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "STATEMENT_PARSE_NOTIFY_FROM": "statements@inbound.lx-software.com",
                "INBOUND_MAIL_DOMAIN": "other.example",
            },
            clear=False,
        ):
            self.assertEqual(
                parse_notify.notify_from_address(),
                "statements@inbound.lx-software.com",
            )

    def test_builds_from_inbound_domain(self) -> None:
        env = {"INBOUND_MAIL_DOMAIN": "inbound.example.com"}
        with patch.dict("os.environ", env, clear=False):
            # Clear explicit from if a previous test set it in this process.
            with patch.dict("os.environ", {"STATEMENT_PARSE_NOTIFY_FROM": ""}, clear=False):
                self.assertEqual(
                    parse_notify.notify_from_address(),
                    "statements@inbound.example.com",
                )


class TestBuildMessage(unittest.TestCase):
    def test_skips_non_terminal(self) -> None:
        self.assertIsNone(
            parse_notify.build_parse_notify_message({"status": "processing"})
        )

    def test_success_includes_lines_and_original_filename(self) -> None:
        with patch.dict(
            "os.environ",
            {"ADMIN_WEB_ORIGIN": "https://admin.lx-software.com"},
            clear=False,
        ):
            subject, body = parse_notify.build_parse_notify_message(
                {
                    "status": "succeeded",
                    "house": "hillmarton",
                    "jobId": "abc123",
                    "source": "inbound_mail",
                    "addedLines": 4,
                    "s3Keys": [
                        "inbound/hillmarton/"
                        + ("a" * 32)
                        + "/00_KDQ170167_-_Landlord_Statement.pdf"
                    ],
                }
            )
        self.assertEqual(subject, "[32 Hillmarton] Statement parse succeeded")
        self.assertIn("Lines added: 4", body)
        self.assertIn("KDQ170167_-_Landlord_Statement.pdf", body)
        self.assertNotIn("00_KDQ", body)
        self.assertIn("inbound email", body)
        self.assertIn("https://admin.lx-software.com", body)

    def test_failure_includes_error(self) -> None:
        subject, body = parse_notify.build_parse_notify_message(
            {
                "status": "failed",
                "house": "lxSoftware",
                "jobId": "job-9",
                "source": "api",
                "errorMessage": "OpenRouter request failed with status 400",
                "s3Keys": ["uploads/sub/x/invoice.pdf"],
            }
        )
        self.assertEqual(subject, "[LX Software] Statement parse failed")
        self.assertIn("Error: OpenRouter request failed with status 400", body)
        self.assertIn("admin upload", body)
        self.assertIn("invoice.pdf", body)


class TestSend(unittest.TestCase):
    def tearDown(self) -> None:
        parse_notify.reset_ses_client_for_tests()

    def test_no_send_when_unconfigured(self) -> None:
        ses = MagicMock()
        parse_notify._sesv2 = ses
        with patch.dict("os.environ", {"STATEMENT_PARSE_NOTIFY_EMAIL": ""}, clear=False):
            self.assertFalse(
                parse_notify.notify_parse_job_outcome(
                    {"status": "succeeded", "jobId": "j", "house": "hillmarton"}
                )
            )
        ses.send_email.assert_not_called()

    def test_sends_simple_email(self) -> None:
        ses = MagicMock()
        parse_notify._sesv2 = ses
        env = {
            "STATEMENT_PARSE_NOTIFY_EMAIL": "ops@example.com",
            "STATEMENT_PARSE_NOTIFY_FROM": "statements@inbound.lx-software.com",
        }
        with patch.dict("os.environ", env, clear=False):
            self.assertTrue(
                parse_notify.notify_parse_job_outcome(
                    {
                        "status": "failed",
                        "jobId": "j1",
                        "house": "hillmarton",
                        "source": "inbound_mail",
                        "errorMessage": "rate limited",
                        "s3Keys": ["inbound/hillmarton/" + ("c" * 32) + "/00_stmt.pdf"],
                    }
                )
            )
        ses.send_email.assert_called_once()
        kwargs = ses.send_email.call_args.kwargs
        self.assertEqual(
            kwargs["FromEmailAddress"], "statements@inbound.lx-software.com"
        )
        self.assertEqual(kwargs["Destination"]["ToAddresses"], ["ops@example.com"])
        self.assertIn(
            "failed",
            kwargs["Content"]["Simple"]["Subject"]["Data"],
        )

    def test_ses_error_does_not_raise(self) -> None:
        ses = MagicMock()
        ses.send_email.side_effect = RuntimeError("sandbox")
        parse_notify._sesv2 = ses
        with patch.dict(
            "os.environ",
            {"STATEMENT_PARSE_NOTIFY_EMAIL": "ops@example.com"},
            clear=False,
        ):
            self.assertFalse(
                parse_notify.notify_parse_job_outcome(
                    {"status": "succeeded", "jobId": "j", "house": "morrison"}
                )
            )


class TestWorkerNotifyHook(unittest.TestCase):
    def test_quiet_wrapper_swallows_errors(self) -> None:
        import parse_jobs

        with patch(
            "parse_notify.notify_parse_job_outcome", side_effect=RuntimeError("boom")
        ):
            parse_jobs._notify_parse_job_quietly(
                {"status": "failed", "jobId": "x", "house": "hillmarton"}
            )


if __name__ == "__main__":
    unittest.main()
