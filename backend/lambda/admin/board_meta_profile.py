"""Give a Page or Instagram thread the sender's name. Runs on the follow-up, never on the webhook."""

from __future__ import annotations

from typing import Any

import board_meta
import board_meta_token
import board_store
from http_common import _log_event


def fill_name(table: Any, thread: dict[str, Any]) -> dict[str, Any]:
    """One Graph read per thread. A refusal is remembered so it is not asked again."""
    channel = str(thread.get("channel") or "")
    sender = str(thread.get("senderId") or "")
    if thread.get("displayName") or thread.get("nameCheckedAt") or not sender:
        return thread
    if channel not in ("page", "instagram") or (thread.get("kind") or "message") != "message":
        return thread
    name, handle = "", ""
    try:
        token = board_meta_token.page_token(board_meta.page_id()) or None
        fields = "name,username" if channel == "instagram" else "name"
        data = board_meta.graph("GET", sender, params={"fields": fields}, token=token)
        name = str(data.get("name") or data.get("username") or "")[:120]
        handle = str(data.get("username") or "")[:120]
    except board_meta.MetaError as exc:
        _log_event("info", tag="board_meta_profile_unavailable", channel=channel, error=str(exc)[:200])
    # Re-read: the webhook may have written this thread while Graph was answering.
    latest = board_store.get_meta_thread(table, str(thread.get("threadId") or "")) or thread
    latest["nameCheckedAt"] = board_store.now_iso()
    if name and not latest.get("displayName"):
        latest["displayName"] = name
    if handle:
        latest["handle"] = handle
    board_store.put_meta_thread(table, latest)
    return latest
