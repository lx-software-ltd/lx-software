"""Facts copied onto a catalog describe row, and generic host-root URLs."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def generic_host_root(url: str) -> bool:
    """True for a host with no path, such as ``https://lcsd.gov.hk/``."""
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return False
    return (parsed.path or "") in ("", "/") and not parsed.query


def describe_candidate(cand: dict[str, Any], name: str, url: str) -> dict[str, str]:
    """Name and URL plus address, phone and coordinates already on the record."""
    row = {"name": name, "url": url}
    address = str(cand.get("addressEn") or cand.get("address") or "").strip()
    phone = str(cand.get("phone") or "").strip()
    if address:
        row["address"] = address[:200]
    if phone:
        row["phone"] = phone[:40]
    if cand.get("lat") not in (None, ""):
        row["lat"] = str(cand.get("lat"))
    if cand.get("lng") not in (None, ""):
        row["lng"] = str(cand.get("lng"))
    return row


_HANDOFF_TTL = 10 * 365 * 86400


def remember_handoff(table: Any, event_id: str, task_id: str) -> None:
    """Remember a handoff so a long delivered list cannot open a second one."""
    import board_store

    try:
        board_store.put_cache(
            table,
            f"catalog:handoff:{event_id}",
            {"taskId": task_id},
            ttl_seconds=_HANDOFF_TTL,
        )
    except Exception:
        return


def handoff_blocked(table: Any, event_id: str) -> bool:
    """True when this organisation already has a handoff, open or delivered."""
    import board_store

    if board_store.get_cache(table, f"catalog:handoff:{event_id}"):
        return True
    from board_triage import find_event_task, find_open_event_task

    if find_open_event_task(table, "catalog-handoff", event_id, limit=2000):
        remember_handoff(table, event_id, "open")
        return True
    found = find_event_task(table, "catalog-handoff", event_id, status="delivered", limit=5000)
    if found:
        remember_handoff(table, event_id, str(found.get("taskId") or ""))
        return True
    return False
