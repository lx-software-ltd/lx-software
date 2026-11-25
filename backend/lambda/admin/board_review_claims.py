"""A deliverable that claims a send, publish, or qualification needs a successful call."""

from __future__ import annotations

import re
from typing import Any

import board_store

_SENT_RE = re.compile(r"\b(send|sent)\b", re.I)
_PUBLISHED_RE = re.compile(r"\b(publish|published)\b", re.I)
_QUALIFIED_RE = re.compile(r"\bqualified\b", re.I)
_SENT_OPS = frozenset({"mail_send", "mail_reply", "outreach_send"})
_PUBLISH_OPS = frozenset({"content_publish"})
_QUALIFY_OPS = frozenset({"outreach_score_prospect"})


def mismatch(table: Any, task: dict[str, Any], deliverable: str) -> str:
    """Empty when the claim is backed by a successful call, or there is no such claim."""
    from board_staff import _CLAIMED_ACTION_RE

    text = f"{task.get('summary') or ''}\n{deliverable or ''}"
    claimed = bool(_CLAIMED_ACTION_RE.search(text) or _QUALIFIED_RE.search(text))
    if not claimed:
        return ""
    task_id = str(task.get("taskId") or "")
    missing: list[str] = []
    if _SENT_RE.search(text) and not _succeeded(table, task_id, _SENT_OPS):
        missing.append("a send (mail_send, mail_reply, or outreach_send)")
    if _PUBLISHED_RE.search(text) and not _succeeded(table, task_id, _PUBLISH_OPS):
        missing.append("content_publish")
    if _QUALIFIED_RE.search(text) and not _succeeded(table, task_id, _QUALIFY_OPS):
        missing.append("outreach_score_prospect")
    if not missing:
        return ""
    return (
        "CLAIM MISMATCH: the deliverable or summary claims "
        + " and ".join(missing)
        + ", but this task has no successful call of that op. Return."
    )


def _succeeded(table: Any, task_id: str, ops: frozenset[str]) -> bool:
    if not task_id:
        return False
    for call in board_store.list_tool_calls_for_task(table, task_id):
        if str(call.get("op") or "") in ops and str(call.get("status") or "") == "ok":
            return True
    return False
