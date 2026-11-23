"""Hourly catch-up for Page and Instagram conversations the webhook missed.

WhatsApp has no conversation read. Its past comes only from the one-off history import.
"""

from __future__ import annotations

from typing import Any

import board_meta
import board_meta_ingest
import board_meta_store
import board_meta_token
from contract_constants import BOARD_TOOLS_CONTRACT
from http_common import _log_event

_LIMITS = BOARD_TOOLS_CONTRACT["limits"]
_THREADS = int(_LIMITS["metaBackfillThreadsPerRun"])
_MEDIA_MAX = int(_LIMITS["metaMediaPerMessageMax"])
_FIELDS = "id,updated_time,participants,messages.limit(20){id,message,from,created_time,attachments{mime_type,name,file_url,image_data,video_data}}"


def backfill(table: Any) -> dict[str, Any]:
    page = board_meta.page_id()
    if not page:
        return {"skipped": "no page"}
    own = _own_ids(page)
    writer = board_meta_store.Writer(table)
    inserted = 0
    follow: dict[str, dict[str, str]] = {}
    for platform, channel in (("messenger", "page"), ("instagram", "instagram")):
        try:
            rows = board_meta.graph_pages("GET", f"{page}/conversations", {"platform": platform, "fields": _FIELDS}, limit=_THREADS)
        except board_meta.MetaError as exc:
            _log_event("warning", tag="board_meta_backfill_failed", channel=channel, error=str(exc)[:200])
            continue
        for row in rows[:_THREADS]:
            inserted += _conversation(table, writer, row, channel=channel, own=own, follow=follow)
    writer.flush()
    board_meta_ingest.follow_up(list(follow.values()))
    return {"inserted": inserted}


def _own_ids(page: str) -> set[str]:
    ids = {page, board_meta.ig_user_id()}
    try:
        ids.add(board_meta_token.linked_ig_user_id())
    except Exception as exc:
        _log_event("info", tag="board_meta_backfill_ig_id_unknown", error=str(exc)[:200])
    return {value for value in ids if value}


def _conversation(table: Any, writer: board_meta_store.Writer, row: dict[str, Any], *, channel: str, own: set[str], follow: dict[str, dict[str, str]]) -> int:
    customer = _customer(row, own)
    if not customer:
        # Without the other party the messages cannot be filed in the thread the webhook uses.
        return 0
    thread_id = board_meta.thread_id_for(channel, customer["id"])
    known = board_meta_store.known_message_ids(table, thread_id)
    messages = ((row.get("messages") or {}).get("data") or []) if isinstance(row.get("messages"), dict) else []
    inserted = 0
    for raw in messages:
        if not isinstance(raw, dict) or not raw.get("id") or str(raw.get("id")) in known:
            continue
        sender = str(((raw.get("from") or {}) if isinstance(raw.get("from"), dict) else {}).get("id") or "")
        outbound = sender in own or (bool(sender) and sender != customer["id"])
        msg: dict[str, Any] = {
            "_threadId": thread_id,
            "channel": channel,
            "threadKey": customer["id"],
            "senderId": customer["id"],
            "messageId": str(raw.get("id")),
            "text": str(raw.get("message") or ""),
            "timestampMs": str(raw.get("created_time") or ""),
            "direction": "out" if outbound else "in",
            "source": "backfill",
            "senderName": "" if outbound else customer["name"],
            "attachments": _attachments(raw.get("attachments")),
        }
        if not writer.add(msg):
            continue
        inserted += 1
        if msg.get("_live") or msg["attachments"]:
            follow[f"{thread_id}:{msg['messageId']}"] = {"threadId": thread_id, "messageId": msg["messageId"], "mode": "live" if msg.get("_live") else "link"}
    writer.set_name(thread_id, customer["name"])
    return inserted


def _customer(row: dict[str, Any], own: set[str]) -> dict[str, str] | None:
    people = ((row.get("participants") or {}).get("data") or []) if isinstance(row.get("participants"), dict) else []
    for person in people:
        if isinstance(person, dict) and person.get("id") and str(person["id"]) not in own:
            return {"id": str(person["id"]), "name": str(person.get("name") or person.get("username") or "")}
    return None


def _attachments(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in ((raw or {}).get("data") or []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        image = _g if isinstance(_g := item.get("image_data"), dict) else {}
        video = _g if isinstance(_g := item.get("video_data"), dict) else {}
        url = str(image.get("url") or video.get("url") or item.get("file_url") or "")
        if not url:
            continue
        kind = "image" if image else ("video" if video else "file")
        out.append({"kind": kind, "url": url, "mime": str(item.get("mime_type") or ""), "name": str(item.get("name") or "")})
        if len(out) >= _MEDIA_MAX:
            break
    return out
