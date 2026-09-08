"""Unit tests for the AWS Cost Explorer company split and allocation PDF."""

from __future__ import annotations

import base64
import unittest
from datetime import date
from unittest.mock import patch

from test_board import BoardTestCase  # noqa: E402  # stubs boto3 before other admin imports

import aws_billing  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402


def _group(organization: str, project: str, amount: str) -> dict:
    return {
        "Keys": [f"Organization${organization}", f"Project${project}"],
        "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
    }


class FakeCE:
    def __init__(self, groups: list[dict] | None = None, pages: list[list[dict]] | None = None) -> None:
        self.calls: list[dict] = []
        self.pages = pages if pages is not None else [groups or []]
        self._i = 0

    def get_cost_and_usage(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        groups = self.pages[self._i] if self._i < len(self.pages) else []
        self._i += 1
        resp: dict = {"ResultsByTime": [{"Groups": groups}]}
        if self._i < len(self.pages):
            resp["NextPageToken"] = f"page-{self._i}"
        return resp


def _client_error(message: str) -> ClientError:
    payload = {"Error": {"Code": "AccessDeniedException", "Message": message}}
    exc = ClientError(payload, "GetCostAndUsage")
    exc.response = payload  # type: ignore[attr-defined]
    return exc


class TestAssignCompany(unittest.TestCase):
    def test_siu_tin_dei_is_lx_software_org_plus_project(self) -> None:
        self.assertEqual(
            aws_billing.assign_company("LX Software", "Siu Tin Dei"), "siuTinDei"
        )

    def test_remaining_lx_software_org_is_lx_software(self) -> None:
        self.assertEqual(
            aws_billing.assign_company("LX Software", "Admin Console"), "lxSoftware"
        )
        self.assertEqual(aws_billing.assign_company("LX Software", ""), "lxSoftware")

    def test_evolve_sprouts_org_matches_any_project(self) -> None:
        self.assertEqual(
            aws_billing.assign_company("Evolve Sprouts", "Backend"), "evolveSprouts"
        )
        self.assertEqual(
            aws_billing.assign_company("Evolve Sprouts", "Public Website"),
            "evolveSprouts",
        )

    def test_personal_and_blank_are_unallocated(self) -> None:
        self.assertEqual(aws_billing.assign_company("Personal", ""), "unallocated")
        self.assertEqual(aws_billing.assign_company("", ""), "unallocated")

    def test_ce_tag_prefix_is_stripped(self) -> None:
        self.assertEqual(
            aws_billing.parse_ce_tag("Organization$Evolve Sprouts", "Organization"),
            "Evolve Sprouts",
        )
        self.assertEqual(aws_billing.parse_ce_tag("Project$", "Project"), "")


class TestSplitGroups(unittest.TestCase):
    def test_august_style_split_matches_live_tags(self) -> None:
        split = aws_billing.split_groups(
            [
                _group("Evolve Sprouts", "Backend", "432.37"),
                _group("LX Software", "Siu Tin Dei", "420.64"),
                _group("LX Software", "", "1.82"),
                _group("LX Software", "Admin Console", "1.65"),
                _group("Evolve Sprouts", "Public Website", "0.91"),
                _group("Evolve Sprouts", "Marketing", "0.40"),
                _group("Evolve Sprouts", "", "0.40"),
                _group("LX Software", "Admin Portal", "0.40"),
                _group("", "", "0.05"),
                _group("Evolve Sprouts", "Admin Website", "0.04"),
                _group("LX Software", "Public Website", "0.01"),
            ]
        )
        by_id = {row["id"]: row for row in split["companies"]}
        self.assertAlmostEqual(split["totalUsd"], 858.69)
        self.assertAlmostEqual(by_id["evolveSprouts"]["usd"], 434.12)
        self.assertAlmostEqual(by_id["siuTinDei"]["usd"], 420.64)
        self.assertAlmostEqual(by_id["lxSoftware"]["usd"], 3.88)
        self.assertAlmostEqual(by_id["unallocated"]["usd"], 0.05)
        self.assertEqual(by_id["siuTinDei"]["projects"][0]["id"], "Siu Tin Dei")
        self.assertEqual(by_id["evolveSprouts"]["projects"][0]["id"], "Backend")
        self.assertEqual(by_id["lxSoftware"]["projects"][0]["id"], "(untagged)")

    def test_catalog_companies_are_always_present(self) -> None:
        split = aws_billing.split_groups([])
        self.assertEqual(
            [row["id"] for row in split["companies"]],
            ["siuTinDei", "evolveSprouts", "lxSoftware"],
        )
        self.assertEqual(split["totalUsd"], 0.0)


class TestRange(unittest.TestCase):
    def test_default_invoice_range_is_last_complete_month(self) -> None:
        start, end = aws_billing.default_invoice_range(date(2026, 9, 8))
        self.assertEqual(start, "2026-08-01")
        self.assertEqual(end, "2026-08-31")

    def test_first_of_month_still_uses_previous_month(self) -> None:
        start, end = aws_billing.default_invoice_range(date(2026, 9, 1))
        self.assertEqual((start, end), ("2026-08-01", "2026-08-31"))

    def test_resolve_range_uses_exclusive_ce_end(self) -> None:
        start, end, ce_end = aws_billing.resolve_range("2026-08-01", "2026-08-31")
        self.assertEqual(start.isoformat(), "2026-08-01")
        self.assertEqual(end.isoformat(), "2026-08-31")
        self.assertEqual(ce_end.isoformat(), "2026-09-01")

    def test_resolve_range_rejects_inverted_and_long_windows(self) -> None:
        with self.assertRaises(ValueError):
            aws_billing.resolve_range("2026-09-02", "2026-09-01")
        with self.assertRaises(ValueError):
            aws_billing.resolve_range("2026-01-01", "2026-06-01")


class TestFetchAndPdf(unittest.TestCase):
    def test_fetch_usage_pages_and_splits(self) -> None:
        ce = FakeCE(
            pages=[
                [_group("Evolve Sprouts", "Backend", "10")],
                [_group("LX Software", "Siu Tin Dei", "5")],
            ]
        )
        payload = aws_billing.fetch_usage(
            from_day="2026-08-01", to_day="2026-08-31", ce=ce
        )
        self.assertEqual(len(ce.calls), 2)
        self.assertEqual(ce.calls[0]["TimePeriod"], {"Start": "2026-08-01", "End": "2026-09-01"})
        self.assertEqual(payload["payer"]["id"], "lxSoftware")
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["costAllocationTags"], ["Organization", "Project"])
        by_id = {row["id"]: row for row in payload["companies"]}
        self.assertAlmostEqual(payload["total"]["usd"], 15.0)
        self.assertAlmostEqual(by_id["evolveSprouts"]["usd"], 10.0)
        self.assertAlmostEqual(by_id["siuTinDei"]["usd"], 5.0)

    def test_fetch_usage_wraps_cost_explorer_errors(self) -> None:
        class Boom:
            def get_cost_and_usage(self, **kwargs: object) -> dict:
                raise _client_error("not entitled")

        with self.assertRaises(aws_billing.AwsBillingError) as ctx:
            aws_billing.fetch_usage(from_day="2026-08-01", to_day="2026-08-31", ce=Boom())
        self.assertIn("not entitled", str(ctx.exception))

    def test_allocation_pdf_lists_companies(self) -> None:
        payload = aws_billing.fetch_usage(
            from_day="2026-08-01",
            to_day="2026-08-31",
            ce=FakeCE([_group("LX Software", "Siu Tin Dei", "12.5")]),
        )
        pdf = aws_billing.render_allocation_pdf(payload)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"Siu Tin Dei", pdf)
        self.assertIn(b"12.50", pdf)
        self.assertIn(b"August 2026", pdf)
        self.assertEqual(aws_billing.pdf_filename("2026-08-01"), "lx-software-aws-2026-08.pdf")


