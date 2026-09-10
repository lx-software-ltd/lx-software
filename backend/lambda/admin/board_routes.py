"""Executive Board: HTTP routing under ``/siu-tin-dei/board``."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs

import board_actions
import board_budget
import board_chat
import board_github
import board_mail
import board_meta
import board_meeting
import board_personas
import board_receivables
import board_research
import board_staff
import board_store
import board_stores
import board_tools
import board_web
from contract_constants import (
    BOARD_CHAIR_DEFAULT,
    BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES,
    BOARD_MAIL_LIST_MAX_THREADS,
    BOARD_MAX_APPROVAL_NOTE_LEN,
    BOARD_MAX_BRIEF_LEN,
    BOARD_MAX_DAILY_BUDGET_USD,
    BOARD_MAX_UPDATE_LEN,
    BOARD_MEETING_MODES,
    BOARD_TOOL_GLOBAL_MODES,
    BOARD_TOOL_LEVELS,
)
from http_common import _audit, _json_response, _log_event, _parse_json_body

BOARD_BASE_PATH = "/siu-tin-dei/board"
ALLOW_LIST_EMAIL_RE = re.compile(r"^(?:[a-z0-9._%+\-]+)?@[a-z0-9.\-]+\.[a-z]{2,}$")
ALLOW_LIST_PHONE_RE = re.compile(r"^\+?\d{8,15}$")


def handle_board_route(
    event: dict[str, Any], method: str, path: str, user_sub: str | None
) -> dict[str, Any] | None:
    """Return a response for board routes, or None when the path is not ours."""
    if path != BOARD_BASE_PATH and not path.startswith(BOARD_BASE_PATH + "/"):
        return None
    rest = [p for p in path[len(BOARD_BASE_PATH):].split("/") if p]

    if not rest:
        if method == "GET":
            return _overview()
        return _json_response(405, {"message": "Method not allowed"})

    head = rest[0]

    if head == "charter" and len(rest) == 1 and method == "PUT":
        return _charter_put(event, user_sub)

    if head == "members" and len(rest) == 2:
        persona_id = rest[1].lower()
        if not board_personas.is_persona_id(persona_id):
            return _json_response(404, {"message": "Unknown board member"})
        if method == "PUT":
            return _member_put(event, persona_id, user_sub)
        if method == "DELETE":
            return _member_reset(event, persona_id, user_sub)

    if head == "brief" and len(rest) == 1 and method == "PUT":
        return _brief_put(event, user_sub)

    if head == "settings" and len(rest) == 1 and method == "PUT":
        return _settings_put(event, user_sub)

    if head == "updates" and len(rest) == 1:
        if method == "POST":
            return _update_post(event, user_sub)
        if method == "GET":
            table = board_store.records_table()
            return _json_response(200, {"updates": board_store.list_updates(table, limit=50)})

    if head == "chat" and len(rest) >= 2:
        persona_id = rest[1].lower()
        if not board_personas.is_persona_id(persona_id):
            return _json_response(404, {"message": "Unknown board member"})
        if len(rest) == 2:
            if method == "GET":
                return board_chat.handle_thread_get(persona_id)
            if method == "POST":
                return board_chat.handle_message_post(event, persona_id, user_sub)
            if method == "DELETE":
                return board_chat.handle_thread_delete(event, persona_id, user_sub)
        if len(rest) == 4 and rest[2] == "jobs" and method == "GET":
            return board_chat.handle_job_get(persona_id, rest[3], user_sub)

    if head == "meetings":
        if len(rest) == 1:
            if method == "GET":
                return board_meeting.handle_meetings_get()
            if method == "POST":
                return board_meeting.handle_meeting_post(event, user_sub)
        if len(rest) == 2 and method == "GET":
            return board_meeting.handle_meeting_get(rest[1])
        if len(rest) == 3 and rest[2] == "cancel" and method == "POST":
            return board_meeting.handle_meeting_cancel(event, rest[1], user_sub)

    if head == "actions":
        if len(rest) == 1 and method == "GET":
            return board_actions.handle_actions_get(event)
        if len(rest) == 2 and method == "PUT":
            return board_actions.handle_action_put(event, rest[1], user_sub)

    if head == "repo-snapshot" and len(rest) == 2 and rest[1] == "refresh" and method == "POST":
        return _repo_snapshot_refresh(event, user_sub)

    if head == "tools":
        if len(rest) == 1:
            if method == "GET":
                return _tools_get()
            if method == "PUT":
                return _tools_put(event, user_sub)
        if len(rest) == 2 and rest[1] == "calls" and method == "GET":
            return _tool_calls_get(event)

    if head == "approvals":
        if len(rest) == 1 and method == "GET":
            return _approvals_get(event)
        if len(rest) == 3 and rest[2] in ("approve", "reject") and method == "POST":
            return _approval_decide(event, rest[1], approve=rest[2] == "approve", user_sub=user_sub)

    if head == "mail":
        if len(rest) == 1 and method == "GET":
            return _mail_list(event)
        if len(rest) == 2 and method == "GET":
            return _mail_thread_get(event, rest[1])
        if len(rest) == 3 and rest[2] == "read" and method == "POST":
            return _mail_thread_read(event, rest[1], user_sub)

    if head == "receivables" and len(rest) == 1 and method == "GET":
        return _json_response(200, board_receivables.aging_for_owner())

    if head == "staff":
        return _staff_route(event, method, rest, user_sub)

    if head == "tasks":
        return _tasks_route(event, method, rest, user_sub)

    return _json_response(404, {"message": "Not found"})


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _overview() -> dict[str, Any]:
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    roster = board_personas.effective_roster(board_store.load_member_overrides(table))
    meetings = board_store.list_meetings(table, limit=5)
    meetings = [board_meeting._finalize_stuck(table, m) for m in meetings]
    actions = board_store.list_actions(table)
    open_count = sum(1 for a in actions if a.get("status") == "open")
    running = next((m for m in meetings if m.get("status") == "running"), None)
    latest_done = next((m for m in meetings if m.get("status") == "succeeded"), None)
    usage = board_store.load_usage_day(table)
    pending_approvals = sum(1 for a in board_store.list_approvals(table) if a.get("status") == "pending")
    mail = board_mail.status_summary(table)
    recv = board_receivables.digest_for_context()
    return _json_response(
        200,
        {
            "settings": settings,
            "charter": board_store.load_charter(table),
            "brief": board_store.load_brief(table),
            "members": roster,
            "chairDefault": BOARD_CHAIR_DEFAULT,
            "openActionCount": open_count,
            "pendingApprovalCount": pending_approvals,
            "unreadMailCount": mail["unreadCount"],
            "overdueInvoiceCount": int(recv.get("overdue") or 0),
            "mail": mail,
            "receivables": recv,
            "toolsEnabled": board_tools.tools_enabled(settings),
            "runningMeeting": board_meeting.public_meeting_summary(running) if running else None,
            "latestMeeting": board_meeting.public_meeting_summary(latest_done) if latest_done else None,
            "usageToday": {
                **usage,
                "budgetUsd": board_budget.daily_budget_usd(settings),
                "external": {
                    "searchCalls": board_store.load_external_usage_day(table)["searchCalls"],
                    "metaAdsMonthUsd": round(board_store.load_ads_spend(table)["monthlyUsd"], 2),
                },
            },
            "models": {
                "chat": board_budget.model_for("chat", settings),
                "standup": board_budget.model_for("standup", settings),
                "deepDive": board_budget.model_for("deepDive", settings),
            },
            "repoSnapshot": board_github.public_snapshot_meta(board_store.load_repo_snapshot(table)),
            "repoSnapshotEnabled": board_github.snapshot_enabled(),
            "repoWriteEnabled": board_github.write_enabled(),
            "repo": board_github.repo_full_name(),
        },
    )


def _tools_get() -> dict[str, Any]:
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    return _json_response(200, _tools_payload(settings))


def _tools_payload(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "config": settings.get("tools") or board_store.default_tools_config(),
        "effective": board_tools.effective_matrix(settings),
        "enabled": board_tools.tools_enabled(settings),
        "envDisabled": board_tools.env_disabled(),
        "registry": board_tools.public_registry(),
        "defaults": board_store.default_tools_config(),
        "repoWriteEnabled": board_github.write_enabled(),
        "mailSendEnabled": board_mail.sending_enabled(),
        "mailDomain": board_mail.mail_domain(),
        "searchConfigured": board_research.search_configured(),
        "dataApiConfigured": board_receivables.configured(),
        "metaConfigured": board_meta.configured(),
        "storesConfigured": board_stores.configured(),
        "webConfigured": board_web.configured(),
        "adsSpend": board_meta.ads_spend_snapshot(board_store.records_table(), settings),
    }


def validate_tools_config(body: Any, current: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    out = {**current}
    if "enabled" in body:
        out["enabled"] = bool(body.get("enabled"))
    if "globalMode" in body:
        mode = body.get("globalMode")
        if mode not in BOARD_TOOL_GLOBAL_MODES:
            raise ValueError("globalMode must be readOnly, propose or act")
        out["globalMode"] = mode
    if "matrix" in body:
        matrix = body.get("matrix")
        if not isinstance(matrix, dict):
            raise ValueError("matrix must be an object of {toolId: {personaId: level}}")
        merged = {tool_id: dict(cells) for tool_id, cells in current["matrix"].items()}
        for tool_id, cells in matrix.items():
            if tool_id not in merged:
                raise ValueError(f"Unknown tool '{tool_id}'")
            if not isinstance(cells, dict):
                raise ValueError(f"matrix.{tool_id} must be an object")
            for pid, level in cells.items():
                if pid not in merged[tool_id]:
                    raise ValueError(f"Unknown board member '{pid}'")
                if level not in BOARD_TOOL_LEVELS:
                    raise ValueError(f"Level for {tool_id}/{pid} must be one of {', '.join(BOARD_TOOL_LEVELS)}")
                merged[tool_id][pid] = level
        out["matrix"] = merged
    if "allowList" in body:
        entries = body.get("allowList")
        if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
            raise ValueError("allowList must be an array of addresses, @domains, or phone numbers")
        if len(entries) > BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES:
            raise ValueError(f"allowList may hold at most {BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES} entries")
        for entry in entries:
            compact = "".join(entry.split()).strip("<>")
            if not compact:
                continue
            if ALLOW_LIST_PHONE_RE.fullmatch(compact):
                continue
            if not ALLOW_LIST_EMAIL_RE.fullmatch(compact.lower()):
                raise ValueError(
                    f"allowList entry '{compact[:80]}' must be a full address (name@host.tld), "
                    "a domain (@host.tld), or a phone number (E.164, 8–15 digits)"
                )
        out["allowList"] = board_store.normalize_allow_list(entries)
    if "spendCaps" in body:
        caps = body.get("spendCaps")
        if not isinstance(caps, dict):
            raise ValueError("spendCaps must be an object")
        out["spendCaps"] = caps
    return board_store.normalize_tools_config(out)


def _tools_put(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    try:
        tools_config = validate_tools_config(_parse_json_body(event), settings["tools"])
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    saved = board_store.save_settings(table, {**settings, "tools": tools_config})
    _audit(user_sub, "BOARD_TOOLS_PUT", "tools", event)
    return _json_response(200, _tools_payload(saved))


def _tool_calls_get(event: dict[str, Any]) -> dict[str, Any]:
    from urllib.parse import parse_qs

    qs = parse_qs(event.get("rawQueryString") or "")
    try:
        limit = min(max(1, int((qs.get("limit") or ["50"])[0])), 200)
    except ValueError:
        limit = 50
    table = board_store.records_table()
    return _json_response(200, {"calls": board_store.list_tool_calls(table, limit=limit)})


def _approvals_get(event: dict[str, Any]) -> dict[str, Any]:
    from urllib.parse import parse_qs

    qs = parse_qs(event.get("rawQueryString") or "")
    status = (qs.get("status") or [""])[0].strip().lower()
    table = board_store.records_table()
    items = board_store.list_approvals(table)
    if status:
        items = [a for a in items if a.get("status") == status]
    return _json_response(200, {"approvals": [board_tools.public_approval(a) for a in items[:200]]})


def _approval_decide(event: dict[str, Any], approval_id: str, *, approve: bool, user_sub: str | None) -> dict[str, Any]:
    if not user_sub:
        return _json_response(400, {"message": "Missing sub claim"})
    body = _parse_json_body(event)
    note = body.get("note") if isinstance(body, dict) else ""
    if note is None:
        note = ""
    if not isinstance(note, str):
        return _json_response(400, {"message": "note must be a string"})
    if len(note) > BOARD_MAX_APPROVAL_NOTE_LEN:
        return _json_response(400, {"message": f"note must be at most {BOARD_MAX_APPROVAL_NOTE_LEN} characters"})
    override = body.get("arguments") if isinstance(body, dict) else None
    if override is not None and not isinstance(override, dict):
        return _json_response(400, {"message": "arguments must be an object"})
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    try:
        decided = board_tools.decide_approval(
            table,
            settings,
            approval_id,
            approve=approve,
            owner_sub=user_sub,
            note=note.strip(),
            arguments_override=override if approve else None,
        )
    except LookupError as exc:
        return _json_response(404, {"message": str(exc)})
    except board_tools.InvalidArgumentsError as exc:
        return _json_response(400, {"message": str(exc)})
    except ValueError as exc:
        return _json_response(409, {"message": str(exc)})
    _audit(user_sub, "BOARD_APPROVAL_APPROVE" if approve else "BOARD_APPROVAL_REJECT", approval_id, event)
    return _json_response(200, {"approval": board_tools.public_approval(decided)})


THREAD_ID_RE = re.compile(r"^[a-f0-9]{8,40}$")


def _mail_list(event: dict[str, Any]) -> dict[str, Any]:
    qs = parse_qs(event.get("rawQueryString") or "")
    try:
        limit = min(max(1, int((qs.get("limit") or ["50"])[0])), BOARD_MAIL_LIST_MAX_THREADS)
    except ValueError:
        limit = 50
    table = board_store.records_table()
    listing = board_mail.thread_list(
        table,
        mailbox=(qs.get("mailbox") or [""])[0],
        query=(qs.get("q") or [""])[0][:200],
        unread_only=(qs.get("unread") or [""])[0] in ("1", "true"),
        limit=limit,
    )
    return _json_response(200, {**listing, "status": board_mail.status_summary(table)})


def _mail_thread_get(event: dict[str, Any], thread_id: str) -> dict[str, Any]:
    if not THREAD_ID_RE.fullmatch(thread_id):
        return _json_response(404, {"message": "Thread not found"})
    qs = parse_qs(event.get("rawQueryString") or "")
    table = board_store.records_table()
    if (qs.get("view") or [""])[0] == "board":
        detail = board_mail.masked_thread_detail(table, thread_id)
    else:
        detail = board_mail.thread_detail(table, thread_id)
    if not detail:
        return _json_response(404, {"message": "Thread not found"})
    return _json_response(200, detail)


def _mail_thread_read(event: dict[str, Any], thread_id: str, user_sub: str | None) -> dict[str, Any]:
    if not THREAD_ID_RE.fullmatch(thread_id):
        return _json_response(404, {"message": "Thread not found"})
    body = _parse_json_body(event)
    read = body.get("read", True) if isinstance(body, dict) else True
    if not isinstance(read, bool):
        return _json_response(400, {"message": "read must be a boolean"})
    table = board_store.records_table()
    if not board_mail.mark_read(table, thread_id, read=read):
        return _json_response(404, {"message": "Thread not found"})
    _audit(user_sub, "BOARD_MAIL_READ" if read else "BOARD_MAIL_UNREAD", thread_id, event)
    return _json_response(200, {"thread": board_store.get_mail_thread(table, thread_id)})


def _charter_put(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    try:
        charter = board_personas.validate_charter(_parse_json_body(event))
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    saved = board_store.save_charter(table, vision=charter["vision"], mission=charter["mission"], owner_sub=user_sub)
    _audit(user_sub, "BOARD_CHARTER_PUT", "charter", event)
    return _json_response(200, {"charter": saved})


def _member_put(event: dict[str, Any], persona_id: str, user_sub: str | None) -> dict[str, Any]:
    try:
        override = board_personas.validate_member_override(_parse_json_body(event))
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    doc = {**override, "updatedAt": board_store.now_iso(), "updatedBySub": user_sub or ""}
    board_store.save_member_override(table, persona_id, doc)
    _audit(user_sub, "BOARD_MEMBER_PUT", persona_id, event)
    profile = board_personas.effective_profile(board_personas.persona_default(persona_id) or {"id": persona_id}, doc)
    return _json_response(200, {"member": profile})


def _member_reset(event: dict[str, Any], persona_id: str, user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    board_store.delete_member_override(table, persona_id)
    _audit(user_sub, "BOARD_MEMBER_RESET", persona_id, event)
    profile = board_personas.effective_profile(board_personas.persona_default(persona_id) or {"id": persona_id}, None)
    return _json_response(200, {"member": profile})


def _brief_put(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    body = _parse_json_body(event)
    raw = body.get("markdown", "")
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        return _json_response(400, {"message": "markdown must be a string"})
    if len(raw) > BOARD_MAX_BRIEF_LEN:
        return _json_response(400, {"message": f"markdown must be at most {BOARD_MAX_BRIEF_LEN} characters"})
    table = board_store.records_table()
    saved = board_store.save_brief(table, markdown=raw.strip(), owner_sub=user_sub)
    _audit(user_sub, "BOARD_BRIEF_PUT", "brief", event)
    return _json_response(200, {"brief": saved})


def validate_settings(body: Any, current: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    out = {**current}
    schedule = body.get("schedule")
    if schedule is not None:
        if not isinstance(schedule, dict):
            raise ValueError("schedule must be an object")
        out["schedule"] = {
            "morningEnabled": bool(schedule.get("morningEnabled", current["schedule"]["morningEnabled"])),
            "eveningEnabled": bool(schedule.get("eveningEnabled", current["schedule"]["eveningEnabled"])),
        }
    if "defaultMode" in body:
        mode = body.get("defaultMode")
        if mode not in BOARD_MEETING_MODES:
            raise ValueError("defaultMode must be standup or deepDive")
        out["defaultMode"] = mode
    if "defaultChair" in body:
        chair = body.get("defaultChair")
        if not board_personas.is_persona_id(chair):
            raise ValueError("defaultChair must be a board member id")
        out["defaultChair"] = chair
    for key in ("shareFinanceSummary", "shareRepoSnapshot"):
        if key in body:
            out[key] = bool(body.get(key))
    if "models" in body:
        models = body.get("models")
        if not isinstance(models, dict):
            raise ValueError("models must be an object")
        cleaned: dict[str, str] = {}
        for kind in ("chat", "standup", "deepDive"):
            value = models.get(kind, current["models"].get(kind, ""))
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ValueError(f"models.{kind} must be a string")
            value = value.strip()
            if len(value) > 120:
                raise ValueError(f"models.{kind} is too long")
            cleaned[kind] = value
        out["models"] = cleaned
    if "dailyBudgetUsd" in body:
        raw = body.get("dailyBudgetUsd")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("dailyBudgetUsd must be a number")
        if raw < 0 or raw > BOARD_MAX_DAILY_BUDGET_USD:
            raise ValueError(f"dailyBudgetUsd must be between 0 and {BOARD_MAX_DAILY_BUDGET_USD}")
        out["dailyBudgetUsd"] = round(float(raw), 2)
    if "staff" in body:
        if not isinstance(body.get("staff"), dict):
            raise ValueError("staff must be an object")
        out["staff"] = board_store.normalize_staff_config({**(current.get("staff") or {}), **body["staff"]})
    if "review" in body:
        if not isinstance(body.get("review"), dict):
            raise ValueError("review must be an object")
        out["review"] = board_store.normalize_review_config({**(current.get("review") or {}), **body["review"]})
    if "boundaries" in body:
        if not isinstance(body.get("boundaries"), dict):
            raise ValueError("boundaries must be an object")
        out["boundaries"] = board_store.normalize_boundaries({**(current.get("boundaries") or {}), **body["boundaries"]})
    return out


def _staff_disabled() -> dict[str, Any]:
    return _json_response(409, {"message": "Staff is disabled"})


def _staff_route(event: dict[str, Any], method: str, rest: list[str], user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if len(rest) == 1:
        if method == "GET":
            if not board_staff.env_enabled():
                return _staff_disabled()
            return _json_response(
                200,
                {
                    "enabled": board_staff.enabled(settings),
                    "envEnabled": True,
                    "seats": board_staff.seats(table, settings),
                    "counts": board_staff.staff_counts(table),
                },
            )
        return _json_response(405, {"message": "Method not allowed"})
    if len(rest) == 2:
        seat_id = rest[1]
        if not board_staff.is_seat_id(seat_id):
            return _json_response(404, {"message": "Unknown staff seat"})
        if not board_staff.env_enabled():
            return _staff_disabled()
        if method == "PUT":
            try:
                patch = board_staff.validate_seat_override(_parse_json_body(event))
            except board_staff.StaffError as exc:
                return _json_response(400, {"message": str(exc)})
            board_store.save_staff_override(table, seat_id, patch)
            _audit(user_sub, "BOARD_STAFF_PUT", seat_id, event)
            return _json_response(200, {"seat": next((s for s in board_staff.seats(table) if s["id"] == seat_id), None)})
        if method == "DELETE":
            board_store.delete_staff_override(table, seat_id)
            _audit(user_sub, "BOARD_STAFF_RESET", seat_id, event)
            return _json_response(200, {"seat": next((s for s in board_staff.seats(table) if s["id"] == seat_id), None)})
        return _json_response(405, {"message": "Method not allowed"})
    return _json_response(404, {"message": "Not found"})


def _tasks_route(event: dict[str, Any], method: str, rest: list[str], user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if len(rest) == 1:
        if method == "GET":
            if not board_staff.env_enabled():
                return _staff_disabled()
            qs = parse_qs(event.get("rawQueryString") or "")
            status = (qs.get("status") or [""])[0] or None
            assignee = (qs.get("assignee") or [""])[0] or None
            try:
                limit = int((qs.get("limit") or ["100"])[0])
            except (TypeError, ValueError):
                limit = 100
            limit = max(1, min(200, limit))
            tasks = board_staff.list_tasks_for_api(table, status=status, assignee=assignee, limit=limit)
            return _json_response(200, {"tasks": [board_staff.public_task(t) for t in tasks], "counts": board_staff.staff_counts(table)})
        if method == "POST":
            if not board_staff.enabled(settings):
                return _staff_disabled()
            body = _parse_json_body(event)
            try:
                task = board_staff.create_task(
                    table,
                    settings,
                    assignee=str(body.get("assignee") or ""),
                    origin="owner",
                    brief=str(body.get("brief") or ""),
                    deliverable_type=str(body.get("deliverableType") or "markdown"),
                    budget_usd=body.get("budgetUsd"),
                    sla_hours=int(body.get("slaHours") or 24),
                    created_by=user_sub or "",
                )
            except board_staff.StaffError as exc:
                message = str(exc)
                return _json_response(409 if "disabled" in message.lower() else 400, {"message": message})
            except (TypeError, ValueError) as exc:
                return _json_response(400, {"message": str(exc)})
            _audit(user_sub, "BOARD_TASK_CREATE", task.get("taskId") or "", event)
            return _json_response(201, {"task": board_staff.public_task(task)})
        return _json_response(405, {"message": "Method not allowed"})
    if len(rest) == 2:
        if method != "GET":
            return _json_response(405, {"message": "Method not allowed"})
        if not board_staff.env_enabled():
            return _staff_disabled()
        task = board_store.get_task(table, rest[1])
        if not task:
            return _json_response(404, {"message": "Task not found"})
        return _json_response(
            200,
            {
                "task": board_staff.public_task(task),
                "steps": board_store.list_task_steps(table, rest[1]),
                "reviews": board_store.list_task_reviews(table, rest[1]),
                "deliverable": board_staff.read_deliverable(task),
                "deliverableUrl": board_staff.presign_deliverable(str(task.get("deliverableKey") or "")),
            },
        )
    if len(rest) == 3 and rest[2] == "cancel" and method == "POST":
        if not board_staff.enabled(settings):
            return _staff_disabled()
        try:
            task = board_staff.cancel_task(table, rest[1], user_sub or "")
        except board_staff.StaffError as exc:
            return _json_response(404 if "not found" in str(exc).lower() else 400, {"message": str(exc)})
        _audit(user_sub, "BOARD_TASK_CANCEL", rest[1], event)
        return _json_response(200, {"task": board_staff.public_task(task)})
    if len(rest) == 3 and rest[2] == "review" and method == "POST":
        if not board_staff.enabled(settings):
            return _staff_disabled()
        body = _parse_json_body(event)
        try:
            task = board_staff.owner_review(
                table,
                settings,
                rest[1],
                str(body.get("verdict") or ""),
                str(body.get("notes") or ""),
                user_sub or "",
            )
        except board_staff.StaffError as exc:
            return _json_response(404 if "not found" in str(exc).lower() else 400, {"message": str(exc)})
        _audit(user_sub, "BOARD_TASK_REVIEW", rest[1], event)
        return _json_response(200, {"task": board_staff.public_task(task)})
    return _json_response(404, {"message": "Not found"})


def _settings_put(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    current = board_store.load_settings(table)
    try:
        merged = validate_settings(_parse_json_body(event), current)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    saved = board_store.save_settings(table, merged)
    _audit(user_sub, "BOARD_SETTINGS_PUT", "settings", event)
    return _json_response(200, {"settings": saved})


def _update_post(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    body = _parse_json_body(event)
    raw = body.get("text")
    if not isinstance(raw, str) or not raw.strip():
        return _json_response(400, {"message": "text is required"})
    if len(raw) > BOARD_MAX_UPDATE_LEN:
        return _json_response(400, {"message": f"text must be at most {BOARD_MAX_UPDATE_LEN} characters"})
    table = board_store.records_table()
    saved = board_store.add_update(table, text=raw.strip(), owner_sub=user_sub)
    _audit(user_sub, "BOARD_UPDATE_POST", saved["updateId"], event)
    return _json_response(201, {"update": saved})


def _repo_snapshot_refresh(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    if not board_github.snapshot_enabled():
        return _json_response(
            400,
            {"message": "GitHub access is not configured (set the BoardGitHubRepo stack parameter)"},
        )
    table = board_store.records_table()
    try:
        snapshot = board_github.fetch_snapshot()
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_repo_snapshot_failed", error=str(exc)[:300])
        return _json_response(502, {"message": str(exc)})
    board_store.save_repo_snapshot(table, snapshot)
    _audit(user_sub, "BOARD_REPO_SNAPSHOT_REFRESH", snapshot.get("repo") or "", event)
    return _json_response(200, {"repoSnapshot": board_github.public_snapshot_meta(snapshot)})
