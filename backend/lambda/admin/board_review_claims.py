"""A deliverable that claims a completed send, publish, or qualification needs a successful call."""

from __future__ import annotations

import re
from typing import Any

import board_store

_SENT_RE = re.compile(r"\b(sent|emailed)\b", re.I)
_PUBLISHED_RE = re.compile(
    r"\bpublished\b(?!\s+(?:contact|email|e-mail|phone|page|listing|address|url)\b)",
    re.I,
)
_QUALIFIED_RE = re.compile(r"\bqualified\b", re.I)
_SKIP_BEFORE = re.compile(
    r"\b(not|never|without|cannot|can't|won't|will|to|would|should|can|could|please|be)\s+$",
    re.I,
)
_SENT_OPS = frozenset({"mail_send", "mail_reply", "outreach_send"})
_PUBLISH_OPS = frozenset({"content_publish"})
_QUALIFY_OPS = frozenset({"outreach_score_prospect"})
_FLAG = "claimed_action_unverified"


def mismatch(table: Any, task: dict[str, Any], deliverable: str) -> str:
    """Empty when the claim is backed by a successful call, or there is no such claim.

    Only a past-tense claim counts. ``will be published``, ``not sent`` and
    ``published contact`` are not claims that the seat already did the work.
    """
    text = f"{task.get('summary') or ''}\n{deliverable or ''}"
    missing: list[str] = []
    if _asserted(_SENT_RE, text) and not _succeeded(table, str(task.get("taskId") or ""), _SENT_OPS):
        missing.append("a send (mail_send, mail_reply, or outreach_send)")
    if _asserted(_PUBLISHED_RE, text) and not _succeeded(table, str(task.get("taskId") or ""), _PUBLISH_OPS):
        missing.append("content_publish")
    if _asserted(_QUALIFIED_RE, text) and not _succeeded(table, str(task.get("taskId") or ""), _QUALIFY_OPS):
        missing.append("outreach_score_prospect")
    if not missing:
        return ""
    return (
        "CLAIM MISMATCH: the deliverable or summary claims "
        + " and ".join(missing)
        + ", but this task has no successful call of that op. Return."
    )


def sync_flag(task: dict[str, Any], claimed: bool) -> bool:
    """Add or clear the flag. Return True when the task row should be saved."""
    flags = [str(flag) for flag in (task.get("flags") or [])]
    has = _FLAG in flags
    if claimed and not has:
        task["flags"] = [*flags, _FLAG]
        return True
    if not claimed and has:
        task["flags"] = [flag for flag in flags if flag != _FLAG]
        return True
    return False


def _asserted(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        window = text[max(0, match.start() - 40) : match.start()]
        if _SKIP_BEFORE.search(window):
            continue
        return True
    return False


def _succeeded(table: Any, task_id: str, ops: frozenset[str]) -> bool:
    if not task_id:
        return False
    for call in board_store.list_tool_calls_for_task(table, task_id):
        if str(call.get("op") or "") in ops and str(call.get("status") or "") == "ok":
            return True
    return False