class TestAwsUsageEndpoint(BoardTestCase):
    def test_usage_endpoint_returns_split(self) -> None:
        ce = FakeCE(
            [
                _group("Evolve Sprouts", "Backend", "20"),
                _group("LX Software", "Admin Console", "4"),
            ]
        )
        with patch("aws_billing._ce", return_value=ce):
            status, body = self.call("/aws/usage", query="from=2026-08-01&to=2026-08-31")
        self.assertEqual(status, 200)
        self.assertEqual(body["payer"]["id"], "lxSoftware")
        by_id = {row["id"]: row for row in body["companies"]}
        self.assertAlmostEqual(by_id["evolveSprouts"]["usd"], 20.0)
        self.assertAlmostEqual(by_id["lxSoftware"]["usd"], 4.0)

    def test_pdf_endpoint_returns_attachment(self) -> None:
        ce = FakeCE([_group("LX Software", "Siu Tin Dei", "9")])
        from dispatch import lambda_handler

        ev = self.event("/aws/usage.pdf", query="from=2026-08-01&to=2026-08-31")
        with patch("aws_billing._ce", return_value=ce):
            resp = lambda_handler(ev, None)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(resp["headers"]["Content-Type"], "application/pdf")
        self.assertIn("lx-software-aws-2026-08.pdf", resp["headers"]["Content-Disposition"])
        self.assertTrue(resp["isBase64Encoded"])
        pdf = base64.b64decode(resp["body"])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"Siu Tin Dei", pdf)

    def test_bad_range_is_400(self) -> None:
        status, body = self.call("/aws/usage", query="from=2026-09-10&to=2026-09-01")
        self.assertEqual(status, 400)
        self.assertIn("to must be on or after from", body["message"])


if __name__ == "__main__":
    unittest.main()
