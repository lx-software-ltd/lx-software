"""Staff tick stages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_async
import board_store
from contract_constants import (
    BOARD_KEY,
    BOARD_STAFF_STEP_MAX_SECONDS,
    BOARD_STAFF_TASK_STUCK_SECONDS,
)
from http_common import _log_event, _utc_iso_z


def _run_tick_stage(tag: str, stage: Any, *, abort: bool) -> None:
    """Run one staff-tick stage.

    Safety stages (breaker evaluation, due holds) log and re-raise so a
    failed policy check cannot skip the rest of the tick. Other stages log
    and continue.
    """
    try:
        stage()
    except Exception as exc:
        _log_event("error" if abort else "warning", tag=tag, error=str(exc)[:300])
        if abort:
            raise

def _continue_tick_stages(table: Any, settings: dict[str, Any]) -> list[tuple[str, Any]]:
    """Tick stages that log and continue. Order matches the previous inline chain."""

    def _catalog_import() -> None:
        import board_catalog_import

        board_catalog_import.handle_tick(table, settings)

    def _catalog_bulk() -> None:
        import board_catalog_bulk

        board_catalog_bulk.maybe_queue_auto_imports(table, settings)

    def _approvals() -> None:
        import board_tools as _board_tools

        _board_tools.expire_stale_approvals(table, settings)

    def _duties() -> None:
        import board_duties

        board_duties.run_due(table, settings)

    def _code() -> None:
        import board_code

        board_code.handle_tick(table, settings)

    def _meeting() -> None:
        import board_meeting

        board_meeting.maybe_retry_failed_schedule(table, settings)

    def _supersede() -> None:
        import board_staff

        board_staff.supersede_stale_failed_duties(table)

    def _help_expiry() -> None:
        import board_staff

        board_staff.expire_waiting_help(table, settings)

    return [
        ("board_catalog_import_tick_failed", _catalog_import),
        ("board_catalog_auto_bulk_failed", _catalog_bulk),
        ("board_approval_expiry_failed", _approvals),
        ("board_duties_tick_failed", _duties),
        ("board_code_tick_failed", _code),
        ("board_meeting_retry_failed", _meeting),
        ("board_staff_supersede_failed", _supersede),
        ("board_staff_help_expiry_failed", _help_expiry),
    ]

def handle_tick(event: dict[str, Any]) -> dict[str, Any]:
    from board_staff import (
        _finish_incomplete,
        _note_parent_if_child_needs_owner,
        _release_step_claim,
        drain_queue,
        enabled,
        run_review,
        run_step,
    )
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    table = board_store.records_table()
    try:
        settings = board_store.ensure_autonomy_defaults(table)
    except Exception as exc:
        _log_event("warning", tag="board_autonomy_defaults_failed", error=str(exc)[:200])
        settings = board_store.load_settings(table)
    try:
        import board_holds

        board_holds.expire_stale(table, settings, board_store.now_iso())
    except Exception as exc:
        _log_event("warning", tag="board_holds_expire_failed", error=str(exc)[:300])
    if not enabled(settings):
        return {"ok": True, "skipped": "disabled"}

    def _evaluate_breakers() -> None:
        import board_breakers

        board_breakers.evaluate(table, settings)

    _run_tick_stage("board_breakers_tick_failed", _evaluate_breakers, abort=True)
    settings = board_store.load_settings(table)
    if not enabled(settings):
        return {"ok": True, "skipped": "disabled", "breaker": "budget"}

    def _execute_due_holds() -> None:
        import board_holds

        board_holds.execute_due(table, settings, board_store.now_iso())

    _run_tick_stage("board_holds_tick_failed", _execute_due_holds, abort=True)
    TICK_STAGES = _continue_tick_stages(table, settings)
    for tag, stage in TICK_STAGES:
        _run_tick_stage(tag, stage, abort=False)
    started = drain_queue(table, settings)
    stuck_cut = datetime.now(timezone.utc) - timedelta(seconds=BOARD_STAFF_TASK_STUCK_SECONDS)
    cut_iso = _utc_iso_z(stuck_cut)
    # AdminApiFn timeout is 300 s; only re-invoke after that plus a margin so
    # a live hung step cannot race a replacement invocation.
    claim_stale_cut = datetime.now(timezone.utc) - timedelta(seconds=BOARD_STAFF_STEP_MAX_SECONDS + 180)
    claim_stale_iso = _utc_iso_z(claim_stale_cut)
    for task in board_store.list_tasks(table, "running"):
        claimed_at = str(task.get("stepClaimedAt") or "")
        updated = str(task.get("updatedAt") or "")
        claim_is_stale = bool(claimed_at and claimed_at < claim_stale_iso)
        # Drain promotes queued→running without stepClaimedAt. If the Event
        # invoke never ran, retry once the same way as a hung claim.
        never_started = (not claimed_at) and int(task.get("step") or 0) == 0 and updated < claim_stale_iso
        if (claim_is_stale or never_started) and not task.get("stuckRetried"):
            wanted = int(task.get("step") or 0) + 1
            _release_step_claim(table, task, wanted)
            latest = board_store.get_task(table, str(task.get("taskId") or "")) or task
            latest["stuckRetried"] = True
            latest["updatedAt"] = board_store.now_iso()
            board_store.put_task(table, latest)
            try:
                board_async.invoke_async(
                    {
                        "internal": "board_staff_step",
                        "boardKey": BOARD_KEY,
                        "taskId": latest.get("taskId"),
                        "step": wanted,
                    },
                    fallback=run_step,
                )
            except Exception as exc:
                _log_event(
                    "error",
                    tag="board_staff_stuck_reinvoke_failed",
                    taskId=latest.get("taskId"),
                    error=str(exc)[:300],
                )
        elif (claim_is_stale or never_started or updated < claim_stale_iso) and task.get("stuckRetried"):
            _finish_incomplete(table, task, "stuck")
        elif updated < cut_iso:
            _finish_incomplete(table, task, "stuck")
    for task in board_store.list_tasks(table, "review"):
        if str(task.get("updatedAt") or "") < cut_iso:
            if not task.get("reviewRetried"):
                task["reviewRetried"] = True
                task["updatedAt"] = board_store.now_iso()
                board_store.put_task(table, task)
                board_async.invoke_async(
                    {"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task["taskId"]},
                    fallback=run_review,
                )
            else:
                task["status"] = "needs_owner"
                task["updatedAt"] = board_store.now_iso()
                board_store.put_task(table, task)
                _note_parent_if_child_needs_owner(table, task)
    return {"ok": True, "started": started}
