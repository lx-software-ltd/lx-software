#!/usr/bin/env python3
"""Smoke-test the siutindei RDS Data API access used by the Executive Board.

Runs every §5.7 read view and the receivables tables through
``rds-data:ExecuteStatement`` with the same typed parameters AdminApiFn
emits (``typeHint`` UUID / DATE / DECIMAL), then a write that is wrapped
in a transaction and rolled back:

    BeginTransaction → INSERT INTO invoices (draft) → RollbackTransaction

so nothing is left behind. Prints PASS / FAIL per statement and exits 1
when anything failed. ``--dry-run`` prints the statements and parameters
without calling AWS.

Requires credentials that may call rds-data on the cluster and read the DB
secret (the same policy the ``lxsoftware`` stack grants AdminApiFn).

Usage:
  python3 scripts/siutindei/smoke_data_api.py \
      --cluster-arn arn:aws:rds:ap-southeast-1:123456789012:cluster:siutindei \
      --secret-arn arn:aws:secretsmanager:...:secret:siutindei-db \
      [--database siutindei] [--region ap-southeast-1] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_ADMIN_LAMBDA_DIR = Path(__file__).resolve().parents[2] / "backend" / "lambda" / "admin"
sys.path.insert(0, str(_ADMIN_LAMBDA_DIR))

import board_data_api  # noqa: E402
from board_data_api import Date, Numeric, Uuid  # noqa: E402


@dataclass(frozen=True)
class Statement:
    label: str
    sql: str
    parameters: list[dict[str, Any]]
    write: bool = False


def read_statements() -> list[Statement]:
    since = (date.today() - timedelta(days=30)).isoformat()
    probe_uuid = str(uuid.uuid4())
    return [
        Statement("view v_catalog_health", "SELECT district, category, activities, providers, stores, completeness, has_photo, has_price, has_schedule, has_geo FROM v_catalog_health ORDER BY activities DESC LIMIT 5", []),
        Statement(
            "view v_funnel_daily (DATE hint)",
            "SELECT day, district, searches, listing_views, cta_taps, leads_relayed, bookings_confirmed FROM v_funnel_daily WHERE day >= :dfrom ORDER BY day DESC LIMIT 5",
            board_data_api.params(dfrom=Date(since)),
        ),
        Statement("view v_provider_pipeline", "SELECT organization_id, organization_name, signed_up_on, onboarding_step, days_since_last_edit, subscription_status FROM v_provider_pipeline ORDER BY days_since_last_edit DESC LIMIT 5", []),
        Statement("table listing_plans", "SELECT COUNT(*) AS n FROM listing_plans", []),
        Statement(
            "table listing_subscriptions (UUID hint)",
            "SELECT id, payer_contact FROM listing_subscriptions WHERE id = :id",
            board_data_api.params(id=Uuid(probe_uuid)),
        ),
        Statement(
            "table listing_subscriptions (DATE hint)",
            "SELECT COUNT(*) AS n FROM listing_subscriptions WHERE status IN ('trial', 'active') AND starts_on >= :since",
            board_data_api.params(since=Date(date.today().replace(day=1))),
        ),
        Statement(
            "table invoices (UUID hint)",
            "SELECT * FROM invoices WHERE id = :id",
            board_data_api.params(id=Uuid(probe_uuid)),
        ),
        Statement(
            "table invoices aging join",
            "SELECT i.id, i.number, i.amount_hkd, i.status, i.due_on, s.organization_id FROM invoices i LEFT JOIN listing_subscriptions s ON s.id = i.subscription_id WHERE i.status IN ('sent', 'overdue') ORDER BY i.due_on LIMIT 5",
            [],
        ),
        Statement(
            "table invoices candidates (DECIMAL hint)",
            "SELECT id, number FROM invoices WHERE status IN ('draft', 'sent', 'overdue') AND (ABS(amount_hkd - :amount) <= :tol OR UPPER(fps_reference) = :ref) LIMIT 5",
            board_data_api.params(amount=Numeric(388.0), tol=Numeric(0.01), ref="-"),
        ),
        Statement(
            "table payments (UUID hint)",
            "SELECT * FROM payments WHERE id = :id",
            board_data_api.params(id=Uuid(probe_uuid)),
        ),
    ]


def write_statement() -> Statement:
    today = date.today()
    return Statement(
        "INSERT draft invoice (rolled back)",
        "INSERT INTO invoices (id, subscription_id, number, issued_on, due_on, amount_hkd, status, fps_reference) "
        "VALUES (:id, :sub, :number, :issued, :due, :amount, 'draft', :fps)",
        board_data_api.params(
            id=Uuid(str(uuid.uuid4())),
            sub=Uuid(None),
            number=f"SMOKE-{today.year}-{uuid.uuid4().hex[:6].upper()}",
            issued=Date(today),
            due=Date(today + timedelta(days=14)),
            amount=Numeric(1.0),
            fps=f"SMOKE{uuid.uuid4().hex[:8].upper()}",
        ),
        write=True,
    )


def _print_result(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


def run(args: argparse.Namespace) -> int:
    statements = read_statements()
    write = write_statement()
    if args.dry_run:
        for st in [*statements, write]:
            print(f"-- {st.label}{' [in transaction, rolled back]' if st.write else ''}")
            print(st.sql)
            if st.parameters:
                print(json.dumps(st.parameters, indent=2))
            print()
        return 0

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("rds-data", region_name=args.region) if args.region else boto3.client("rds-data")
    common = {"resource_arn": args.cluster_arn, "secret": args.secret_arn, "database": args.database}
    failures = 0
    for st in statements:
        try:
            resp = client.execute_statement(**board_data_api.statement_kwargs(st.sql, st.parameters, **common))
            rows = board_data_api._rows_from_rds(resp)
            _print_result(st.label, True, f"{len(rows)} row(s)")
        except ClientError as exc:
            failures += 1
            _print_result(st.label, False, str(exc.response.get("Error", {}).get("Message") or exc)[:300])

    tx_id = ""
    try:
        tx = client.begin_transaction(resourceArn=args.cluster_arn, secretArn=args.secret_arn, database=args.database)
        tx_id = str(tx.get("transactionId") or "")
        _print_result("BeginTransaction", bool(tx_id))
        if not tx_id:
            return 1
        try:
            resp = client.execute_statement(
                **board_data_api.statement_kwargs(write.sql, write.parameters, transaction_id=tx_id, **common)
            )
            _print_result(write.label, True, f"{int(resp.get('numberOfRecordsUpdated') or 0)} row(s) updated")
        except ClientError as exc:
            failures += 1
            _print_result(write.label, False, str(exc.response.get("Error", {}).get("Message") or exc)[:300])
    finally:
        if tx_id:
            try:
                status = client.rollback_transaction(resourceArn=args.cluster_arn, transactionId=tx_id)
                _print_result("RollbackTransaction", True, str(status.get("transactionStatus") or ""))
            except ClientError as exc:
                failures += 1
                _print_result("RollbackTransaction", False, str(exc.response.get("Error", {}).get("Message") or exc)[:300])
    print()
    print("All statements passed." if not failures else f"{failures} statement(s) failed.")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cluster-arn", default="", help="Aurora cluster ARN (SiutindeiClusterArn)")
    parser.add_argument("--secret-arn", default="", help="DB secret ARN (SiutindeiDbSecretArn)")
    parser.add_argument("--database", default="siutindei")
    parser.add_argument("--region", default="")
    parser.add_argument("--dry-run", action="store_true", help="print the statements without calling AWS")
    args = parser.parse_args(argv)
    if not args.dry_run and not (args.cluster_arn and args.secret_arn):
        parser.error("--cluster-arn and --secret-arn are required unless --dry-run")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
