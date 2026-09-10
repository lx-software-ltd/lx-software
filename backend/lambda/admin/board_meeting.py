"""Executive Board: meeting engine.

A meeting is a chain of phases, each run in its own async self-invocation of
AdminApiFn so no single invocation approaches the Lambda timeout:

    prepare -> agenda -> positions -> [challenge] -> synthesis -> persist

Each phase claims the meeting row with a conditional update (idempotent
against duplicate deliveries), does its LLM calls, stores the resulting
"turns", advances ``phase`` and invokes the next phase. The SPA polls
``GET /siu-tin-dei/board/meetings/{id}`` and renders the transcript live.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import board_actions
import board_async
import board_budget
import board_context
import board_personas
import board_store
import board_tools
from contract_constants import (
    BOARD_ACTION_EFFORTS,
    BOARD_ACTION_PRIORITIES,
    BOARD_CHAIR_DEFAULT,
    BOARD_MAX_PARALLEL_PERSONA_CALLS,
    BOARD_MAX_TOPIC_LEN,
    BOARD_MEETING_MODES,
    BOARD_MEETING_STUCK_SECONDS,
    BOARD_MEETING_TOOL_LOOP_MAX_SECONDS,
    BOARD_PHASE_OPENROUTER_TIMEOUT_SECONDS,
    BOARD_REPO_SNAPSHOT_STALE_SECONDS,
)
from http_common import _audit, _json_response, _log_event, _parse_json_body, _request_id, _utc_iso_z
from openrouter_client import OpenRouterError, add_usage, parse_json_object_text
from runtime import logger

PHASES_BY_MODE: dict[str, tuple[str, ...]] = {
    "standup": ("prepare", "agenda", "positions", "synthesis", "persist"),
    "deepDive": ("prepare", "agenda", "positions", "challenge", "synthesis", "persist"),
}
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})

MAX_AGENDA_ITEMS = 5
MAX_TEXT = 4000
MAX_LIST = 12

MEETING_ROLE_MEMBER = (
    "You are speaking in a board meeting. Address the agenda from your own mandate; "
    "do not cover other executives' areas except to flag dependencies. Be specific "
    "about what the founder should do, why, and how you would measure it."
)
MEETING_ROLE_CHAIR = (
    "You chair this meeting. You set the agenda, surface disagreements, and write "
    "the minutes with a prioritised list of next actions for the founder. Prefer "
    "fewer, sharper actions over long lists; every action must be something one "
    "person can start this week."
)


class MeetingError(RuntimeError):
    """User-facing meeting failure (recorded on the meeting row)."""


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

def handle_meetings_get() -> dict[str, Any]:
    table = board_store.records_table()
    items = board_store.list_meetings(table, limit=40)
    out = [public_meeting_summary(_finalize_stuck(table, m)) for m in items]
    return _json_response(200, {"meetings": out})


def handle_meeting_get(meeting_id: str) -> dict[str, Any]:
    table = board_store.records_table()
    doc = board_store.get_meeting(table, meeting_id)
    if not doc:
        return _json_response(404, {"message": "Meeting not found"})
    doc = _finalize_stuck(table, doc)
    turns = board_store.list_turns(table, meeting_id)
    return _json_response(200, {"meeting": public_meeting_doc(doc), "turns": turns})


def handle_meeting_post(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    if not user_sub:
        return _json_response(400, {"message": "Missing sub claim"})
    body = _parse_json_body(event)
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    mode = str(body.get("mode") or settings.get("defaultMode") or "standup")
    if mode not in BOARD_MEETING_MODES:
        return _json_response(400, {"message": "mode must be standup or deepDive"})
    chair = str(body.get("chair") or settings.get("defaultChair") or BOARD_CHAIR_DEFAULT)
    if not board_personas.is_persona_id(chair):
        return _json_response(400, {"message": "chair must be a board member id"})
    topic_raw = body.get("topic")
    topic = str(topic_raw).strip()[:BOARD_MAX_TOPIC_LEN] if isinstance(topic_raw, str) else ""
    if mode == "deepDive" and not topic:
        return _json_response(400, {"message": "topic is required for a deep dive"})
    try:
        doc = start_meeting(
            table,
            settings=settings,
            mode=mode,
            chair=chair,
            topic=topic,
            owner_sub=user_sub,
            trigger="manual",
        )
    except board_budget.BudgetExceeded as exc:
        return _json_response(429, {"message": str(exc)})
    except MeetingError as exc:
        return _json_response(409, {"message": str(exc)})
    _audit(user_sub, "BOARD_MEETING_START", doc["meetingId"], event)
    return _json_response(202, {"meetingId": doc["meetingId"], "meeting": public_meeting_summary(doc)})


def handle_meeting_cancel(event: dict[str, Any], meeting_id: str, user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    doc = board_store.get_meeting(table, meeting_id)
    if not doc:
        return _json_response(404, {"message": "Meeting not found"})
    if doc.get("status") in TERMINAL_STATUSES:
        return _json_response(409, {"message": f"Meeting is already {doc.get('status')}"})
    doc = {**doc, "status": "cancelled", "updatedAt": board_store.now_iso()}
    board_store.put_meeting(table, doc)
    _audit(user_sub, "BOARD_MEETING_CANCEL", meeting_id, event)
    return _json_response(200, {"meeting": public_meeting_summary(doc)})


def handle_schedule_trigger(event: dict[str, Any]) -> None:
    """EventBridge entry point: start the scheduled meeting when the slot is enabled."""
    slot = str(event.get("slot") or "morning")
    if not board_store.event_targets_this_board(event):
        _log_event("info", tag="board_schedule_skipped", slot=slot, reason="other_board")
        return
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    enabled = bool((settings.get("schedule") or {}).get(f"{slot}Enabled"))
    if not enabled:
        _log_event("info", tag="board_schedule_skipped", slot=slot, reason="disabled")
        return
    try:
        doc = start_meeting(
            table,
            settings=settings,
            mode=str(settings.get("defaultMode") or "standup") if settings.get("defaultMode") in BOARD_MEETING_MODES else "standup",
            chair=str(settings.get("defaultChair") or BOARD_CHAIR_DEFAULT),
            topic="",
            owner_sub="schedule",
            trigger=f"schedule:{slot}",
        )
    except (board_budget.BudgetExceeded, MeetingError) as exc:
        _log_event("warning", tag="board_schedule_skipped", slot=slot, reason=str(exc)[:200])
        return
    _log_event("info", tag="board_schedule_started", slot=slot, meeting_id=doc["meetingId"])


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def start_meeting(
    table: Any,
    *,
    settings: dict[str, Any],
    mode: str,
    chair: str,
    topic: str,
    owner_sub: str,
    trigger: str,
) -> dict[str, Any]:
    if mode == "deepDive" and not topic:
        mode = "standup"
    for existing in board_store.list_meetings(table, limit=5):
        existing = _finalize_stuck(table, existing)
        if existing.get("status") == "running":
            raise MeetingError("A meeting is already running. Wait for it to finish or cancel it.")
    board_budget.check_budget(table, settings)
    if not board_personas.is_persona_id(chair):
        chair = BOARD_CHAIR_DEFAULT
    created = board_store.now_iso()
    doc: dict[str, Any] = {
        "meetingId": board_store.new_id(),
        "status": "running",
        "mode": mode,
        "chair": chair,
        "topic": topic,
        "trigger": trigger,
        "ownerSub": owner_sub,
        "phase": "prepare",
        "phaseState": "pending",
        "phases": list(PHASES_BY_MODE[mode]),
        "createdAt": created,
        "updatedAt": created,
        "usage": add_usage(None, None),
        "turnCount": 0,
    }
    board_store.put_meeting(table, doc)
    payload = {"internal": "board_meeting", "meetingId": doc["meetingId"], "phase": "prepare"}
    try:
        board_async.invoke_async(payload, fallback=run_meeting_phase)
    except Exception as exc:
        _log_event("error", tag="board_meeting_enqueue_failed", err=str(exc)[:400])
        board_store.put_meeting(
            table,
            {**doc, "status": "failed", "errorMessage": "Could not start the meeting worker"},
        )
        raise MeetingError("Could not start the meeting worker") from exc
    return board_store.get_meeting(table, doc["meetingId"]) or doc


def run_meeting_phase(payload: dict[str, Any]) -> None:
    meeting_id = str(payload.get("meetingId") or "").strip()
    phase = str(payload.get("phase") or "").strip()
    if not meeting_id or not phase:
        _log_event("warning", tag="board_meeting_bad_payload")
        return
    table = board_store.records_table()
    doc = board_store.get_meeting(table, meeting_id)
    if not doc or doc.get("status") != "running":
        _log_event("info", tag="board_meeting_phase_skipped", meeting_id=meeting_id[:32], reason="not_running")
        return
    if doc.get("phase") != phase:
        _log_event("info", tag="board_meeting_phase_skipped", meeting_id=meeting_id[:32], reason="phase_mismatch")
        return
    stale = _utc_iso_z(datetime.now(timezone.utc) - timedelta(seconds=BOARD_MEETING_STUCK_SECONDS))
    if not board_store.claim_meeting_phase(table, meeting_id, expected_phase=phase, stale_before_iso=stale):
        _log_event("info", tag="board_meeting_phase_skipped", meeting_id=meeting_id[:32], reason="claimed")
        return
    doc = board_store.get_meeting(table, meeting_id) or doc
    _log_event("info", tag="board_meeting_phase", meeting_id=meeting_id[:32], phase=phase)

    try:
        doc = PHASE_RUNNERS[phase](table, doc)
    except (OpenRouterError, MeetingError, board_budget.BudgetExceeded) as exc:
        _fail(table, doc, str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("board meeting phase failed")
        _fail(table, doc, f"Meeting phase {phase} failed unexpectedly: {str(exc)[:200]}")
        return

    # Re-check cancellation requested while the phase ran.
    latest = board_store.get_meeting(table, meeting_id)
    if latest and latest.get("status") == "cancelled":
        board_store.put_meeting(table, {**doc, "status": "cancelled", "updatedAt": board_store.now_iso()})
        return

    phases = list(doc.get("phases") or PHASES_BY_MODE.get(str(doc.get("mode")), PHASES_BY_MODE["standup"]))
    idx = phases.index(phase) if phase in phases else -1
    next_phase = phases[idx + 1] if 0 <= idx < len(phases) - 1 else None
    if next_phase is None:
        doc = {**doc, "status": "succeeded", "phase": "done", "phaseState": "done", "updatedAt": board_store.now_iso()}
        board_store.put_meeting(table, doc)
        _log_event("info", tag="board_meeting_succeeded", meeting_id=meeting_id[:32])
        return
    doc = {**doc, "phase": next_phase, "phaseState": "pending", "updatedAt": board_store.now_iso()}
    board_store.put_meeting(table, doc)
    try:
        board_async.invoke_async(
            {"internal": "board_meeting", "meetingId": meeting_id, "phase": next_phase},
            fallback=run_meeting_phase,
        )
    except Exception as exc:
        _fail(table, doc, f"Could not schedule phase {next_phase}: {str(exc)[:200]}")


def _fail(table: Any, doc: dict[str, Any], message: str) -> None:
    _log_event("warning", tag="board_meeting_failed", meeting_id=str(doc.get("meetingId"))[:32], error=message[:300])
    board_store.put_meeting(
        table,
        {**doc, "status": "failed", "errorMessage": message[:800], "updatedAt": board_store.now_iso()},
    )


def _finalize_stuck(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("status") != "running":
        return doc
    updated = _iso_to_dt(doc.get("updatedAt"))
    if updated is None:
        return doc
    if (datetime.now(timezone.utc) - updated).total_seconds() <= BOARD_MEETING_STUCK_SECONDS:
        return doc
    failed = {
        **doc,
        "status": "failed",
        "errorMessage": f"The meeting stalled during the {doc.get('phase')} phase. Start a new one.",
        "updatedAt": board_store.now_iso(),
    }
    board_store.put_meeting(table, failed)
    return failed


def _iso_to_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def _phase_prepare(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    board_context.refresh_repo_snapshot_if_stale(
        table, settings, max_age_seconds=BOARD_REPO_SNAPSHOT_STALE_SECONDS
    )
    charter = board_store.load_charter(table)
    roster = board_personas.effective_roster(board_store.load_member_overrides(table))
    pack = board_context.build_context_pack(table, settings, roster=roster)
    out = {
        **doc,
        "contextPackText": pack["text"],
        "contextPackHash": pack["hash"],
        "contextPackChars": len(pack["text"]),
        "charter": charter,
        "roster": [
            {
                "id": p["id"],
                "displayName": p["displayName"],
                "title": p["title"],
                "shortName": p["shortName"],
                "profileHash": p["profileHash"],
            }
            for p in roster
        ],
        "memberProfileHashes": board_personas.roster_hashes(roster),
        "models": {
            "standup": board_budget.model_for("standup", settings),
            "deepDive": board_budget.model_for("deepDive", settings),
        },
        "updatedAt": board_store.now_iso(),
    }
    board_store.put_meeting(table, out)
    return out


def _meeting_model(doc: dict[str, Any]) -> str:
    models = doc.get("models") or {}
    kind = "deepDive" if doc.get("mode") == "deepDive" else "standup"
    return str(models.get(kind) or board_budget.model_for(kind, board_store.load_settings(board_store.records_table())))


def _profiles(table: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    charter = board_store.load_charter(table)
    roster = board_personas.effective_roster(board_store.load_member_overrides(table))
    return board_personas.roster_by_id(roster), charter


def _call(
    table: Any,
    doc: dict[str, Any],
    *,
    messages: list[dict[str, Any]],
    json_mode: bool,
    max_tokens: int,
    temperature: float = 0.4,
    tag: str,
) -> Any:
    return board_budget.board_completion(
        table=table,
        messages=messages,
        model=_meeting_model(doc),
        timeout=BOARD_PHASE_OPENROUTER_TIMEOUT_SECONDS,
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=1,
        tag=tag,
    )


def _append_turn(table: Any, doc: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    seq = int(doc.get("turnCount") or 0) + 1
    full = {**turn, "seq": seq, "createdAt": board_store.now_iso()}
    board_store.put_turn(table, str(doc["meetingId"]), full)
    usage = add_usage(doc.get("usage"), turn.get("usage"))
    out = {**doc, "turnCount": seq, "usage": usage, "updatedAt": board_store.now_iso()}
    board_store.put_meeting(table, out)
    return out


def _member_call(
    table: Any,
    doc: dict[str, Any],
    *,
    profile: dict[str, Any],
    phase: str,
    messages: list[dict[str, Any]],
    json_mode: bool,
    max_tokens: int,
    temperature: float = 0.4,
    tag: str,
) -> board_tools.ToolLoopResult:
    """One member statement, with that member's tools available."""
    ctx = board_tools.ToolContext(
        table=table,
        settings=board_store.load_settings(table),
        persona_id=str(profile["id"]),
        display_name=str(profile.get("displayName") or profile.get("shortName") or profile["id"]),
        kind="meeting",
        meeting_id=str(doc["meetingId"]),
        phase=phase,
    )
    return board_tools.run_tool_loop(
        ctx=ctx,
        messages=messages,
        model=_meeting_model(doc),
        timeout=BOARD_PHASE_OPENROUTER_TIMEOUT_SECONDS,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=json_mode,
        tag=tag,
        max_seconds=BOARD_MEETING_TOOL_LOOP_MAX_SECONDS,
    )


