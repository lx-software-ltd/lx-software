"""Write a Meta message once and keep each thread summary moving forward only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_meta
import board_pii
import board_store
from botocore.exceptions import ClientError
from contract_constants import BOARD_TOOLS_CONTRACT
from http_common import _log_event, _utc_iso_z

_TEXT_MAX = int(BOARD_TOOLS_CONTRACT["limits"]["metaMessageTextMax"])
_LIVE_HOURS = 24
_NAMES = "meta#names"


def received_at(raw: Any, fallback: str) -> str:
    """One stored format for epoch seconds, epoch milliseconds and Graph's ISO strings."""
    text = str(raw or "").strip()
    if text.isdigit():
        stamp = int(text)
        if stamp > 10_000_000_000:
            return _utc_iso_z(datetime.fromtimestamp(stamp / 1000, timezone.utc))
        if stamp > 1_000_000_000:
            return _utc_iso_z(datetime.fromtimestamp(stamp, timezone.utc))
        return fallback
    if not text:
        return fallback
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _utc_iso_z(parsed)


def claim(table: Any, suffix: str, sort_key: str, extra: dict[str, Any] | None = None) -> bool:
    """Conditional put. False when another writer already holds the row."""
    item = {"pk": board_store.board_pk(suffix), "sk": sort_key, "expiresAt": board_store._meta_expires_at(), **(extra or {})}
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def known_message_ids(table: Any, thread_id: str) -> set[str]:
    return {str(row.get("messageId") or "") for row in board_store.list_meta_messages(table, thread_id)}


class Writer:
    """Stores messages for one delivery and writes each touched thread once."""

    def __init__(self, table: Any) -> None:
        self.table = table
        self.pseud = board_pii.Pseudonymizer(table)
        self.now = _utc_iso_z(datetime.now(timezone.utc))
        self._threads: dict[str, dict[str, Any]] = {}
        self._dirty: set[str] = set()
        self._names: dict[str, str] = {}

    def thread(self, thread_id: str) -> dict[str, Any]:
        if thread_id not in self._threads:
            self._threads[thread_id] = board_store.get_meta_thread(self.table, thread_id) or {}
        return self._threads[thread_id]

    def add(self, msg: dict[str, Any]) -> bool:
        """Store one message. False when this message id is already on the thread."""
        channel = str(msg.get("channel") or "")
        thread_id = str(msg.get("_threadId") or board_meta.thread_id_for(channel, str(msg.get("threadKey"))))
        msg["_threadId"] = thread_id
        message_id = str(msg.get("messageId") or "")
        received = received_at(msg.get("timestampMs"), self.now)
        text = str(msg.get("text") or "")[:_TEXT_MAX]
        masked = self.pseud.mask_text(text)
        inbound = (msg.get("direction") or "in") == "in"
        row = {
            "threadId": thread_id,
            "messageId": message_id,
            "receivedAt": received,
            "direction": "in" if inbound else "out",
            "text": text,
            "textMasked": masked,
            "channel": channel,
            "senderName": str(msg.get("senderName") or "")[:120] if inbound else "",
            "source": msg.get("source") or "webhook",
            "attachments": msg.get("attachments") or [],
            "replyTo": str(msg.get("replyTo") or ""),
        }
        # The sort key carries the timestamp, and two paths can report different
        # timestamps for one message. The claim row is keyed on the id alone.
        marker = f"MID#{message_id}"
        stored = claim(self.table, f"meta#thread#{thread_id}", marker)
        if stored:
            try:
                stored = board_store.put_meta_message_if_new(self.table, row)
            except Exception:
                self.table.delete_item(Key={"pk": board_store.board_pk(f"meta#thread#{thread_id}"), "sk": marker})
                raise
        if not stored:
            _log_event("info", tag="board_meta_duplicate_delivery", threadId=thread_id, messageId=message_id)
            return False
        live = inbound and _is_live(str(row["source"]), received)
        msg["_live"] = live
        self._advance(thread_id, msg, row, masked, live=live)
        return True

    def _advance(self, thread_id: str, msg: dict[str, Any], row: dict[str, Any], masked: str, *, live: bool) -> None:
        thread = self.thread(thread_id)
        channel = str(row["channel"])
        inbound = row["direction"] == "in"
        received = str(row["receivedAt"])
        phone = str(msg.get("phone") or thread.get("phone") or "")
        # The owner's contact-book name wins over the profile name the sender chose.
        name = str(thread.get("displayName") or "")
        if not name and channel == "whatsapp" and phone:
            name = self._contact_name(phone)
        name = name or str(row["senderName"] or "")
        thread.update(
            {
                "threadId": thread_id,
                "channel": channel,
                "kind": msg.get("kind") or thread.get("kind") or "message",
                "senderId": msg.get("senderId") or thread.get("senderId"),
                "displayName": name[:120],
                "phone": phone,
                "messageCount": int(thread.get("messageCount") or 0) + 1,
                "unread": bool(thread.get("unread")) or live,
                "unreadCount": int(thread.get("unreadCount") or 0) + (1 if live else 0),
            }
        )
        if received >= str(thread.get("lastMessageAt") or ""):
            thread.update({"text": str(row["text"])[:240], "lastTextMasked": masked[:240], "lastMessageAt": received, "lastDirection": row["direction"]})
        side = "lastInboundAt" if inbound else "lastOutboundAt"
        if received > str(thread.get(side) or ""):
            thread[side] = received
        self._dirty.add(thread_id)

    def remember_name(self, phone: str, name: str) -> None:
        """Contact sync arrives before the history, so the name waits for its thread."""
        digits = board_meta._phone_digits(phone)
        name = str(name or "").strip()[:120]
        if not digits or not name:
            return
        self.table.put_item(
            Item={"pk": board_store.board_pk(_NAMES), "sk": f"WA#{digits}", "name": name, "expiresAt": board_store._meta_expires_at()}
        )
        self._names[digits] = name
        self.set_name(board_meta.thread_id_for("whatsapp", digits), name, replace=True)

    def set_name(self, thread_id: str, name: str, *, replace: bool = False) -> None:
        """Name a thread that already exists. A thread is never created from a name alone."""
        thread = self.thread(thread_id)
        if not thread or not name or thread.get("displayName") == name:
            return
        if thread.get("displayName") and not replace:
            return
        thread["displayName"] = name[:120]
        self._dirty.add(thread_id)

    def _contact_name(self, phone: str) -> str:
        digits = board_meta._phone_digits(phone)
        if digits and digits not in self._names:
            res = self.table.get_item(Key={"pk": board_store.board_pk(_NAMES), "sk": f"WA#{digits}"})
            item = res.get("Item") if isinstance(res, dict) else None
            self._names[digits] = str((item or {}).get("name") or "")
        return self._names.get(digits, "")

    def flush(self) -> None:
        for thread_id in sorted(self._dirty):
            board_store.put_meta_thread(self.table, self._threads[thread_id])
        self._dirty.clear()
        self.pseud.save()


def _is_live(source: str, received: str) -> bool:
    """Only a message that just arrived is unread and triaged. Imported history never is."""
    if source == "webhook":
        return True
    if source != "backfill":
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(received.replace("Z", "+00:00"))
    except ValueError:
        return False
    return age <= timedelta(hours=_LIVE_HOURS)
