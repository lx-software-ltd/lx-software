"""Executive Board: chat with an individual board member.

``POST /siu-tin-dei/board/chat/{personaId}`` stores the founder's message and
a pending job, then self-invokes the Lambda (``internal: "board_chat"``).
The worker builds the persona prompt, calls OpenRouter, appends the reply to
the thread and marks the job succeeded. The SPA polls the job.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import board_async
import board_budget
import board_context
import board_personas
import board_store
import board_tools
from contract_constants import (
    BOARD_CHAT_HISTORY_TURNS,
    BOARD_CHAT_JOB_STUCK_SECONDS,
    BOARD_CHAT_OPENROUTER_TIMEOUT_SECONDS,
    BOARD_CHAT_TOOL_LOOP_MAX_SECONDS,
    BOARD_MAX_CHAT_MESSAGE_LEN,
    BOARD_MAX_TOPIC_LEN,
)
from http_common import _audit, _json_response, _log_event, _parse_json_body, _request_id, _utc_iso_z
from openrouter_client import OpenRouterError
from runtime import logger

THREAD_PAGE_SIZE = 100
_SUGGEST_MEETING_RE = re.compile(r"^\s*SUGGEST_MEETING:\s*(\{.*\})\s*$", re.MULTILINE)

CHAIR_CHAT_INSTRUCTIONS = (
    "You chair the board. If the founder asks you to convene, schedule or run a "
    "meeting (or you judge one is clearly needed), end your reply with exactly one "
    "line of the form SUGGEST_MEETING: {\"mode\": \"standup\" | \"deepDive\", "
    "\"topic\": \"<short topic>\"} — the admin UI turns it into a button. Never "
    "claim a meeting has been started; only the founder can start one."
)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

def handle_thread_get(persona_id: str) -> dict[str, Any]:
    table = board_store.records_table()
    messages = board_store.list_chat_messages(table, persona_id, limit=THREAD_PAGE_SIZE)
    return _json_response(200, {"personaId": persona_id, "messages": messages})


def handle_thread_delete(event: dict[str, Any], persona_id: str, user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    removed = board_store.clear_chat_thread(table, persona_id)
    _audit(user_sub, "BOARD_CHAT_CLEAR", persona_id, event)
    return _json_response(200, {"ok": True, "removed": removed})


def handle_message_post(event: dict[str, Any], persona_id: str, user_sub: str | None) -> dict[str, Any]:
    if not user_sub:
        return _json_response(400, {"message": "Missing sub claim"})
    body = _parse_json_body(event)
    raw = body.get("text")
    if not isinstance(raw, str) or not raw.strip():
        return _json_response(400, {"message": "text is required"})
    text = raw.strip()
    if len(text) > BOARD_MAX_CHAT_MESSAGE_LEN:
        return _json_response(
            400,
            {"message": f"text must be at most {BOARD_MAX_CHAT_MESSAGE_LEN} characters"},
        )
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    try:
        board_budget.check_budget(table, settings)
    except board_budget.BudgetExceeded as exc:
        return _json_response(429, {"message": str(exc)})

    user_message = board_store.add_chat_message(table, persona_id, role="user", text=text)
    job_id = board_store.new_id()
    created = board_store.now_iso()
    board_store.put_chat_job(
        table,
        {
            "jobId": job_id,
            "status": "pending",
            "personaId": persona_id,
            "userMessageId": user_message["messageId"],
            "ownerSub": user_sub,
            "createdAt": created,
            "updatedAt": created,
            "apiRequestId": _request_id(event)[:256],
        },
    )
    payload = {"internal": "board_chat", "jobId": job_id, "personaId": persona_id}
    try:
        board_async.invoke_async(payload, fallback=run_chat_worker)
    except Exception as exc:
        _log_event("error", tag="board_chat_enqueue_failed", err=str(exc)[:400])
        board_store.put_chat_job(
            table,
            {
                "jobId": job_id,
                "status": "failed",
                "personaId": persona_id,
                "ownerSub": user_sub,
                "createdAt": created,
                "updatedAt": board_store.now_iso(),
                "errorMessage": "Could not start the reply job",
            },
        )
        return _json_response(502, {"message": "Could not start the reply job"})
    _audit(user_sub, "BOARD_CHAT", persona_id, event)
    return _json_response(
        202,
        {"jobId": job_id, "status": "pending", "userMessage": user_message},
    )


def handle_job_get(persona_id: str, job_id: str, user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    job = board_store.get_chat_job(table, job_id)
    if not job:
        return _json_response(404, {"message": "Job not found"})
    if job.get("personaId") != persona_id:
        return _json_response(400, {"message": "Persona does not match job"})
    if user_sub and job.get("ownerSub") not in (user_sub, "", None):
        return _json_response(403, {"message": "Forbidden"})
    job = _finalize_stuck_job(table, job)
    status = job.get("status")
    if status in ("pending", "processing"):
        return _json_response(200, {"status": status, "toolCalls": job.get("toolCalls") or []})
    if status == "succeeded":
        return _json_response(
            200,
            {"status": "succeeded", "message": job.get("assistantMessage") or {}},
        )
    if status == "failed":
        return _json_response(
            200,
            {"status": "failed", "message": str(job.get("errorMessage") or "Reply failed")},
        )
    return _json_response(200, {"status": "unknown"})


def _finalize_stuck_job(table: Any, job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") not in ("pending", "processing"):
        return job
    updated = _iso_to_dt(job.get("updatedAt"))
    if updated is None:
        return job
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    if age <= BOARD_CHAT_JOB_STUCK_SECONDS:
        return job
    failed = {
        **job,
        "status": "failed",
        "errorMessage": "The reply did not arrive in time. Please send your message again.",
        "updatedAt": board_store.now_iso(),
    }
    board_store.put_chat_job(table, failed)
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
# Worker
# ---------------------------------------------------------------------------

def run_chat_worker(payload: dict[str, Any]) -> None:
    job_id = str(payload.get("jobId") or "").strip()
    persona_id = str(payload.get("personaId") or "").strip()
    if not job_id or not board_personas.is_persona_id(persona_id):
        _log_event("warning", tag="board_chat_worker_bad_payload")
        return
    table = board_store.records_table()
    stale = _utc_iso_z(datetime.now(timezone.utc) - timedelta(seconds=BOARD_CHAT_JOB_STUCK_SECONDS))
    if not board_store.claim_chat_job(table, job_id, stale_before_iso=stale):
        _log_event("info", tag="board_chat_skip_duplicate_worker", job_id=job_id[:64])
        return
    job = board_store.get_chat_job(table, job_id) or {"jobId": job_id, "personaId": persona_id}

    def _progress(calls: list[dict[str, Any]]) -> None:
        # Lets the SPA show "Looking at GitHub…" lines while the reply is still running.
        board_store.put_chat_job(
            table,
            {**job, "status": "processing", "toolCalls": calls, "updatedAt": board_store.now_iso()},
        )

    try:
        reply = generate_reply(table, persona_id=persona_id, job_id=job_id, on_progress=_progress)
    except (OpenRouterError, board_budget.BudgetExceeded) as exc:
        _fail_job(table, job, str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("board chat worker failed")
        _fail_job(table, job, f"Reply failed unexpectedly: {str(exc)[:200]}")
        return

    board_store.put_chat_job(
        table,
        {
            **job,
            "status": "succeeded",
            "assistantMessage": reply,
            "updatedAt": board_store.now_iso(),
        },
    )


def _fail_job(table: Any, job: dict[str, Any], message: str) -> None:
    _log_event("warning", tag="board_chat_failed", job_id=str(job.get("jobId"))[:64], error=message[:300])
    board_store.put_chat_job(
        table,
        {**job, "status": "failed", "errorMessage": message[:500], "updatedAt": board_store.now_iso()},
    )


def generate_reply(
    table: Any,
    *,
    persona_id: str,
    job_id: str = "",
    on_progress: Any = None,
) -> dict[str, Any]:
    """Build the persona prompt from the thread + context pack, run the tool loop, persist the reply."""
    settings = board_store.load_settings(table)
    board_budget.check_budget(table, settings)
    charter = board_store.load_charter(table)
    roster = board_personas.effective_roster(board_store.load_member_overrides(table))
    profile = board_personas.roster_by_id(roster)[persona_id]
    pack = board_context.build_context_pack(table, settings, roster=roster)

    is_chair = persona_id == str(settings.get("defaultChair") or "")
    system_prompt = board_personas.render_system_prompt(
        profile,
        charter,
        meeting_role=CHAIR_CHAT_INSTRUCTIONS if is_chair else None,
    )
    history = board_store.list_chat_messages(table, persona_id, limit=BOARD_CHAT_HISTORY_TURNS)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": pack["text"]},
    ]
    try:
        import board_mail

        _pseud = board_mail.pseudonymizer(table)
    except Exception:
        _pseud = None
    for msg in history:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        text = str(msg.get("text") or "").strip()
        if not text:
            continue
        if role == "user" and _pseud is not None:
            text = _pseud.mask_text(text)
        messages.append({"role": role, "content": text})
    if _pseud is not None:
        try:
            _pseud.save()
        except Exception:
            pass
    if not history or history[-1].get("role") != "user":
        messages.append(
            {"role": "user", "content": "(The founder is waiting for your reply to the thread above.)"}
        )

    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id=persona_id,
        display_name=str(profile.get("displayName") or profile.get("shortName") or persona_id),
        kind="chat",
        job_id=job_id,
    )
    result = board_tools.run_tool_loop(
        ctx=ctx,
        messages=messages,
        model=board_budget.model_for("chat", settings),
        timeout=BOARD_CHAT_OPENROUTER_TIMEOUT_SECONDS,
        max_tokens=1200,
        temperature=0.5,
        json_mode=False,
        tag="board_chat_reply",
        max_seconds=BOARD_CHAT_TOOL_LOOP_MAX_SECONDS,
        on_progress=on_progress,
    )
    text, suggested = extract_suggested_meeting(result.text)
    extra: dict[str, Any] = {
        "model": result.model,
        "profileHash": profile["profileHash"],
        "contextHash": pack["hash"],
    }
    if suggested:
        extra["suggestedMeeting"] = suggested
    if result.calls:
        extra["toolCalls"] = result.calls
    return board_store.add_chat_message(
        table,
        persona_id,
        role="assistant",
        text=text.strip() or "(empty reply)",
        usage=result.usage,
        extra=extra,
    )


def extract_suggested_meeting(text: str) -> tuple[str, dict[str, Any] | None]:
    """Split a trailing ``SUGGEST_MEETING: {...}`` line off the reply text."""
    match = _SUGGEST_MEETING_RE.search(text or "")
    if not match:
        return text, None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text.replace(match.group(0), "").rstrip(), None
    if not isinstance(data, dict):
        return text.replace(match.group(0), "").rstrip(), None
    mode = str(data.get("mode") or "deepDive")
    if mode not in ("standup", "deepDive"):
        mode = "deepDive"
    topic = str(data.get("topic") or "").strip()[:BOARD_MAX_TOPIC_LEN]
    cleaned = text.replace(match.group(0), "").rstrip()
    return cleaned, {"mode": mode, "topic": topic}
