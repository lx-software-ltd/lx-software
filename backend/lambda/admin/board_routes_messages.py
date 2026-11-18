"""Owner routes for the Messages tab. Staff tools stay masked; this session sees the text."""

from __future__ import annotations

from typing import Any

import board_meta
import board_meta_attachments
import board_meta_inbox
import board_meta_whatsapp
import board_store
from http_common import _json_response, _parse_json_body, method_not_allowed, not_found


def handle(event: dict[str, Any], method: str, rest: list[str], user_sub: str | None) -> dict[str, Any]:
    del user_sub
    table = board_store.records_table()
    if rest == ["messages"] and method == "GET":
        params = event.get("queryStringParameters") or {}
        channel = str(params.get("channel") or "all")
        unread = str(params.get("unread") or "") in ("1", "true")
        return _json_response(200, board_meta_inbox.list_for_owner(table, channel=channel, unread_only=unread))
    if rest == ["messages", "status"] and method == "GET":
        return _json_response(200, board_meta_inbox.status(table))
    if rest == ["messages", "connect", "page"] and method == "POST":
        return _connect_page()
    if rest == ["messages", "whatsapp", "connect"] and method == "POST":
        return _connect_whatsapp(event, table)
    if rest == ["messages", "whatsapp", "sync"] and method == "POST":
        return _sync(table)
    if len(rest) == 2 and method == "GET":
        detail = board_meta_inbox.thread_for_owner(table, rest[1])
        return _json_response(200, detail) if detail else not_found()
    if len(rest) == 3 and rest[2] == "read" and method == "POST":
        thread = board_meta_inbox.mark_read(table, rest[1])
        return _json_response(200, {"thread": thread}) if thread else not_found()
    if len(rest) == 4 and rest[2] == "media" and method == "GET":
        return _media(table, rest[1], rest[3])
    return method_not_allowed()


def _connect_page() -> dict[str, Any]:
    page = board_meta.page_id()
    if not page:
        return _json_response(400, {"message": "META_PAGE_ID is not set"})
    fields = "messages,message_echoes,messaging_postbacks,message_reactions,feed"
    try:
        result = board_meta.graph("POST", f"{page}/subscribed_apps", params={"subscribed_fields": fields})
    except board_meta.MetaError as exc:
        return _json_response(exc.status or 502, {"message": str(exc)})
    return _json_response(200, {"ok": True, "fields": fields.split(","), "result": result})


def _connect_whatsapp(event: dict[str, Any], table: Any) -> dict[str, Any]:
    try:
        body = _parse_json_body(event)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    if not isinstance(body, dict):
        return _json_response(400, {"message": "Body must be a JSON object"})
    try:
        return _json_response(200, board_meta_whatsapp.connect(table, body))
    except board_meta.MetaError as exc:
        return _json_response(exc.status or 400, {"message": str(exc)})


def _sync(table: Any) -> dict[str, Any]:
    try:
        return _json_response(200, board_meta_whatsapp.sync_history(table))
    except board_meta.MetaError as exc:
        return _json_response(exc.status or 400, {"message": str(exc)})


def _media(table: Any, thread_id: str, ref: str) -> dict[str, Any]:
    found = board_meta_inbox.find_media(table, thread_id, ref)
    if not found:
        return not_found()
    message, index = found
    if not message["attachments"][index].get("key"):
        # History media is not copied on import. It is fetched the first time the owner opens it.
        board_meta_attachments.fetch_pending(table, message)
    item = message["attachments"][index]
    url = board_meta_attachments.presign(item)
    if not url:
        return _json_response(404, {"message": "This file is no longer available from Meta."})
    return _json_response(200, {"url": url, "kind": item.get("kind") or "file", "mime": item.get("mime") or "", "name": item.get("name") or ""})
