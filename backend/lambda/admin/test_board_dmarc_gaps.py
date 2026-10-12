"""DMARC gap reasons and the fresh-summary hide set."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import board_config_gaps
import board_dmarc
import board_dmarc_gaps
import board_duties
from test_board import BoardTestCase


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finding(kind: str = "own_sender_failing") -> dict:
    return {
        "kind": kind,
        "severity": "high",
        "evidence": {
            "sender": "siutindei.com",
            "sourceIp": "203.0.113.9",
            "dkim": "fail",
            "spf": "fail",
            "quarantine": 1,
            "reject": 0,
            "bothFail": 1,
            "count": 2,
            "failedAuthDomains": ["mail.gmail.com"],
        },
    }


class MatchKnownTests(BoardTestCase):
    def test_match_known_is_public_and_matches_a_subdomain(self) -> None:
        self.assertEqual(board_dmarc.match_known("mail.gmail.com", {"gmail.com"}), "gmail.com")
        self.assertEqual(board_dmarc.match_known("evil.example", {"gmail.com"}), "")


class SummaryGapIdTests(BoardTestCase):
    def _put(self, **payload: object) -> None:
        board_store_payload = {"generatedAt": _now(), "enabled": True, "findings": [], **payload}
        import board_store

        board_store.put_cache(self.table, "dmarc:summary", board_store_payload)

    def test_missing_summary_does_not_hide(self) -> None:
        self.assertIsNone(board_dmarc_gaps.summary_gap_ids(self.table))

    def test_fresh_own_sender_finding_is_listed(self) -> None:
        self._put(findings=[_finding()])
        self.assertEqual(board_dmarc_gaps.summary_gap_ids(self.table), {"dmarc:siutindei.com"})

    def test_stale_disabled_and_capped_summaries_do_not_hide(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._put(generatedAt=old, findings=[])
        self.assertIsNone(board_dmarc_gaps.summary_gap_ids(self.table))
        self._put(enabled=False, findings=[])
        self.assertIsNone(board_dmarc_gaps.summary_gap_ids(self.table))
        self._put(findings=[{"kind": "policy_drift", "evidence": {"domain": f"d{i}.example"}} for i in range(30)])
        self.assertIsNone(board_dmarc_gaps.summary_gap_ids(self.table))


class NoteGapTests(BoardTestCase):
    def test_note_writes_the_gap_cache_without_the_duty_wrappers(self) -> None:
        finding = _finding()
        with (
            patch.object(board_duties, "note_config_gap", side_effect=AssertionError("hop")),
            patch.object(board_duties, "list_config_gaps", side_effect=AssertionError("hop")),
            patch.object(board_duties, "clear_config_gap", side_effect=AssertionError("hop")),
        ):
            board_dmarc_gaps.note(self.table, [finding])
            rows = board_config_gaps.list_config_gaps(self.table)
            self.assertEqual([row.get("gapId") for row in rows], ["dmarc:siutindei.com"])
            self.assertIn("203.0.113.9", rows[0]["reason"])
            board_dmarc_gaps.note(self.table, [])
        self.assertEqual(board_config_gaps.list_config_gaps(self.table), [])
