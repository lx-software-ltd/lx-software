"""Staff manager review."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import board_async
import board_budget
import board_personas
import board_store
from contract_constants import (
    BOARD_CATALOG_EVENT_KINDS,
    BOARD_CHAIR_DEFAULT,
    BOARD_KEY,
    BOARD_STAFF_MAX_REVISIONS,
    BOARD_STAFF_RETENTION_DAYS,
)
from http_common import _log_event


def _review_flag_line(task: dict[str, Any]) -> str:
    flags = [str(f) for f in (task.get("flags") or []) if f]
    if not flags:
        return ""
    extra = ""
    if "salvaged" in flags or "no_evidence" in flags:
        extra = " — verify official_url and address fields before accepting"
    if "brief_mismatch" in flags:
        extra += " — runner brief may not match the GitHub issue title"
    return f"FLAGS: {', '.join(flags)}{extra}\n"

def _reviewer_id(task: dict[str, Any]) -> str:
    if task.get("assigneeKind") == "persona" and task.get("assignee") == BOARD_CHAIR_DEFAULT:
        return "cfo"
    if task.get("assigneeKind") == "persona":
        return BOARD_CHAIR_DEFAULT
    return str(task.get("managerId") or BOARD_CHAIR_DEFAULT)

def _catalog_quality_return(task: dict[str, Any], raw: str) -> str:
    kind = str(((task or {}).get("eventRef") or {}).get("kind") or "")
    if kind not in BOARD_CATALOG_EVENT_KINDS:
        return ""
    try:
        import board_catalog_import

        sheet = board_catalog_import.parse_sheet(raw)
        kept, dropped = board_catalog_import.keep_quality_orgs(sheet)
        issues = board_catalog_import.sheet_quality_issues(
            kept if kept.get("organisations") else sheet
        )
    except Exception as exc:
        return f"Catalog sheet does not parse: {exc}"[:300]
    if kept.get("organisations") and not issues:
        return ""
    if not issues and not dropped:
        return ""
    prefix = "Return — "
    if dropped:
        prefix = f"Return — dropped {len(dropped)} thin org(s); "
    if not issues:
        return prefix + ", ".join(dropped[:6])
    return prefix + "; ".join(issues[:6])

def _review_user_prompt(
    task: dict[str, Any],
    raw: str,
    evidence_lines: list[str],
    *,
    catalog_note: str = "",
) -> str:
    """User message for the manager review call."""
    catalog_line = (catalog_note.strip() + "\n") if catalog_note.strip() else ""
    return (
        f"You are reviewing work assigned to {task.get('assignee')}.\n"
        f"Brief: {task.get('brief')}\n"
        f"Deliverable type: {task.get('deliverableType')}\n"
        f"Confidence: {task.get('confidence')}\n"
        f"{_review_flag_line(task)}"
        f"Evidence:\n" + ("\n".join(evidence_lines) or "(none)") + "\n\n"
        f"{catalog_line}"
        f"Deliverable:\n{raw}\n\n"
        "Books of record: there is no QuickBooks or Xero. This board is Siu Tin Dei "
        "only. For receivables aging, accept a report backed by finance_aging_report "
        "(including zero outstanding or a Data API not-configured error from that tool). "
        "Cash and Siu Tin Dei statement-book flow come from finance_cash_snapshot; AWS "
        "from aws_monthly_cost; Meta from meta_ad_spend or finance_unit_economics. Return "
        "if the deliverable reports the LX Software statement book or other houses as "
        "Siu Tin Dei product P&L. Return if the deliverable still has "
        "[Insert …] placeholders or 0-30/31-60 aging buckets instead of current / D+7 / "
        "D+21 / D+35. Accept a memo that states a figure is unavailable with the tool error. "
        "Do not return asking for accounting software or credentials.\n"
        "If the deliverable claims an action (label, publish, reply, create, send, rebase, merge, sync, implement, fix) "
        "and Evidence is (none), you MUST return.\n"
        "If the deliverable uses Campaign A / Article 1 / screenshotN.png template data, return.\n"
        "Visitor sources and tracking: proof is web_sessions (referrers / sessionSource), "
        "web_conversions (events), and web_gtm_status when GTM is in the brief. Zero "
        "sessions or empty referrers is a valid connected result. A not-configured or "
        "WebError from those tools is a valid unavailable. Do not return asking for GA4 "
        "console access, analytics credentials, or direct access to analytics tools.\n"
        "Evidence tagged (via seat, task id) was gathered by a help subtask; accept it "
        "as if the assignee called those tools.\n"
        "If the brief demands JSON and the Deliverable is not valid JSON, or contains "
        "`!function_call:` text, you MUST return.\n"
        "Catalog sheets: return if any organisation has fewer than two of "
        "opening_hours, (free_or_paid or price_note), and address_en in verified_fields. "
        "Accept only facts read on the official page. When a quality-filter note "
        "gives a kept organisation count, that count is authoritative — do not "
        "return only because it differs from an 'exactly N' line in the brief.\n"
        'Return JSON {"verdict":"accept"|"return","notes":"…"}.'
    )

def run_review(payload: dict[str, Any]) -> None:
    from board_staff import _blob_get, _blob_put, enabled
    if not board_store.event_targets_this_board(payload):
        return
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if not enabled(settings):
        return
    task_id = str(payload.get("taskId") or "")
    task = board_store.get_task(table, task_id)
    if not task or task.get("status") != "review":
        return
    reviewer_id = _reviewer_id(task)
    overrides = board_store.load_member_overrides(table)
    charter = board_store.load_charter(table)
    default = board_personas.persona_default(reviewer_id) or {}
    profile = board_personas.effective_profile(default, overrides.get(reviewer_id))
    raw = _blob_get(str(task.get("deliverableKey") or "")).decode("utf-8", errors="replace")
    if len(raw) > 12000:
        raw = raw[:12000] + "\n[… truncated]"
    catalog_note = ""
    try:
        import board_catalog_import

        if str(((task or {}).get("eventRef") or {}).get("kind") or "") in BOARD_CATALOG_EVENT_KINDS:
            sheet = board_catalog_import.parse_sheet(raw)
            kept, dropped = board_catalog_import.keep_quality_orgs(sheet)
            kept_orgs = kept.get("organisations") if isinstance(kept.get("organisations"), list) else []
            catalog_note = (
                f"Quality filter kept {len(kept_orgs)} organisation(s). "
                "That count is authoritative. Do not return because it differs "
                "from an 'exactly N' line in the brief."
            )
            if dropped:
                catalog_note += " Dropped as thin: " + ", ".join(str(name) for name in dropped[:6]) + "."
            if dropped and kept_orgs:
                raw = json.dumps(kept, ensure_ascii=False, indent=2)
                key = str(task.get("deliverableKey") or "")
                if key:
                    _blob_put(key, raw.encode("utf-8"))
                task["openQuestions"] = [
                    *(task.get("openQuestions") or []),
                    *(f"dropped thin org: {name}" for name in dropped[:6]),
                ][:20]
                board_store.put_task(table, task)
    except Exception as exc:
        _log_event("warning", tag="board_staff_catalog_keep_failed", error=str(exc)[:200])
    quality = _catalog_quality_return(task, raw)
    if quality:
        apply_review(table, settings, task, verdict="return", notes=quality, by="manager")
        return
    cited = set(task.get("evidence") or [])
    evidence_lines: list[str] = []
    for call in board_store.list_tool_calls_for_task(table, task_id):
        if str(call.get("callId")) in cited:
            evidence_lines.append(f"- {call.get('op')}: {call.get('summary')}")
    for hid in task.get("helpTaskIds") or []:
        child = board_store.get_task(table, str(hid))
        via = str((child or {}).get("assignee") or "helper")
        for call in board_store.list_tool_calls_for_task(table, str(hid)):
            if str(call.get("callId")) in cited:
                evidence_lines.append(
                    f"- {call.get('op')} (via {via}, task {hid}): {call.get('summary')}"
                )
    prompt = _review_user_prompt(task, raw, evidence_lines, catalog_note=catalog_note)
    system = board_personas.render_system_prompt(profile, charter)
    model = board_budget.model_for("standup", settings)
    completion = board_budget.board_completion(
        table=table,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        model=model,
        timeout=60,
        json_mode=True,
        temperature=0.2,
        max_tokens=800,
        tag="board_staff_review",
    )
    board_store.add_staff_usage_day(table, reviewer_id, {**(completion.usage or {}), "calls": 1})
    verdict = "return"
    notes = ""
    parsed_ok = False
    try:
        parsed = json.loads(completion.text or "")
        raw_verdict = str(parsed.get("verdict") or "").lower()
        if raw_verdict in ("accept", "return"):
            verdict = raw_verdict
            parsed_ok = True
        notes = str(parsed.get("notes") or "")[:2000]
    except json.JSONDecodeError:
        notes = (completion.text or "")[:2000]
    if not parsed_ok:
        _log_event("warning", tag="board_staff_review_unparsed", taskId=task_id)
        verdict = "return"
    apply_review(table, settings, task, verdict=verdict, notes=notes, by="manager")

def apply_review(
    table: Any,
    settings: dict[str, Any],
    task: dict[str, Any],
    *,
    verdict: str,
    notes: str,
    by: str,
) -> dict[str, Any]:
    from board_staff import _align_step_claim, _append_scratchpad, run_step
    now = board_store.now_iso()
    seq = int(task.get("reviews") or 0) + 1
    review = {"seq": seq, "verdict": verdict, "notes": notes, "at": now, "by": by}
    board_store.put_task_review(table, str(task["taskId"]), review)
    task["reviews"] = seq
    task["lastReview"] = {"verdict": verdict, "notes": notes, "at": now, "by": by}
    task["updatedAt"] = now
    if verdict == "accept":
        is_owner_accept = str(by or "").startswith("owner")
        if not is_owner_accept and _should_hold_unverified_accept(table, task):
            task["status"] = "needs_owner"
            task["finishedAt"] = None
            board_store.put_task(table, task)
            _note_parent_if_child_needs_owner(table, task)
            return task
        task["acceptedBy"] = by
        return _accept_task(table, task, now, bypass_unverified=is_owner_accept)
    revisions = int(task.get("revisions") or 0)
    is_owner = str(by or "").startswith("owner")
    is_final = revisions >= BOARD_STAFF_MAX_REVISIONS
    if is_owner or is_final:
        try:
            import board_lessons

            board_lessons.create_from_return(table, task)
        except Exception as exc:
            _log_event("warning", tag="board_lesson_from_return_failed", error=str(exc)[:200])
    if revisions < BOARD_STAFF_MAX_REVISIONS:
        _append_scratchpad(task, f"MANAGER NOTES: {notes}")
        task["revisions"] = revisions + 1
        task["status"] = "running"
        task["idleSteps"] = 0
        task["failureReason"] = ""
        _align_step_claim(task)
        board_store.put_task(table, task)
        board_async.invoke_async(
            {
                "internal": "board_staff_step",
                "boardKey": BOARD_KEY,
                "taskId": task["taskId"],
                "step": int(task.get("step") or 0) + 1,
            },
            fallback=run_step,
        )
        return task
    task["status"] = "needs_owner"
    task["finishedAt"] = None
    board_store.put_task(table, task)
    _note_parent_if_child_needs_owner(table, task)
    return task

def _task_attempted_required_tools(table: Any, task: dict[str, Any]) -> bool:
    from board_staff import _IDLE_TOOL_OPS, _brief_required_evidence_tools
    """True when the seat called every tool the brief names, even if those calls errored."""
    needed = _brief_required_evidence_tools(str(task.get("brief") or ""))
    if not needed:
        return False
    task_id = str(task.get("taskId") or "")
    if not task_id:
        return False
    ops: set[str] = set()
    for call in board_store.list_tool_calls_for_task(table, task_id):
        op = str(call.get("op") or "")
        if op and op not in _IDLE_TOOL_OPS:
            ops.add(op)
    return all(tool in ops for tool in needed)

def note_parent_if_child_needs_owner(table: Any, task: dict[str, Any]) -> None:
    """Public wrapper so catalog import can park a help child without calling a private."""
    _note_parent_if_child_needs_owner(table, task)

def _note_parent_if_child_needs_owner(table: Any, task: dict[str, Any]) -> None:
    from board_staff import _note_parent_child_waiting
    if not task.get("parentTaskId") or task.get("status") != "needs_owner":
        return
    notes = str((task.get("lastReview") or {}).get("notes") or "").strip()
    extra = f" Last review: {notes[:200]}" if notes else ""
    _note_parent_child_waiting(
        table,
        task,
        f"HELP: task {task.get('taskId')} is waiting for founder review.{extra} "
        "Stay parked until the founder accepts or cancels that help task.",
        reason=f"help task {task.get('taskId')} needs founder review",
    )

def _is_review_headline_duty(task: dict[str, Any]) -> bool:
    ref = task.get("eventRef") or {}
    return ref.get("kind") == "duty" and str(ref.get("id") or "").startswith("review-headline:")

def _should_hold_unverified_accept(table: Any, task: dict[str, Any]) -> bool:
    from board_staff import _CLAIMED_ACTION_RE, _EVIDENCE_REQUIRED_ORIGINS
    flags = {str(f) for f in (task.get("flags") or [])}
    if "no_evidence" not in flags and "salvaged" not in flags:
        return False
    if _is_review_headline_duty(task):
        return False
    if str((task.get("eventRef") or {}).get("kind") or "") in BOARD_CATALOG_EVENT_KINDS:
        return False
    if "salvaged" not in flags and _task_attempted_required_tools(table, task):
        return False
    if str(task.get("origin") or "") in _EVIDENCE_REQUIRED_ORIGINS:
        return True
    brief = str(task.get("brief") or "")
    return bool(_CLAIMED_ACTION_RE.search(brief))

def _task_has_open_approvals(table: Any, task: dict[str, Any]) -> bool:
    task_id = str(task.get("taskId") or "")
    if not task_id:
        return False
    blocked = [str(x) for x in (task.get("blockedOn") or []) if x]
    if blocked:
        return True
    for approval in board_store.list_approvals(table):
        if str(approval.get("status") or "") != "pending":
            continue
        ctx = approval.get("context") or {}
        if str(ctx.get("taskId") or "") == task_id:
            return True
    return False

def _should_close_linked_action(table: Any, task: dict[str, Any]) -> bool:
    flags = {str(f) for f in (task.get("flags") or [])}
    if flags & {"no_evidence", "salvaged", "staging_behind", "sync_scheduled"}:
        return False
    if _task_has_open_approvals(table, task):
        return False
    return True

def _mark_delivered(table: Any, task: dict[str, Any], now: str) -> dict[str, Any]:
    from board_staff import _resume_parent_after_help
    """Persist a delivered task, TTL, linked-action close, and parent/duty hooks."""
    task["status"] = "delivered"
    task["finishedAt"] = now
    task["updatedAt"] = now
    task["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    action_id = task.get("actionId")
    dtype = str(task.get("deliverableType") or "")
    if action_id and dtype in ("markdown", "csv", "json", "issues", "pr") and _should_close_linked_action(table, task):
        action = board_store.get_action(table, str(action_id))
        if action:
            action["note"] = (
                (str(action.get("note") or "") + "\n" if action.get("note") else "")
                + f"Closed by staff task {task['taskId']}: {task.get('summary') or ''}"
            )[:2000]
            action["status"] = "done"
            action["closedBy"] = f"staff:{task['taskId']}"
            action["updatedAt"] = now
            board_store.put_action(table, action)
    board_store.put_task(table, task)
    if task.get("parentTaskId"):
        _resume_parent_after_help(
            table,
            board_store.load_settings(table),
            str(task.get("parentTaskId") or ""),
            "help delivered",
            child=task,
            success=True,
        )
        return task
    ref = task.get("eventRef") or {}
    if ref.get("kind") == "duty" and str(ref.get("id") or "").startswith("market-brief:"):
        try:
            import board_intel

            board_intel.on_brief_delivered(table, task)
        except Exception as exc:
            _log_event("warning", tag="board_intel_brief_deliver_failed", error=str(exc)[:200])
    if ref.get("kind") == "duty" and str(ref.get("id") or "").startswith("content-plan:"):
        try:
            import board_content

            board_content.on_plan_delivered(table, board_store.load_settings(table), task)
        except Exception as exc:
            _log_event("warning", tag="board_content_plan_deliver_failed", error=str(exc)[:200])
    if ref.get("kind") == "duty" and str(ref.get("id") or "").startswith("content-readout:"):
        try:
            import board_content

            board_content.on_readout_delivered(table, board_store.load_settings(table), task)
        except Exception as exc:
            _log_event("warning", tag="board_content_readout_deliver_failed", error=str(exc)[:200])
    if ref.get("kind") == "code-review":
        try:
            import board_code

            board_code.on_review_delivered(table, board_store.load_settings(table), task)
        except Exception as exc:
            _log_event("warning", tag="board_code_review_deliver_failed", error=str(exc)[:200])
    return task

def _accept_task(table: Any, task: dict[str, Any], now: str, *, bypass_unverified: bool = False) -> dict[str, Any]:
    from board_staff import _blob_get
    last = task.get("lastReview") or {}
    if last.get("verdict") and last.get("verdict") != "accept":
        task["status"] = "needs_owner"
        task["finishedAt"] = None
        task["updatedAt"] = now
        board_store.put_task(table, task)
        _note_parent_if_child_needs_owner(table, task)
        return task
    ref = task.get("eventRef") or {}
    if ref.get("kind") == "ops" and str(ref.get("id") or "") == "rebase-staging":
        import board_code

        return board_code.accept_sync_staging_task(
            table, task, now, bypass_unverified=bypass_unverified
        )
    if not bypass_unverified and _should_hold_unverified_accept(table, task):
        task["status"] = "needs_owner"
        task["finishedAt"] = None
        task["updatedAt"] = now
        board_store.put_task(table, task)
        _note_parent_if_child_needs_owner(table, task)
        return task
    if ref.get("kind") in BOARD_CATALOG_EVENT_KINDS:
        import board_catalog_import

        try:
            accepted = board_catalog_import.accept_catalog_task(table, task, now)
            try:
                import board_catalog

                settings = board_store.load_settings(table)
                sheet = board_catalog_import.parse_sheet(
                    _blob_get(str(task.get("deliverableKey") or "")).decode("utf-8", errors="replace")
                )
                board_catalog.handoff_commercial_providers(table, settings, accepted, sheet)
            except Exception as exc:
                _log_event("info", tag="board_catalog_handoff_failed", error=str(exc)[:200])
            return accepted
        except Exception as exc:
            _log_event("warning", tag="board_catalog_import_accept_failed", error=str(exc)[:200])
            task["importPreview"] = {"ok": False, "error": str(exc)[:300], "taskId": task.get("taskId")}
            return board_catalog_import._set_awaiting(table, task, now, phase="pending")
    return _mark_delivered(table, task, now)

def owner_review(table: Any, settings: dict[str, Any], task_id: str, verdict: str, notes: str, by_sub: str) -> dict[str, Any]:
    from board_staff import StaffError
    task = board_store.get_task(table, task_id)
    if not task:
        raise StaffError("Task not found")
    if verdict not in ("accept", "return"):
        raise StaffError("verdict must be accept or return")
    return apply_review(table, settings, task, verdict=verdict, notes=notes, by=f"owner:{by_sub}")
