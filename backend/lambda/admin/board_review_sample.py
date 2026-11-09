"""Daily review "Sample of what ran": hold-0 write calls with task context."""

from __future__ import annotations

import json
import random
from typing import Any

import board_store
from contract_constants import BOARD_STAFF_REVIEW_SAMPLE_SIZE

TEXT_LIMIT = 280
ARGUMENTS_LIMIT = 1200
DIGEST_LINE_LIMIT = 320
DELIVERABLE_PREVIEW_LIMIT = 1600


def _clip(text: Any, limit: int) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1].rstrip() + "…"


def _json_preview(value: Any, limit: int) -> str:
    if value is None or value == {} or value == "":
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 40].rstrip() + f" … [truncated, {len(text)} chars]"


def _deliverable_preview(call: dict[str, Any]) -> str:
    """Pretty JSON body from a task_finish call. The result key is not the preview."""
    if str(call.get("op") or "") != "task_finish":
        return ""
    args = call.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return ""
    if not isinstance(args, dict):
        return ""
    body = args.get("deliverable")
    if not isinstance(body, str) or not body.strip():
        return ""
    dtype = str(args.get("deliverableType") or "")
    text = body.strip()
    looks_json = dtype in ("json", "messages") or text[:1] in "{["
    if not looks_json:
        return ""
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError, ValueError):
        if dtype not in ("json", "messages"):
            return ""
    return _json_preview(text, DELIVERABLE_PREVIEW_LIMIT)


def overlay(table: Any, review: dict[str, Any]) -> dict[str, Any]:
    """Fresh sample for today's on-screen review. The stored snapshot is not written."""
    if not isinstance(review, dict):
        return review
    date_hkt = str(review.get("date") or "")
    if not date_hkt:
        return review
    try:
        import board_review

        sample = board_review._sample(table, board_store.load_settings(table), date_hkt)
    except Exception:
        return review
    return {**review, "sample": sample}


def _task_context(table: Any, cache: dict[str, dict[str, Any] | None], task_id: str) -> dict[str, Any] | None:
    if not task_id:
        return None
    if task_id in cache:
        return cache[task_id]
    try:
        task = board_store.get_task(table, task_id)
    except Exception:
        task = None
    context = None
    if isinstance(task, dict):
        context = {
            "taskId": task_id,
            "assignee": str(task.get("assignee") or ""),
            "status": str(task.get("status") or ""),
            "brief": _clip(task.get("brief"), TEXT_LIMIT),
            "summary": _clip(task.get("summary"), TEXT_LIMIT),
        }
    cache[task_id] = context
    return context


def row_from_call(
    table: Any,
    call: dict[str, Any],
    class_key: str,
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    task_id = str(call.get("taskId") or "")
    return {
        "callId": call.get("callId"),
        "summary": call.get("summary"),
        "preview": call.get("resultPreview") or call.get("arguments"),
        "op": call.get("op"),
        "classKey": class_key,
        "createdAt": str(call.get("createdAt") or ""),
        "personaId": str(call.get("personaId") or ""),
        "displayName": str(call.get("displayName") or ""),
        "seatId": str(call.get("seatId") or ""),
        "taskId": task_id,
        "arguments": _json_preview(call.get("arguments"), ARGUMENTS_LIMIT),
        "deliverablePreview": _deliverable_preview(call),
        "task": _task_context(table, cache, task_id),
    }


def collect(table: Any, settings: dict[str, Any], date_hkt: str, start: str, end: str) -> list[dict[str, Any]]:
    """Yesterday's hold-0 write calls, seeded-shuffled by date, capped at the review sample size."""
    size = int((settings.get("review") or {}).get("sampleSize") or BOARD_STAFF_REVIEW_SAMPLE_SIZE)
    try:
        import board_holds
        import board_tools
    except Exception:
        return []
    pool: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any] | None] = {}
    for call in board_store.list_tool_calls(table, limit=400):
        created = str(call.get("createdAt") or "")
        if created < start or created >= end:
            continue
        if call.get("status") != "ok":
            continue
        op = board_tools.REGISTRY.get(str(call.get("op") or ""))
        if op is None or not op.is_write:
            continue
        ctx = board_tools.ToolContext(
            table=table,
            settings=settings,
            persona_id=str(call.get("personaId") or ""),
            display_name=str(call.get("displayName") or ""),
            kind="review",
        )
        action_class, class_key = board_holds.classify(op, ctx, dict(call.get("arguments") or {}), settings)
        if board_holds.hold_hours(table, settings, action_class, class_key) > 0:
            continue
        pool.append(row_from_call(table, call, class_key, cache))
    rng = random.Random(date_hkt)
    rng.shuffle(pool)
    return pool[: max(1, size)]


def digest_line(row: dict[str, Any]) -> str:
    head = str(row.get("summary") or row.get("op") or row.get("callId") or "Action")
    actor = str(row.get("displayName") or row.get("personaId") or "")
    if actor:
        head = f"{head} — {actor}"
    task = row.get("task")
    if isinstance(task, dict) and task.get("taskId"):
        short = str(task["taskId"])[:8]
        who = str(task.get("assignee") or "")
        status = str(task.get("status") or "")
        meta = " ".join(p for p in (who, status) if p)
        tail = f"task #{short}" + (f" ({meta})" if meta else "")
        brief = str(task.get("brief") or "")
        if brief:
            tail = f"{tail}: {brief}"
        head = f"{head} · {tail}"
    return _clip(head, DIGEST_LINE_LIMIT)