def _tool_turn(profile: dict[str, Any], phase: str, calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Transcript entry listing what a member looked up or proposed before speaking."""
    if not calls:
        return None
    lines = []
    for c in calls:
        marker = {"ok": "✓", "pending_approval": "⧗ proposed", "error": "✗"}.get(str(c.get("status")), "•")
        lines.append(f"- {marker} {c.get('summary')}" + (f" — {c['error']}" if c.get("error") else ""))
    return {
        "phase": phase,
        "kind": "tool",
        "personaId": profile["id"],
        "displayName": profile["displayName"],
        "title": profile["title"],
        "text": "\n".join(lines),
        "data": {"calls": calls},
    }


def _phase_agenda(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    profiles, charter = _profiles(table)
    chair_id = str(doc.get("chair") or BOARD_CHAIR_DEFAULT)
    chair = profiles[chair_id]
    mode = str(doc.get("mode") or "standup")
    topic = str(doc.get("topic") or "").strip()
    count = "3" if mode == "standup" else "3 to 5"
    instructions = [
        f"Draft the agenda for today's {'daily stand-up' if mode == 'standup' else 'deep-dive'} board meeting.",
        f"Produce {count} agenda items. Each item is a decision or question the board must answer today, "
        "grounded in the context data (brief, founder updates, open actions, previous minutes).",
    ]
    if topic:
        instructions.append(
            f"The founder requested this topic; make it agenda item 1 and keep the rest supporting it: \"{topic}\"."
        )
    instructions.append(
        "Return strict JSON only: {\"items\": [{\"title\": \"<= 90 chars\", \"question\": \"the exact question to answer\", "
        "\"whyNow\": \"one sentence\"}]}. No markdown, no prose."
    )
    messages = [
        {"role": "system", "content": board_personas.render_system_prompt(chair, charter, meeting_role=MEETING_ROLE_CHAIR)},
        {"role": "system", "content": str(doc.get("contextPackText") or "")},
        {"role": "user", "content": "\n".join(instructions)},
    ]
    completion = _call(table, doc, messages=messages, json_mode=True, max_tokens=900, temperature=0.3, tag="board_meeting_agenda")
    raw = parse_json_object_text(completion.text)
    items = normalize_agenda(raw.get("items"), topic=topic)
    if not items:
        raise MeetingError("The chair did not produce a usable agenda")
    text_lines = ["**Agenda**"]
    for i, item in enumerate(items, start=1):
        text_lines.append(f"{i}. **{item['title']}** — {item['question']}")
        if item.get("whyNow"):
            text_lines.append(f"   _Why now:_ {item['whyNow']}")
    out = {**doc, "agenda": items}
    return _append_turn(
        table,
        out,
        {
            "phase": "agenda",
            "personaId": chair_id,
            "displayName": chair["displayName"],
            "title": chair["title"],
            "text": "\n".join(text_lines),
            "data": {"items": items},
            "usage": completion.usage,
            "model": completion.model,
        },
    )


def normalize_agenda(raw_items: Any, *, topic: str = "") -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if isinstance(raw_items, list):
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            title = _clean(it.get("title"), 120)
            question = _clean(it.get("question"), 400)
            if not title and not question:
                continue
            items.append(
                {
                    "title": title or question[:90],
                    "question": question or title,
                    "whyNow": _clean(it.get("whyNow"), 300),
                }
            )
            if len(items) >= MAX_AGENDA_ITEMS:
                break
    if topic and items and topic.lower()[:30] not in (items[0]["title"] + items[0]["question"]).lower():
        items.insert(0, {"title": topic[:120], "question": topic, "whyNow": "Requested by the founder."})
        items = items[:MAX_AGENDA_ITEMS]
    return items


def _agenda_text(doc: dict[str, Any]) -> str:
    lines = []
    for i, item in enumerate(doc.get("agenda") or [], start=1):
        lines.append(f"{i}. {item.get('title')}: {item.get('question')}")
    return "\n".join(lines)


def _phase_positions(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    profiles, charter = _profiles(table)
    agenda_text = _agenda_text(doc)
    pack_text = str(doc.get("contextPackText") or "")

    def _one(persona_id: str) -> list[dict[str, Any]]:
        profile = profiles[persona_id]
        prompt = (
            "Today's agenda:\n"
            f"{agenda_text}\n\n"
            "For EACH agenda item, give your position from your mandate. Return strict JSON only:\n"
            "{\"items\": [{\"agendaIndex\": 1, \"position\": \"<= 120 words, first person\", "
            "\"risks\": [\"<= 3 short items\"], \"proposedActions\": [{\"title\": \"imperative, <= 100 chars\", "
            "\"detail\": \"what done looks like, <= 60 words\", \"priority\": \"now|next|later\", "
            "\"effort\": \"S|M|L\", \"dueInDays\": 7, \"metric\": \"how we know it worked\"}]}]}\n"
            "At most 2 proposed actions per agenda item. If an open action already covers it, say so in the "
            "position and do not propose a duplicate. No markdown, no prose outside the JSON."
        )
        messages = [
            {"role": "system", "content": board_personas.render_system_prompt(profile, charter, meeting_role=MEETING_ROLE_MEMBER)},
            {"role": "system", "content": pack_text},
            {"role": "user", "content": prompt},
        ]
        result = _member_call(
            table, doc, profile=profile, phase="positions", messages=messages, json_mode=True, max_tokens=1400, tag="board_meeting_position"
        )
        try:
            data = normalize_positions(parse_json_object_text(result.text), agenda_len=len(doc.get("agenda") or []))
        except OpenRouterError:
            data = {"items": [{"agendaIndex": 1, "position": _clean(result.text, MAX_TEXT), "risks": [], "proposedActions": []}]}
        turns: list[dict[str, Any]] = []
        tool_turn = _tool_turn(profile, "positions", result.calls)
        if tool_turn:
            turns.append(tool_turn)
        turns.append(
            {
                "phase": "positions",
                "personaId": persona_id,
                "displayName": profile["displayName"],
                "title": profile["title"],
                "text": render_position_text(data, doc.get("agenda") or []),
                "data": data,
                "usage": result.usage,
                "model": result.model,
            }
        )
        return turns

    order = [str(p["id"]) for p in doc.get("roster") or []] or list(profiles)
    with ThreadPoolExecutor(max_workers=max(1, BOARD_MAX_PARALLEL_PERSONA_CALLS)) as pool:
        results = list(pool.map(_one, order))
    out = doc
    for turns in results:
        for turn in turns:
            out = _append_turn(table, out, turn)
    return out


def normalize_positions(raw: dict[str, Any], *, agenda_len: int) -> dict[str, Any]:
    items_out: list[dict[str, Any]] = []
    raw_items = raw.get("items")
    if isinstance(raw_items, list):
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            idx = it.get("agendaIndex")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                idx_int = len(items_out) + 1
            idx_int = min(max(1, idx_int), max(1, agenda_len))
            actions = []
            for a in (it.get("proposedActions") or [])[:2] if isinstance(it.get("proposedActions"), list) else []:
                norm = normalize_action_proposal(a)
                if norm:
                    actions.append(norm)
            items_out.append(
                {
                    "agendaIndex": idx_int,
                    "position": _clean(it.get("position"), 1500),
                    "risks": [_clean(r, 200) for r in (it.get("risks") or []) if _clean(r, 200)][:3]
                    if isinstance(it.get("risks"), list)
                    else [],
                    "proposedActions": actions,
                }
            )
            if len(items_out) >= MAX_AGENDA_ITEMS:
                break
    return {"items": items_out}


def normalize_action_proposal(raw: Any, *, persona: str | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = _clean(raw.get("title"), 120)
    if not title:
        return None
    priority = str(raw.get("priority") or "next").strip().lower()
    if priority not in BOARD_ACTION_PRIORITIES:
        priority = "next"
    effort = str(raw.get("effort") or "M").strip().upper()[:1]
    if effort not in BOARD_ACTION_EFFORTS:
        effort = "M"
    due_raw = raw.get("dueInDays")
    try:
        due = int(due_raw) if due_raw is not None else None
    except (TypeError, ValueError):
        due = None
    if due is not None:
        due = min(max(1, due), 180)
    out: dict[str, Any] = {
        "title": title,
        "detail": _clean(raw.get("detail"), 800),
        "priority": priority,
        "effort": effort,
        "dueInDays": due,
        "metric": _clean(raw.get("metric"), 300),
    }
    persona_raw = raw.get("persona") or persona
    if isinstance(persona_raw, str) and board_personas.is_persona_id(persona_raw.strip().lower()):
        out["persona"] = persona_raw.strip().lower()
    depends = raw.get("dependsOn")
    if isinstance(depends, list):
        out["dependsOn"] = [_clean(d, 120) for d in depends if _clean(d, 120)][:5]
    existing = raw.get("existingActionId")
    if isinstance(existing, str) and re.fullmatch(r"[0-9a-f]{32}", existing.strip()):
        out["existingActionId"] = existing.strip()
    assignee_raw = raw.get("assignee")
    if isinstance(assignee_raw, str):
        assignee = assignee_raw.strip().lower()
        if board_personas.is_persona_id(assignee):
            out["assignee"] = assignee
        else:
            try:
                import board_staff

                table = board_store.records_table()
                settings = board_store.load_settings(table)
                roster = board_staff.seats_by_id(table, settings)
                seat = roster.get(assignee)
                if seat and seat.get("isActive"):
                    out["assignee"] = assignee
            except Exception:
                pass
    return out


def render_position_text(data: dict[str, Any], agenda: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in data.get("items") or []:
        idx = int(item.get("agendaIndex") or 1)
        title = agenda[idx - 1]["title"] if 0 < idx <= len(agenda) else f"Item {idx}"
        lines.append(f"**{idx}. {title}**")
        if item.get("position"):
            lines.append(str(item["position"]))
        if item.get("risks"):
            lines.append("Risks: " + "; ".join(str(r) for r in item["risks"]))
        for a in item.get("proposedActions") or []:
            due = f", due in {a['dueInDays']} days" if a.get("dueInDays") else ""
            lines.append(f"- Proposed [{a['priority']}/{a['effort']}{due}]: {a['title']}")
        lines.append("")
    return "\n".join(lines).strip()


def _turns_text(table: Any, doc: dict[str, Any], *, phases: tuple[str, ...]) -> str:
    turns = board_store.list_turns(table, str(doc["meetingId"]))
    parts = []
    for t in turns:
        if t.get("phase") not in phases or t.get("kind") == "tool":
            continue
        parts.append(f"### {t.get('displayName')} ({t.get('title')}) — {t.get('phase')}\n{t.get('text')}")
    return "\n\n".join(parts)


def _phase_challenge(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    profiles, charter = _profiles(table)
    chair_id = str(doc.get("chair") or BOARD_CHAIR_DEFAULT)
    chair = profiles[chair_id]
    positions_text = _turns_text(table, doc, phases=("positions",))
    messages = [
        {"role": "system", "content": board_personas.render_system_prompt(chair, charter, meeting_role=MEETING_ROLE_CHAIR)},
        {"role": "system", "content": str(doc.get("contextPackText") or "")},
        {
            "role": "user",
            "content": (
                "Agenda:\n" + _agenda_text(doc) + "\n\nBoard positions:\n" + positions_text + "\n\n"
                "Identify the 2 to 4 most consequential disagreements or unexamined assumptions across these "
                "positions. Return strict JSON only: {\"conflicts\": [{\"topic\": \"<= 90 chars\", \"summary\": "
                "\"<= 80 words\", \"askedOf\": [\"persona ids\"], \"question\": \"the pointed question you want answered\"}]}. "
                "Use only these persona ids: " + ", ".join(sorted(profiles)) + "."
            ),
        },
    ]
    completion = _call(table, doc, messages=messages, json_mode=True, max_tokens=900, temperature=0.3, tag="board_meeting_challenge")
    raw = parse_json_object_text(completion.text)
    conflicts = normalize_conflicts(raw.get("conflicts"), persona_ids=set(profiles))
    lines = ["**Points of contention**"]
    for c in conflicts:
        lines.append(f"- **{c['topic']}** — {c['summary']} _Question to {', '.join(c['askedOf']) or 'the board'}:_ {c['question']}")
    out = _append_turn(
        table,
        {**doc, "conflicts": conflicts},
        {
            "phase": "challenge",
            "personaId": chair_id,
            "displayName": chair["displayName"],
            "title": chair["title"],
            "text": "\n".join(lines),
            "data": {"conflicts": conflicts},
            "usage": completion.usage,
            "model": completion.model,
        },
    )
    asked: dict[str, list[dict[str, Any]]] = {}
    for c in conflicts:
        for pid in c["askedOf"]:
            asked.setdefault(pid, []).append(c)
    if not asked:
        return out

    def _rebuttal(persona_id: str) -> list[dict[str, Any]]:
        profile = profiles[persona_id]
        qs = "\n".join(f"- {c['topic']}: {c['question']}" for c in asked[persona_id])
        messages_r = [
            {"role": "system", "content": board_personas.render_system_prompt(profile, charter, meeting_role=MEETING_ROLE_MEMBER)},
            {"role": "system", "content": str(doc.get("contextPackText") or "")},
            {
                "role": "user",
                "content": (
                    "Board positions so far:\n" + positions_text + "\n\nThe chair asks you specifically:\n" + qs +
                    "\n\nAnswer in at most 180 words, first person. Change your position if the arguments warrant it and say so."
                ),
            },
        ]
        result = _member_call(
            table, doc, profile=profile, phase="challenge", messages=messages_r, json_mode=False, max_tokens=500, tag="board_meeting_rebuttal"
        )
        turns: list[dict[str, Any]] = []
        tool_turn = _tool_turn(profile, "challenge", result.calls)
        if tool_turn:
            turns.append(tool_turn)
        turns.append(
            {
                "phase": "challenge",
                "personaId": persona_id,
                "displayName": profile["displayName"],
                "title": profile["title"],
                "text": _clean(result.text, MAX_TEXT),
                "usage": result.usage,
                "model": result.model,
            }
        )
        return turns

    order = [pid for pid in ([str(p["id"]) for p in doc.get("roster") or []] or list(profiles)) if pid in asked]
    with ThreadPoolExecutor(max_workers=max(1, BOARD_MAX_PARALLEL_PERSONA_CALLS)) as pool:
        results = list(pool.map(_rebuttal, order))
    for turns in results:
        for turn in turns:
            out = _append_turn(table, out, turn)
    return out


def normalize_conflicts(raw: Any, *, persona_ids: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for c in raw:
        if not isinstance(c, dict):
            continue
        topic = _clean(c.get("topic"), 120)
        summary = _clean(c.get("summary"), 800)
        question = _clean(c.get("question"), 400)
        if not (topic or summary):
            continue
        asked = []
        if isinstance(c.get("askedOf"), list):
            for pid in c["askedOf"]:
                p = str(pid or "").strip().lower()
                if p in persona_ids and p not in asked:
                    asked.append(p)
        out.append({"topic": topic or summary[:90], "summary": summary, "askedOf": asked[:4], "question": question or summary})
        if len(out) >= 4:
            break
    return out


def _phase_synthesis(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    profiles, charter = _profiles(table)
    chair_id = str(doc.get("chair") or BOARD_CHAIR_DEFAULT)
    chair = profiles[chair_id]
    discussion = _turns_text(table, doc, phases=("positions", "challenge"))
    open_actions = [a for a in board_store.list_actions(table) if a.get("status") == "open"]
    open_text = "\n".join(
        f"- id {a.get('actionId')}: [{a.get('priority')}] ({a.get('persona')}) {a.get('title')}" for a in open_actions[:40]
    ) or "(none)"
    schema = (
        "{\"headline\": \"one sentence\", "
        "\"discussion\": [{\"agendaIndex\": 1, \"summary\": \"<= 80 words\", \"consensus\": \"agree|split|deferred\"}], "
        "\"decisions\": [{\"text\": \"<= 200 chars\", \"proposedBy\": \"persona id\", \"rationale\": \"<= 200 chars\"}], "
        "\"risks\": [{\"text\": \"<= 200 chars\", \"owner\": \"persona id\", \"severity\": \"high|medium|low\"}], "
        "\"actions\": [{\"title\": \"imperative, <= 100 chars\", \"detail\": \"what done looks like\", \"persona\": \"persona id\", "
        "\"priority\": \"now|next|later\", \"effort\": \"S|M|L\", \"dueInDays\": 7, \"dependsOn\": [\"titles\"], "
        "\"metric\": \"how we know it worked\", \"existingActionId\": \"optional id of an open action this reaffirms\"}], "
        "\"questionsForOwner\": [\"decisions only the founder can make\"]}"
    )
    messages = [
        {"role": "system", "content": board_personas.render_system_prompt(chair, charter, meeting_role=MEETING_ROLE_CHAIR)},
        {"role": "system", "content": str(doc.get("contextPackText") or "")},
        {
            "role": "user",
            "content": (
                "Agenda:\n" + _agenda_text(doc) + "\n\nDiscussion transcript:\n" + discussion +
                "\n\nOpen action items already assigned to the founder (reference by id instead of re-creating):\n" + open_text +
                "\n\nWrite the minutes. Rules: at most 7 actions in total, at most 3 with priority \"now\"; each action is one "
                "concrete thing the founder can start this week; use persona ids for owners (" + ", ".join(sorted(profiles)) + "); "
                "no duplicate of an open action unless you set existingActionId. Return strict JSON only matching: " + schema
            ),
        },
    ]
    completion = _call(table, doc, messages=messages, json_mode=True, max_tokens=2200, temperature=0.3, tag="board_meeting_synthesis")
    raw = parse_json_object_text(completion.text)
    minutes = normalize_minutes(raw, agenda=doc.get("agenda") or [], persona_ids=set(profiles), default_persona=chair_id)
    text = board_context.render_minutes_brief(minutes)
    return _append_turn(
        table,
        {**doc, "minutes": minutes},
        {
            "phase": "synthesis",
            "personaId": chair_id,
            "displayName": chair["displayName"],
            "title": chair["title"],
            "text": "**Minutes**\n" + text,
            "data": {"minutes": minutes},
            "usage": completion.usage,
            "model": completion.model,
        },
    )


def normalize_minutes(
    raw: dict[str, Any],
    *,
    agenda: list[dict[str, Any]],
    persona_ids: set[str],
    default_persona: str,
) -> dict[str, Any]:
    def _pid(value: Any) -> str:
        p = str(value or "").strip().lower()
        return p if p in persona_ids else default_persona

    discussion = []
    if isinstance(raw.get("discussion"), list):
        for d in raw["discussion"][:MAX_AGENDA_ITEMS]:
            if not isinstance(d, dict):
                continue
            try:
                idx = int(d.get("agendaIndex") or 1)
            except (TypeError, ValueError):
                idx = 1
            idx = min(max(1, idx), max(1, len(agenda)))
            consensus = str(d.get("consensus") or "").strip().lower()
            if consensus not in ("agree", "split", "deferred"):
                consensus = "agree"
            discussion.append({"agendaIndex": idx, "summary": _clean(d.get("summary"), 1200), "consensus": consensus})

    decisions = []
    if isinstance(raw.get("decisions"), list):
        for d in raw["decisions"][:MAX_LIST]:
            if not isinstance(d, dict):
                continue
            text = _clean(d.get("text"), 400)
            if text:
                decisions.append({"text": text, "proposedBy": _pid(d.get("proposedBy")), "rationale": _clean(d.get("rationale"), 400)})

    risks = []
    if isinstance(raw.get("risks"), list):
        for r in raw["risks"][:MAX_LIST]:
            if not isinstance(r, dict):
                continue
            text = _clean(r.get("text"), 400)
            if not text:
                continue
            severity = str(r.get("severity") or "medium").strip().lower()
            if severity not in ("high", "medium", "low"):
                severity = "medium"
            risks.append({"text": text, "owner": _pid(r.get("owner")), "severity": severity})

    actions = []
    now_count = 0
    if isinstance(raw.get("actions"), list):
        for a in raw["actions"]:
            norm = normalize_action_proposal(a)
            if not norm:
                continue
            norm["persona"] = _pid(a.get("persona") if isinstance(a, dict) else None)
            if norm["priority"] == "now":
                now_count += 1
                if now_count > 3:
                    norm["priority"] = "next"
            actions.append(norm)
            if len(actions) >= 7:
                break

    questions = []
    if isinstance(raw.get("questionsForOwner"), list):
        questions = [_clean(q, 400) for q in raw["questionsForOwner"] if _clean(q, 400)][:6]

    return {
        "headline": _clean(raw.get("headline"), 300),
        "agenda": [{"title": a.get("title"), "question": a.get("question")} for a in agenda],
        "discussion": discussion,
        "decisions": decisions,
        "risks": risks,
        "actions": actions,
        "questionsForOwner": questions,
    }


def _phase_persist(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    minutes = doc.get("minutes") if isinstance(doc.get("minutes"), dict) else {}
    created_ids, reaffirmed_ids = board_actions.create_actions_from_minutes(
        table, minutes=minutes, meeting_id=str(doc["meetingId"])
    )
    try:
        import board_staff

        settings = board_store.load_settings(table)
        created = {str(a.get("actionId")): a for a in board_store.list_actions(table) if a.get("actionId") in created_ids}
        chair_id = str(doc.get("chair") or BOARD_CHAIR_DEFAULT)
        for action in created.values():
            if action.get("assignee"):
                board_staff.assign_from_minutes(table, settings, action=action, chair_id=chair_id)
    except Exception as exc:
        _log_event("warning", tag="board_staff_minutes_assign_failed", error=str(exc)[:300])
    date = str(doc.get("createdAt") or board_store.now_iso())[:10]
    board_store.append_decision_log(
        table,
        [
            {"date": date, "meetingId": doc["meetingId"], "text": d.get("text"), "proposedBy": d.get("proposedBy")}
            for d in minutes.get("decisions") or []
        ],
    )
    out = {
        **doc,
        "createdActionIds": created_ids,
        "reaffirmedActionIds": reaffirmed_ids,
        "updatedAt": board_store.now_iso(),
    }
    board_store.put_meeting(table, out)
    return out


PHASE_RUNNERS = {
    "prepare": _phase_prepare,
    "agenda": _phase_agenda,
    "positions": _phase_positions,
    "challenge": _phase_challenge,
    "synthesis": _phase_synthesis,
    "persist": _phase_persist,
}


# ---------------------------------------------------------------------------
# Public views
# ---------------------------------------------------------------------------

def public_meeting_summary(doc: dict[str, Any]) -> dict[str, Any]:
    minutes = doc.get("minutes") if isinstance(doc.get("minutes"), dict) else None
    return {
        "meetingId": doc.get("meetingId"),
        "status": doc.get("status"),
        "mode": doc.get("mode"),
        "chair": doc.get("chair"),
        "topic": doc.get("topic") or "",
        "trigger": doc.get("trigger"),
        "phase": doc.get("phase"),
        "phases": doc.get("phases") or [],
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "headline": (minutes or {}).get("headline") or "",
        "actionCount": len((minutes or {}).get("actions") or []),
        "usage": doc.get("usage") or {},
        "errorMessage": doc.get("errorMessage"),
    }


def public_meeting_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out = public_meeting_summary(doc)
    out.update(
        {
            "agenda": doc.get("agenda") or [],
            "conflicts": doc.get("conflicts") or [],
            "minutes": doc.get("minutes"),
            "roster": doc.get("roster") or [],
            "contextPackHash": doc.get("contextPackHash"),
            "contextPackChars": doc.get("contextPackChars"),
            "memberProfileHashes": doc.get("memberProfileHashes") or {},
            "models": doc.get("models") or {},
            "createdActionIds": doc.get("createdActionIds") or [],
            "reaffirmedActionIds": doc.get("reaffirmedActionIds") or [],
            "turnCount": doc.get("turnCount") or 0,
        }
    )
    return out


def _clean(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split()) if limit <= 400 else str(value).strip()
    return text[:limit]
