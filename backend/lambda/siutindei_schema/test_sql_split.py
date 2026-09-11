"""Tests for splitting receivables.sql into Data API statements."""

from __future__ import annotations

import unittest
from pathlib import Path

import sql_split


class SplitTests(unittest.TestCase):
    def test_repo_sql_file_is_the_packaged_source(self) -> None:
        repo = Path(__file__).resolve().parents[3] / "scripts" / "siutindei" / "receivables.sql"
        self.assertTrue(repo.is_file())
        self.assertEqual(sql_split.load_receivables_sql(), repo.read_text(encoding="utf-8"))

    def test_skips_begin_commit_and_keeps_dollar_quoted_do(self) -> None:
        stmts = sql_split.split_sql(
            """
            BEGIN;
            CREATE TABLE IF NOT EXISTS listing_plans (id uuid);
            -- comment
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'board_api') THEN
                    CREATE ROLE board_api NOLOGIN;
                END IF;
            END
            $$;
            GRANT SELECT ON listing_plans TO board_api;
            COMMIT;
            """
        )
        self.assertEqual(len(stmts), 3)
        self.assertTrue(stmts[0].startswith("CREATE TABLE"))
        self.assertIn("CREATE ROLE board_api", stmts[1])
        self.assertTrue(stmts[1].strip().endswith("$$"))
        self.assertTrue(stmts[2].startswith("GRANT SELECT"))

    def test_receivables_script_yields_tables_views_and_grants(self) -> None:
        stmts = sql_split.receivables_statements()
        joined = "\n".join(stmts)
        self.assertGreaterEqual(len(stmts), 10)
        self.assertIn("CREATE TABLE IF NOT EXISTS listing_plans", joined)
        self.assertIn("CREATE OR REPLACE VIEW v_catalog_health", joined)
        self.assertIn("CREATE OR REPLACE VIEW v_funnel_daily", joined)
        self.assertIn("CREATE OR REPLACE VIEW v_provider_pipeline", joined)
        self.assertIn("CREATE ROLE board_api", joined)
        self.assertNotIn("\nBEGIN;", "\n" + joined)
        self.assertNotIn("\nCOMMIT;", "\n" + joined)


if __name__ == "__main__":
    unittest.main()
