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


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _shrink_json(value: Any, budget: int, depth: int = 0) -> Any:
    """Drop whole keys and items so the pretty form stays within ``budget``."""
    if depth > 8:
        return "…"
    if len(_pretty_json(value)) <= budget:
        return value
    if isinstance(value, dict):
        kept: dict[str, Any] = {}
        for key, item in value.items():
            trial = {**kept, key: item}
            if len(_pretty_json(trial)) <= budget:
                kept[key] = item
                continue
            if isinstance(item, (dict, list, str)):
                shrunk = _shrink_json(item, max(20, budget - len(_pretty_json(kept)) - len(str(key)) - 8), depth + 1)
                trial = {**kept, key: shrunk}
                if shrunk != item and len(_pretty_json(trial)) <= budget:
                    kept[key] = shrunk
            break
        return kept
    if isinstance(value, list):
        kept_items: list[Any] = []
        for item in value:
            trial_list = [*kept_items, item]
            if len(_pretty_json(trial_list)) <= budget:
                kept_items.append(item)
                continue
            if isinstance(item, (dict, list, str)):
                shrunk = _shrink_json(item, max(20, budget // 2), depth + 1)
                trial_list = [*kept_items, shrunk]
                if shrunk != item and len(_pretty_json(trial_list)) <= budget:
                    kept_items.append(shrunk)
            break
        return kept_items
    if isinstance(value, str):
        lo, hi, best = 0, len(value), ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid] + "…"
            if len(json.dumps(candidate, ensure_ascii=False)) <= budget:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return best
    return value


def _bounded_pretty(value: Any, limit: int) -> str:
    """Pretty JSON that still parses, with a truncation line when the body was shortened."""
    full = _pretty_json(value)
    if len(full) <= limit:
        return full
    note = f"\n… [truncated, {len(full)} chars]"
    budget = max(20, limit - len(note))
    body = _pretty_json(_shrink_json(value, budget))
    for _ in range(6):
        if len(body) + len(note) <= limit:
            break
        budget = max(20, int(budget * 0.7))
        body = _pretty_json(_shrink_json(value, budget))
    return body + note


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    note = f"\n… [truncated, {len(text)} chars]"
    cut = text[: max(0, limit - len(note))]
    newline = cut.rfind("\n")
    if newline >= len(cut) // 2:
        cut = cut[:newline]
    return cut.rstrip() + note


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
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        if dtype not in ("json", "messages"):
            return ""
        return _clip_text(text, DELIVERABLE_PREVIEW_LIMIT)
    return _bounded_pretty(parsed, DELIVERABLE_PREVIEW_LIMIT)


def _stored_call(table: Any, created_at: str, call_id: str) -> dict[str, Any] | None:
    """One audit row. The sort key is known, so this does not scan the newest calls."""
    if not created_at or not call_id:
        return None
    try:
        res = table.get_item(Key={"pk": board_store.board_pk("toolcalls"), "sk": f"CALL#{created_at}#{call_id}"})
    except Exception:
        return None
    item = res.get("Item") if isinstance(res, dict) else None
    if not isinstance(item, dict):
        return None
    doc = board_store._from_ddb_nested(board_store._strip_keys(item))
    return doc if isinstance(doc, dict) else None


def enrich_stored_sample(table: Any, review: dict[str, Any]) -> dict[str, Any]:
    """Fill JSON previews on the rows already stored. Membership and order stay put."""
    if not isinstance(review, dict):
        return review
    sample = review.get("sample")
    if not isinstance(sample, list) or not sample:
        return review
    rows: list[Any] = []
    changed = False
    for row in sample:
        if not isinstance(row, dict) or str(row.get("op") or "") != "task_finish":
            rows.append(row)
            continue
        call = _stored_call(table, str(row.get("createdAt") or ""), str(row.get("callId") or ""))
        preview = _deliverable_preview(call) if call else ""
        if not preview or preview == str(row.get("deliverablePreview") or ""):
            rows.append(row)
            continue
        rows.append({**row, "deliverablePreview": preview})
        changed = True
    if not changed:
        return review
    return {**review, "sample": rows}


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
