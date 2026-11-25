"""Approvals that will expire soon, for the daily review email."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_hk
import board_store


def pending(table: Any, *, within_hours: int = 48) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    start = board_hk.to_iso(now)
    end = board_hk.to_iso(now + timedelta(hours=within_hours))
    out: list[dict[str, Any]] = []
    for approval in board_store.list_approvals(table):
        if str(approval.get("status") or "") != "pending":
            continue
        expires = str(approval.get("autoRejectAt") or "")
        if not expires or expires <= start or expires > end:
            continue
        out.append(
            {
                "approvalId": approval.get("approvalId"),
                "summary": str(approval.get("summary") or approval.get("op") or "")[:160],
                "autoRejectAt": expires,
            }
        )
    out.sort(key=lambda row: str(row.get("autoRejectAt") or ""))
    return out


def lines(rows: list[dict[str, Any]]) -> list[str]:
    return [
        (
            f"Approval {row.get('approvalId')} expires {str(row.get('autoRejectAt') or '')[:16]} "
            f"without a decision: {row.get('summary')}"
        )
        for row in rows
        if isinstance(row, dict)
    ]
