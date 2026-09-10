"""WP4 lessons — veto / correction / return → confirmed prompt rules."""

from __future__ import annotations

import json
from typing import Any

import board_budget
import board_store
from http_common import _log_event

_FALLBACK = "Do not repeat this action the same way without extra founder review."


def _desk_instruction(
    table: Any,
    settings: dict[str, Any],
    *,
    kind: str,
    what: str,
    note: str,
    preview: str,
) -> str:
    try:
        completion = board_budget.board_completion(
            table=table,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Draft one imperative standing instruction (≤200 characters) "
                        "the staff should follow next time. JSON only: "
                        '{"instruction":"…"}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"kind": kind, "what": what, "note": note, "preview": preview},
                        ensure_ascii=False,
                    )[:4000],
                },
            ],
            model=board_budget.model_for("standup", settings),
            timeout=12,
            json_mode=True,
            temperature=0,
            max_tokens=120,
            tag="board_lesson_draft",
        )
        parsed = json.loads(completion.text or "{}")
        text = str(parsed.get("instruction") or "").strip()
        if text:
            return text[:200]
    except Exception as exc:
        _log_event("warning", tag="board_lesson_draft_failed", error=str(exc)[:200])
    if note.strip():
        return note.strip()[:200]
    return _FALLBACK[:200]


def _write(
    table: Any,
    *,
    kind: str,
    subject: str,
    class_key: str,
    what: str,
    instruction: str,
    source_ref: str,
) -> dict[str, Any]:
    now = board_store.now_iso()
    doc = {
        "lessonId": board_store.new_id(),
        "kind": kind,
        "subject": subject,
        "classKey": class_key,
        "what": what[:400],
        "instruction": instruction[:200],
        "confirmed": False,
        "sourceRef": source_ref,
        "createdAt": now,
    }
    board_store.put_lesson(table, doc)
    return doc


def create_from_veto(table: Any, hold: dict[str, Any]) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    what = str(hold.get("summary") or hold.get("op") or "held action")
    preview = json.dumps(hold.get("preview") or hold.get("arguments") or {}, default=str)[:1500]
    instruction = _desk_instruction(
        table,
        settings,
        kind="veto",
        what=what,
        note=str(hold.get("vetoReason") or ""),
        preview=preview,
    )
    return _write(
        table,
        kind="veto",
        subject=str(hold.get("seatId") or hold.get("personaId") or ""),
        class_key=str(hold.get("classKey") or hold.get("actionClass") or ""),
        what=what,
        instruction=instruction,
        source_ref=str(hold.get("holdId") or ""),
    )


def create_from_correction(table: Any, call_id: str, note: str) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    call = board_store.get_tool_call(table, call_id) or {"callId": call_id}
    what = str(call.get("summary") or call.get("op") or call_id)
    preview = str(call.get("resultPreview") or "")[:1500]
    instruction = _desk_instruction(
        table,
        settings,
        kind="correction",
        what=what,
        note=note,
        preview=preview,
    )
    return _write(
        table,
        kind="correction",
        subject=str(call.get("seatId") or call.get("personaId") or ""),
        class_key=str(call.get("classKey") or call.get("toolId") or ""),
        what=what,
        instruction=instruction,
        source_ref=str(call_id),
    )


def create_from_return(table: Any, task: dict[str, Any]) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    notes = str((task.get("lastReview") or {}).get("notes") or "")
    what = str(task.get("summary") or task.get("brief") or task.get("taskId") or "returned task")
    instruction = _desk_instruction(
        table,
        settings,
        kind="return",
        what=what,
        note=notes,
        preview=str(task.get("brief") or "")[:1500],
    )
    return _write(
        table,
        kind="return",
        subject=str(task.get("assignee") or ""),
        class_key="internal",
        what=what,
        instruction=instruction,
        source_ref=str(task.get("taskId") or ""),
    )


def confirm(table: Any, lesson_id: str, instruction: str | None = None) -> dict[str, Any]:
    existing = board_store.get_lesson(table, lesson_id)
    if not existing:
        raise KeyError(lesson_id)
    if instruction is not None:
        text = str(instruction).strip()
        if text:
            existing["instruction"] = text[:200]
    existing["confirmed"] = True
    existing["confirmedAt"] = board_store.now_iso()
    board_store.put_lesson(table, existing)
    return existing


def dismiss(table: Any, lesson_id: str) -> dict[str, Any]:
    existing = board_store.get_lesson(table, lesson_id)
    if not existing:
        raise KeyError(lesson_id)
    existing["confirmed"] = False
    existing["dismissed"] = True
    existing["dismissedAt"] = board_store.now_iso()
    board_store.put_lesson(table, existing)
    return existing


def list_lessons(table: Any, subject: str | None = None, *, limit: int = 80) -> list[dict[str, Any]]:
    return board_store.list_lessons(table, subject, limit=limit)
