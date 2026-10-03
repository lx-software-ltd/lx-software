"""Executive Board: tools that members call while chatting or meeting.

Design (see docs/architecture/executive-board.md §5 Tools):

- A **registry** of operations, each belonging to a tool (``github``,
  ``board``, ``mail``, ``research``, ``aws``, ``security``, ``product``,
  ``catalog``, ``meta``, ``finance``, ``stores``, ``staff``, ``intel``,
  ``outreach``, ``content``, ``code``, ``newsletter``)
  and being either a *read* or a *write*.
- A per-tool, per-member **level** (``off`` < ``read`` < ``propose`` <
  ``act``), capped by a global mode. Read operations are offered at
  ``read`` and above; write operations at ``propose`` and above. At
  ``propose`` a write is recorded as a pending **approval** for the owner
  instead of executing; at ``act`` it executes immediately.
- The **loop**: model → tool calls → results → model, bounded by rounds,
  calls, and wall-clock seconds. Every call lands in the audit log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

import board_aws
import board_budget
import board_catalog_import
import board_deadline
import board_github
import board_mail
import board_meta
import board_personas
import board_product
import board_receivables
import board_research
import board_security
import board_store
import board_stores
import board_web
from board_tools_core import (
    GLOBAL_MODE_CAP,
    LEVEL_RANK,
    REASON_PARAM,
    TOOL_LABELS,
    InvalidArgumentsError,
    ToolContext,
    ToolLoopResult,
    ToolOp,
    ToolOutcome,
    ToolPermissionError,
    allows,
    configured_level,
    effective_level,
    effective_matrix,
    env_disabled,
    global_cap,
    tools_enabled,
)
from contract_constants import (
    BOARD_MAX_PENDING_APPROVALS,
    BOARD_MAX_TOOL_CALLS_PER_TURN,
    BOARD_MAX_TOOL_ROUNDS_PER_TURN,
    BOARD_STAFF_APPROVAL_EXPIRY_HOURS,
    BOARD_TOOL_CALL_TIMEOUT_SECONDS,
    BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
    BOARD_TOOL_DEFINITIONS,
    BOARD_TOOL_RESULT_MAX_CHARS,
)
from http_common import _log_event
from openrouter_client import ChatCompletion, ToolCall, add_usage

__all__ = [
    "GLOBAL_MODE_CAP",
    "LEVEL_RANK",
    "TOOL_LABELS",
    "InvalidArgumentsError",
    "REASON_PARAM",
    "ToolContext",
    "ToolLoopResult",
    "ToolOp",
    "ToolOutcome",
    "ToolPermissionError",
    "allows",
    "configured_level",
    "effective_level",
    "effective_matrix",
    "env_disabled",
    "global_cap",
    "tools_enabled",
    "REGISTRY",
    "build_registry",
    "execute_call",
    "run_tool_loop",
    "BOARD_TOOL_CALL_TIMEOUT_SECONDS",
    "BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS",
]

MAX_ARGUMENT_CHARS = 8000
# task_finish deliverables (content plans, catalog sheets) routinely exceed 8k.
MAX_ARGUMENT_CHARS_TASK_FINISH = 40000
MAX_RESULT_PREVIEW = 400
# Wall-clock budget of one persona turn (chat: chatToolLoopMaxSeconds, meeting:
# meetingToolLoopMaxSeconds) is shared by the model calls and the tool ops:
#   round N model call  ≤ min(openrouter timeout, seconds left)
#   each op             ≤ min(op timeout, seconds left), never below the floor
#   final answer call   ≤ min(openrouter timeout, seconds left), at least the final floor
# so a turn ends within about max(max_seconds + final floor, openrouter timeout):
# chat 120 + 45 = 165 s (< chatPollDeadlineMs 270 s, < the 300 s Lambda),
# meeting 60 + 45 = 105 s per member (members run in parallel per phase).
MODEL_CALL_TIMEOUT_FLOOR_SECONDS = 15
FINAL_CALL_TIMEOUT_FLOOR_SECONDS = 45
OP_TIMEOUT_FLOOR_SECONDS = 2


def completion_timeout(
    requested: int,
    left: float,
    floor: int,
    *,
    allow_floor_overrun: bool = False,
) -> int:
    """Clamp an OpenRouter timeout to the remaining tool-loop budget.

    When enough time remains, keep the usual floor so a short leftover does
    not become a 1-second call. When leftover is positive but below the
    floor, use the leftover instead of inflating it past the deadline.
    ``allow_floor_overrun`` is for the final answer call, which may run
    briefly past the loop budget the same way it does today.
    """
    remaining = int(left)
    if remaining >= floor:
        return max(floor, min(requested, remaining))
    if remaining > 0:
        return min(max(1, requested), remaining)
    if allow_floor_overrun:
        return max(1, floor)
    return 0


def build_registry() -> dict[str, ToolOp]:
    """Assemble the operation registry from per-family modules."""
    import board_tools_aws
    import board_tools_board
    import board_tools_catalog
    import board_tools_code
    import board_tools_content
    import board_tools_finance
    import board_tools_github
    import board_tools_intel
    import board_tools_mail
    import board_tools_meta
    import board_tools_newsletter
    import board_tools_outreach
    import board_tools_product
    import board_tools_research
    import board_tools_security
    import board_tools_staff
    import board_tools_stores
    import board_tools_task
    import board_tools_web

    families = (
        board_tools_github,
        board_tools_board,
        board_tools_mail,
        board_tools_research,
        board_tools_aws,
        board_tools_security,
        board_tools_product,
        board_tools_catalog,
        board_tools_meta,
        board_tools_finance,
        board_tools_stores,
        board_tools_web,
        board_tools_intel,
        board_tools_outreach,
        board_tools_content,
        board_tools_newsletter,
        board_tools_code,
        board_tools_staff,
        board_tools_task,
    )
    ops: list[ToolOp] = []
    for family in families:
        ops.extend(family.ops())
    return {op.name: op for op in ops}














# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------















# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------











# --- board operations -------------------------------------------------------































































































































REGISTRY: dict[str, ToolOp] = build_registry()


def public_registry() -> list[dict[str, Any]]:
    """Tool and operation descriptions for the SPA."""
    out = []
    for tool in BOARD_TOOL_DEFINITIONS:
        tool_id = str(tool["id"])
        out.append(
            {
                "id": tool_id,
                "label": tool.get("label"),
                "description": tool.get("description"),
                "maxLevel": tool.get("maxLevel"),
                "operations": [
                    {
                        "name": op.name,
                        "kind": op.kind,
                        "description": op.description,
                        "contexts": list(op.contexts),
                    }
                    for op in REGISTRY.values()
                    if op.tool_id == tool_id
                ],
            }
        )
    return out


def task_ops_level(context: str) -> str:
    """``task_note`` / ``task_finish`` are act-only while running a task.

    They are not a matrix tool (no seat or persona has ``tools.task``), so
    ``effective_level`` would return ``off`` and refuse every finish.
    """
    return "act" if context == "task" else "off"


def available_ops(
    settings: dict[str, Any],
    persona_id: str,
    *,
    context: str,
    seat_id: str = "",
    seats_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[ToolOp, str]]:
    """Operations this member may call now, each with its effective level."""
    out: list[tuple[ToolOp, str]] = []
    tools_on = tools_enabled(settings)
    for op in REGISTRY.values():
        if context not in op.contexts:
            continue
        if op.tool_id == "task":
            # Staff lifecycle ops are not in the owner matrix; they are only
            # legal on the current task. execute_call uses the same rule.
            # Offer them even when the tools kill-switch is off so a duty can
            # still finish (the prompt tells the seat to call them).
            level = task_ops_level(context)
        elif not tools_on:
            continue
        elif op.tool_id in ("staff", "intel", "outreach", "content", "newsletter", "code"):
            import board_staff

            if not board_staff.enabled(settings):
                continue
            if seat_id:
                level = effective_level(settings, op.tool_id, persona_id, seat_id=seat_id, seats_by_id=seats_by_id)
            else:
                level = effective_level(settings, op.tool_id, persona_id)
        elif seat_id:
            level = effective_level(settings, op.tool_id, persona_id, seat_id=seat_id, seats_by_id=seats_by_id)
        else:
            level = effective_level(settings, op.tool_id, persona_id)
        if allows(level, op.min_level) and _op_is_configured(op):
            out.append((op, level))
    # Lifecycle ops are registered last; models with long tool lists often miss
    # them and write "I cannot call task_note / task_finish" in prose instead.
    out.sort(key=lambda pair: 0 if pair[0].tool_id == "task" else 1)
    return out


def _op_is_configured(op: ToolOp) -> bool:
    """Hide writes whose backing credentials are missing so seats do not propose junk.

    Reads stay visible so duty briefs can still call them and get a structured
    'not configured' result (those errors are ignored by tool breakers).
    """
    if not op.is_write:
        return True
    if op.tool_id == "meta":
        name = op.name
        if "ig_" in name or name.endswith("_ig_insights"):
            return bool(board_meta.ig_user_id())
        if "ad_" in name or "boost" in name:
            return bool(board_meta.ad_account_id())
        if any(token in name for token in ("page_", "comment", "dm", "whatsapp", "post")):
            return bool(board_meta.page_id() or board_meta.wa_phone_id())
        return board_meta.configured()
    if op.tool_id == "web":
        return board_web.configured()
    if op.tool_id == "stores":
        return board_stores.configured()
    if op.tool_id == "catalog":
        return board_catalog_import.import_enabled() and board_catalog_import.configured()
    return True


def unconfigured_notes() -> list[str]:
    """Owner-facing list of integrations the seat should treat as unavailable."""
    notes: list[str] = []
    if not board_meta.page_id():
        notes.append("meta page (META_PAGE_ID)")
    if not board_meta.ig_user_id():
        notes.append("instagram (META_IG_USER_ID)")
    if not board_meta.ad_account_id():
        notes.append("meta ads (META_AD_ACCOUNT_ID)")
    if not board_web.configured():
        notes.append("GA4 / GTM")
    if not board_stores.configured():
        notes.append("app stores")
    return notes


def tools_preamble(ops: list[tuple[ToolOp, str]]) -> str:
    """System text explaining what the offered tools do and do not do."""
    if not ops:
        return ""
    lines = [
        "TOOLS: you can call the functions offered to you. Those names are the complete list; "
        "never invent others (there is no read_github, read_npm or read_cve). Use read tools to "
        "check live facts before asserting them; cite what you found. Never call the same function "
        "twice with the same arguments, and make at most "
        f"{BOARD_MAX_TOOL_CALLS_PER_TURN} calls per reply. If a fact cannot be verified with the "
        "offered functions, say so and finish with what you have.",
    ]
    if any(op.tool_id == "task" for op, _lvl in ops):
        if any(op.name == "task_request_help" for op, _ in ops):
            lines.append(
                "TASK CONTROL: task_note, task_finish and task_request_help are in this turn's "
                "function list. You must invoke them as tool calls. Do not write that you cannot "
                "call them. Call task_note to record progress, or task_finish with the deliverable "
                "when done (task_note call ids are not evidence). If the brief needs a tool you were not offered, call task_request_help "
                "once instead of finishing unable to verify. That is how the task completes; a "
                "prose report is not a finish."
            )
        else:
            lines.append(
                "TASK CONTROL: task_note and task_finish are in this turn's function list. "
                "You must invoke them as tool calls. Do not write that you cannot call them. "
                "Call task_note to record progress, or task_finish with the deliverable when done "
                "(task_note call ids are not evidence). "
                "That is how the task completes; a prose report is not a finish."
            )
    proposes = sorted({TOOL_LABELS.get(op.tool_id, op.tool_id) for op, lvl in ops if op.is_write and lvl == "propose"})
    acts = sorted(
        {
            TOOL_LABELS.get(op.tool_id, op.tool_id)
            for op, lvl in ops
            if op.is_write and lvl == "act" and op.tool_id != "task"
        }
    )
    missing = unconfigured_notes()
    if missing:
        lines.append(
            "Not configured (do not invent calls or loop asking for them): "
            + ", ".join(missing)
            + ". Write 'unavailable' and finish."
        )
    if proposes:
        lines.append(
            f"Write operations on {', '.join(proposes)} only RECORD A PROPOSAL for the founder to approve; "
            "nothing happens until they approve it. After you propose, stop and wait — do not propose again. "
            "Say 'I have proposed ...' and never claim it is done."
        )
    if acts:
        lines.append(
            f"Write operations on {', '.join(acts)} execute immediately and are logged. Use them only when "
            "the founder asked for it or your mandate clearly covers it; explain what you did."
        )
        lines.append(
            "A result status of 'held' means the write is scheduled and will happen automatically unless the "
            "founder vetoes it. Say 'I have scheduled …' and never claim it is already done."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execution and audit
# ---------------------------------------------------------------------------

def _truncate_json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 60].rstrip() + f" ... [truncated, {len(text)} chars total]"


def _argument_char_limit(op_name: str = "") -> int:
    if op_name == "task_finish":
        return MAX_ARGUMENT_CHARS_TASK_FINISH
    return MAX_ARGUMENT_CHARS


def _clean_arguments(args: Any, *, limit: int | None = None) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    text = json.dumps(args, default=str)
    cap = MAX_ARGUMENT_CHARS if limit is None else int(limit)
    if len(text) > cap:
        raise InvalidArgumentsError(f"arguments too large (over {cap} characters)")
    return args


def _check_value(key: str, value: Any, spec: dict[str, Any]) -> tuple[Any, str]:
    """Return ``(normalised_value, problem)`` for one schema property."""
    kind = spec.get("type")
    if kind == "string":
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            return None, f"'{key}' must be a string"
        max_len = spec.get("maxLength")
        if max_len and len(value) > int(max_len):
            return None, f"'{key}' is longer than {max_len} characters"
        enum = spec.get("enum")
        if enum and value not in enum:
            return None, f"'{key}' must be one of: {', '.join(str(e) for e in enum)}"
        return value, ""
    if kind in ("integer", "number"):
        if isinstance(value, bool):
            return None, f"'{key}' must be a number"
        if isinstance(value, str):
            try:
                value = int(value.strip()) if kind == "integer" else float(value.strip())
            except ValueError:
                return None, f"'{key}' must be a number"
        if isinstance(value, Decimal):
            value = int(value) if value == value.to_integral_value() else float(value)
        if not isinstance(value, (int, float)):
            return None, f"'{key}' must be a number"
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None, f"'{key}' must be a finite number"
        if kind == "integer" and isinstance(value, float):
            if not value.is_integer():
                return None, f"'{key}' must be a whole number"
            value = int(value)
        minimum = spec.get("minimum")
        if minimum is not None and value < minimum:
            return None, f"'{key}' must be at least {minimum}"
        maximum = spec.get("maximum")
        if maximum is not None and value > maximum:
            return None, f"'{key}' must be at most {maximum}"
        return value, ""
    if kind == "boolean":
        if isinstance(value, bool):
            return value, ""
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true", ""
        return None, f"'{key}' must be true or false"
    if kind == "array":
        if not isinstance(value, list):
            return None, f"'{key}' must be a list"
        max_items = spec.get("maxItems")
        if max_items and len(value) > int(max_items):
            return None, f"'{key}' has more than {max_items} items"
        item_spec = spec.get("items") if isinstance(spec.get("items"), dict) else {}
        cleaned: list[Any] = []
        for index, item in enumerate(value):
            if item_spec.get("type"):
                item, problem = _check_value(f"{key}[{index}]", item, item_spec)
                if problem:
                    return None, problem
            cleaned.append(item)
        return cleaned, ""
    if kind == "object":
        if not isinstance(value, dict):
            return None, f"'{key}' must be an object"
        nested, problems = _validate_against(value, spec, prefix=f"{key}.")
        return nested, problems[0] if problems else ""
    return value, ""


def _validate_against(args: dict[str, Any], schema: dict[str, Any], *, prefix: str = "") -> tuple[dict[str, Any], list[str]]:
    props: dict[str, Any] = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    problems: list[str] = []
    out: dict[str, Any] = {}
    for key in schema.get("required") or []:
        if args.get(key) in (None, "", [], {}):
            problems.append(f"'{prefix}{key}' is required")
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            if schema.get("additionalProperties") is False:
                problems.append(f"unknown argument '{prefix}{key}'")
            else:
                out[key] = value
            continue
        if value is None:
            continue
        cleaned, problem = _check_value(f"{prefix}{key}", value, spec)
        if problem:
            problems.append(problem)
        else:
            out[key] = cleaned
    return out, problems


def validate_arguments(op: ToolOp, args: dict[str, Any]) -> dict[str, Any]:
    """Check ``args`` against the schema the model was shown and return a normalised copy.

    Numeric strings are coerced, ``null`` values dropped; unknown keys, wrong
    types, enum / length / range violations raise :class:`InvalidArgumentsError`
    so neither a persona nor an owner override can smuggle an undeclared or
    oversized value into an op.
    """
    cleaned, problems = _validate_against(args, op.parameters or {})
    if problems:
        raise InvalidArgumentsError("Invalid arguments: " + "; ".join(problems[:6]))
    return cleaned


_SENSITIVE_ARG_KEYS = frozenset({"to", "cc", "recipientId", "contact", "providerEmail", "providerPhone", "parentContact"})


def mask_arguments(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Alias e-mail addresses and phone numbers inside ``arguments`` for the audit log.

    Tool-call rows are browsable in the SPA activity feed and are kept far longer
    than the approval they came from, so they never store raw contact details.
    Approvals keep the real arguments because they are executed from them and
    already carry the un-masked owner preview by design.
    """
    try:
        pseud = board_mail.pseudonymizer(ctx.table)
    except Exception:  # pragma: no cover - masking is best effort, never blocks a call
        return arguments

    def _walk(value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            if key in _SENSITIVE_ARG_KEYS and "@" in value:
                return pseud.alias_for_address(value)
            return pseud.mask_text(value)
        if isinstance(value, list):
            return [_walk(v, key) for v in value]
        if isinstance(value, dict):
            return {k: _walk(v, str(k)) for k, v in value.items()}
        return value

    masked = _walk(arguments)
    try:
        pseud.save()
    except Exception as exc:  # pragma: no cover - alias map save is retried elsewhere
        _log_event("warning", tag="board_tool_mask_save_failed", error=str(exc)[:200])
    return masked


def _invoke_op(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> dict[str, Any]:
    timeout = op.timeout_seconds if op.timeout_seconds is not None else BOARD_TOOL_CALL_TIMEOUT_SECONDS
    left = ctx.seconds_left()
    if left is not None and timeout > 0:
        # A slow op late in the turn may not overrun the loop's wall-clock budget.
        timeout = max(OP_TIMEOUT_FLOOR_SECONDS, min(timeout, int(math.ceil(left))))
    if timeout <= 0:
        result = op.run(ctx, arguments)
    else:
        token = board_deadline.set_deadline(timeout)
        # Not a ``with`` block: the context manager joins the worker on exit,
        # which would make the caller wait out the whole slow op anyway.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"board-op-{op.name}")
        try:
            future = pool.submit(board_deadline.bind_context(op.run), ctx, arguments)
            try:
                result = future.result(timeout=timeout)
            except FuturesTimeout as exc:
                _log_event("warning", tag="board_tool_timeout", op=op.name, timeoutSeconds=timeout)
                raise TimeoutError(f"{op.name} timed out after {timeout}s") from exc
        finally:
            board_deadline.reset(token)
            pool.shutdown(wait=False, cancel_futures=True)
    return result if isinstance(result, dict) else {"result": result}


_SECURITY_ISSUE_LABELS = frozenset({"security", "dependencies"})


_ARCHITECT_AUTO_ACT_OPS = frozenset({"github_set_labels"})


def _architect_backlog_write(ctx: ToolContext, op: ToolOp) -> bool:
    """Architect label grooming executes at act. Comments stay a proposal."""
    return bool(ctx.seat_id == "architect" and op.name in _ARCHITECT_AUTO_ACT_OPS)


def _architect_comment_stays_proposal(ctx: ToolContext, op: ToolOp) -> bool:
    """Boilerplate acceptance-criteria comments wait for the founder."""
    return bool(ctx.seat_id == "architect" and op.name == "github_comment_issue")


def _union_github_labels(arguments: dict[str, Any]) -> dict[str, Any]:
    """Merge requested labels with the issue's current set so act cannot strip."""
    current = board_github.op_get_issue({"number": arguments.get("number")})
    if current.get("error"):
        raise board_github.GitHubSnapshotError(str(current.get("error")))
    existing = [str(name) for name in (current.get("labels") or []) if name]
    wanted = board_github._clean_labels(arguments.get("labels"))  # noqa: SLF001
    merged: list[str] = []
    for name in [*existing, *wanted]:
        if name and name not in merged:
            merged.append(name)
    # op_set_labels re-cleans to 10; a longer union would drop a requested label.
    if len(merged) > 10:
        raise board_github.GitHubSnapshotError("label union exceeds 10; leave as a proposal")
    return {**arguments, "labels": merged}


def _cto_security_issue(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> bool:
    """CTO filing a security/dependencies issue may act even when globalMode is propose.

    Labels are model-supplied. This is the only op that ignores the global cap;
    see docs/architecture/executive-board.md §5.1.
    """
    if op.name != "github_create_issue" or ctx.persona_id != "cto":
        return False
    labels = {str(x).strip().lower() for x in (arguments.get("labels") or []) if x}
    return bool(labels & _SECURITY_ISSUE_LABELS)


def _should_always_propose(op: ToolOp, ctx: ToolContext, arguments: dict[str, Any]) -> bool:
    if not op.always_propose:
        return False
    return not _cto_security_issue(ctx, op, arguments)


def _is_terminal_merge_guard(reason: str) -> bool:
    try:
        import board_code

        return board_code.is_terminal_merge_reason(reason)
    except Exception:
        return False


def execute_call(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> ToolOutcome:
    """Run (or record for approval) one operation and write the audit row."""
    started = time.monotonic()
    raw = arguments if isinstance(arguments, dict) else {}
    invalid = ""
    arg_limit = _argument_char_limit(op.name)
    try:
        arguments = validate_arguments(op, _clean_arguments(raw, limit=arg_limit))
    except InvalidArgumentsError as exc:
        invalid = str(exc)
        # Keep the (bounded) raw arguments so the audit row shows what was asked.
        arguments = raw if len(json.dumps(raw, default=str)) <= arg_limit else {}
    safety_actor = ctx.actor in ("persona", "hold")
    if safety_actor and op.tool_id == "task":
        level = task_ops_level(ctx.kind)
    elif safety_actor:
        if ctx.internal:
            level = "act"
        else:
            seats = None
            if ctx.seat_id:
                import board_staff

                seats = board_staff.seats_by_id(ctx.table, ctx.settings)
            level = effective_level(
                ctx.settings,
                op.tool_id,
                ctx.persona_id,
                seat_id=ctx.seat_id,
                seats_by_id=seats,
            )
        # Intentional: security/dependencies issues skip always_propose and the
        # globalMode cap so Dependabot / CVE tickets are filed without an Approval.
        if _cto_security_issue(ctx, op, arguments) and level in ("propose", "act"):
            level = "act"
        if _architect_backlog_write(ctx, op) and level in ("propose", "act"):
            if op.name == "github_set_labels":
                try:
                    arguments = _union_github_labels(arguments)
                except Exception:
                    # Fetch failed — do not replace labels unattended.
                    logging.getLogger(__name__).debug("suppressed", exc_info=True)
                else:
                    level = "act"
            else:
                level = "act"
        if _architect_comment_stays_proposal(ctx, op) and level == "act":
            level = "propose"
    else:
        level = "act"
    summary = op.summarize(arguments)
    if not invalid and op.name == "task_request_help":
        try:
            import board_staff as _staff_help

            summary = _staff_help.summarize_help_request(
                prepared=_staff_help.prepare_help_request(ctx, arguments)
            )
        except Exception:
            logging.getLogger(__name__).debug("suppressed", exc_info=True)
    approval_id = ""
    guard_reason = ""
    hold_fail = ""
    if ctx.actor == "hold":
        if not tools_enabled(ctx.settings):
            hold_fail = "tools are switched off"
        elif level != "act":
            hold_fail = "level changed"
    if op.is_write and not invalid and not hold_fail and level == "act" and safety_actor and op.act_guard is not None:
        try:
            guard_reason = str(op.act_guard(ctx, arguments) or "")
        except Exception as exc:  # pragma: no cover - a guard bug must fail closed
            _log_event("error", tag="board_tool_guard_crashed", op=op.name, error=str(exc)[:300])
            guard_reason = "the safety check could not be completed"
    breaker_error: dict[str, Any] | None = None
    if op.is_write and not invalid and not hold_fail and safety_actor:
        try:
            import board_breakers
            import board_staff as _staff

            if _staff.enabled(ctx.settings):
                breaker_error = board_breakers.write_blocked(ctx.table, op)
        except Exception as exc:
            _log_event("warning", tag="board_breaker_check_failed", op=op.name, error=str(exc)[:200])
            guard_reason = guard_reason or "the safety check could not be completed"
    hold_doc: dict[str, Any] | None = None
    if (
        op.is_write
        and not invalid
        and not breaker_error
        and level == "act"
        and not guard_reason
        and not hold_fail
        and ctx.actor == "persona"
    ):
        try:
            import board_holds

            hold_doc = board_holds.maybe_hold(ctx, op, arguments, summary=summary)
        except Exception as exc:  # pragma: no cover - hold bugs must fail closed (R-02)
            _log_event("error", tag="board_hold_check_failed", op=op.name, error=str(exc)[:300])
            guard_reason = guard_reason or "the safety check could not be completed"
    class_key = ""
    action_class = ""
    try:
        import board_holds as _holds_for_class

        action_class, class_key = _holds_for_class.classify(op, ctx, arguments, ctx.settings)
    except Exception:
        class_key = ""
        action_class = ""
    if ctx.actor == "hold" and (hold_fail or guard_reason or breaker_error):
        reason = hold_fail or guard_reason or str((breaker_error or {}).get("error") or "blocked")
        outcome = ToolOutcome(status="error", result={"error": reason}, summary=summary)
    elif not allows(level, op.min_level):
        outcome = ToolOutcome(
            status="error",
            result={"error": f"{op.name} is not available to you at level '{level}'."},
            summary=summary,
        )
    elif invalid:
        # Never queue a malformed proposal: the model gets the schema problem back
        # and can retry with corrected arguments.
        outcome = ToolOutcome(status="error", result={"error": invalid[:500]}, summary=summary)
    elif (world_error := _validate_world(ctx, op, arguments)):
        world_status = "refused" if op.name == "code_run_task" else "error"
        outcome = ToolOutcome(status=world_status, result={"error": world_error[:500]}, summary=summary)
    elif breaker_error:
        outcome = ToolOutcome(status="refused", result=breaker_error, summary=summary)
    elif hold_doc:
        execute_at = str(hold_doc.get("executeAt") or "")
        hold_id = str(hold_doc.get("holdId") or "")
        outcome = ToolOutcome(
            status="held",
            result={
                "status": "held",
                "holdId": hold_id,
                "executeAt": execute_at,
                "message": f"Scheduled; executes {execute_at} unless the founder vetoes.",
            },
            summary=f"Scheduled {summary} (executes {execute_at} unless vetoed)",
        )
    elif (
        (reused_assign := _reuse_staff_assign(ctx, op, arguments))
        if op.name == "staff_assign"
        else None
    ):
        outcome = ToolOutcome(status="ok", result=reused_assign, summary="Attached to an open task")
    elif guard_reason and op.name == "code_merge_staging" and _is_terminal_merge_guard(guard_reason):
        outcome = ToolOutcome(status="refused", result={"error": guard_reason}, summary=summary)
    elif op.is_write and ctx.actor != "hold" and (level != "act" or guard_reason or (_should_always_propose(op, ctx, arguments) and ctx.actor == "persona")):
        approval = create_approval(ctx, op, arguments, summary=summary, downgrade_reason=guard_reason)
        approval_id = str(approval["approvalId"])
        # Architect issue comments stay a proposal, and the proposal does not
        # park the groom task: the founder still decides whether it posts.
        blocks_task = not _architect_comment_stays_proposal(ctx, op)
        if blocks_task:
            message = (
                "Recorded as a proposal for the founder. It has NOT been executed; "
                "tell the founder it awaits their approval in the Approvals section."
            )
        else:
            message = (
                "Recorded as a proposal for the founder. It has NOT been posted. "
                "Continue the task and cite the approval id; the comment posts "
                "only after the founder accepts."
            )
        if guard_reason:
            message = f"Not sent automatically because {guard_reason}. " + message
        outcome = ToolOutcome(
            status="pending_approval",
            result={"status": "pending_approval", "approvalId": approval_id, "message": message},
            summary=summary,
            approval_id=approval_id,
            blocks_task=blocks_task,
        )
    else:
        try:
            result = _invoke_op(ctx, op, arguments)
            status = "error" if _is_error_result(result) else "ok"
            outcome = ToolOutcome(status=status, result=result, summary=summary)
            if status == "ok":
                try:
                    import board_policy

                    if op.name in board_policy.REPLY_OPS:
                        board_policy.record_reply(ctx.table, op.name, arguments)
                except Exception:
                    logging.getLogger(__name__).debug("suppressed", exc_info=True)
                if op.is_write and ctx.actor == "persona" and class_key:
                    try:
                        import board_holds as _holds_ramp

                        hours = _holds_ramp.hold_hours(ctx.table, ctx.settings, action_class, class_key)
                        if hours <= 0:
                            _holds_ramp.record_ramp(ctx.table, ctx.settings, class_key, vetoed=False)
                    except Exception:
                        logging.getLogger(__name__).debug("suppressed", exc_info=True)
        except Exception as exc:
            if getattr(exc, "refused", False):
                outcome = ToolOutcome(status="refused", result={"error": str(exc)[:500]}, summary=summary)
            elif isinstance(
                exc,
                (
                    board_github.GitHubSnapshotError,
                    board_mail.MailError,
                    board_research.ResearchError,
                    board_aws.AwsToolError,
                    board_security.SecurityToolError,
                    board_receivables.ReceivablesError,
                    board_product.ProductError,
                    board_meta.MetaError,
                    board_stores.StoresError,
                    board_web.WebError,
                    TimeoutError,
                    ValueError,
                ),
            ):
                outcome = ToolOutcome(status="error", result={"error": str(exc)[:500]}, summary=summary)
            else:
                _log_event("error", tag="board_tool_crashed", op=op.name, error=str(exc)[:300])
                outcome = ToolOutcome(status="error", result={"error": f"Tool failed: {str(exc)[:200]}"}, summary=summary)
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    outcome.approval_id = approval_id or outcome.approval_id
    audit = mask_arguments(ctx, {"arguments": arguments, "summary": summary})
    ctx.bind_task_meta()
    attempt = ctx.task_attempt
    record = board_store.add_tool_call(
        ctx.table,
        {
            "personaId": ctx.persona_id,
            "displayName": ctx.display_name,
            "actor": ctx.actor,
            "ownerSub": ctx.owner_sub if ctx.actor == "owner" else "",
            "toolId": op.tool_id,
            "op": op.name,
            "kind": op.kind,
            "level": level,
            "arguments": audit["arguments"],
            "status": outcome.status,
            "summary": audit["summary"],
            "resultPreview": _truncate_json(outcome.result, MAX_RESULT_PREVIEW),
            "approvalId": approval_id,
            "downgradeReason": guard_reason,
            "context": ctx.public(),
            "durationMs": outcome.duration_ms,
            "taskId": ctx.task_id,
            "seatId": ctx.seat_id,
            "classKey": class_key,
            **({"errorCause": cause} if (cause := _error_cause(outcome)) else {}),
            **({"attempt": attempt} if attempt is not None else {}),
            **({"toolCallId": ctx.llm_tool_call_id} if ctx.llm_tool_call_id else {}),
        },
    )
    outcome.call_id = str(record["callId"])
    if isinstance(outcome.result, dict) and outcome.call_id:
        outcome.result = {**outcome.result, "callId": outcome.call_id}
    _log_event(
        "info",
        tag="board_tool_call",
        op=op.name,
        persona=ctx.persona_id,
        actor=ctx.actor,
        status=outcome.status,
        duration_ms=outcome.duration_ms,
    )
    return outcome


def render_preview(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if op.preview is None:
        return None
    try:
        return op.preview(ctx, arguments)
    except Exception as exc:  # pragma: no cover - preview is best effort
        _log_event("warning", tag="board_tool_preview_failed", op=op.name, error=str(exc)[:300])
        return {"error": "Preview unavailable"}


# Keys an op may return next to ``error`` without the call counting as ``ok``.
# ``cause: "page"`` marks a research fetch that ran but hit a bad page; the
# breaker ignores those (``board_breakers.evaluate``).
_ERROR_META_KEYS = frozenset({"cause"})


def _is_error_result(result: dict[str, Any]) -> bool:
    if not result.get("error"):
        return False
    return all(key in _ERROR_META_KEYS for key in result if key != "error")


def _error_cause(outcome: ToolOutcome) -> str:
    if outcome.status != "error" or not isinstance(outcome.result, dict):
        return ""
    return str(outcome.result.get("cause") or "")[:40]


def _validate_world(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> str:
    """Refuse a propose/act that cannot succeed even if the founder approves."""
    if op.validate is None:
        return ""
    try:
        return str(op.validate(ctx, arguments) or "")
    except Exception as exc:
        _log_event("warning", tag="board_tool_validate_failed", op=op.name, error=str(exc)[:200])
        return ""


def approval_fingerprint(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> str:
    payload = {k: v for k, v in (arguments or {}).items() if k != "reason"}
    payload["_task"] = ctx.task_id or ""
    payload["_op"] = op.name
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _reuse_staff_assign(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if op.name != "staff_assign":
        return None
    try:
        import board_staff as _staff_reuse

        return _staff_reuse.reuse_open_assignment(ctx, arguments)
    except Exception:
        return None


def _approval_expires_at(now: str) -> str:
    try:
        created = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        created = datetime.now(timezone.utc)
    expires = created + timedelta(hours=BOARD_STAFF_APPROVAL_EXPIRY_HOURS)
    return expires.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_approval(
    ctx: ToolContext,
    op: ToolOp,
    arguments: dict[str, Any],
    *,
    summary: str,
    downgrade_reason: str = "",
) -> dict[str, Any]:
    pending = [a for a in board_store.list_approvals(ctx.table) if a.get("status") == "pending"]
    fingerprint = approval_fingerprint(ctx, op, arguments)
    for existing in pending:
        if str(existing.get("fingerprint") or "") == fingerprint:
            return existing
        if (
            op.name == "code_merge_staging"
            and str(existing.get("op") or "") == op.name
            and _same_merge_pr(existing.get("arguments") or {}, arguments)
        ):
            return _refresh_pending_approval(
                ctx,
                op,
                existing,
                arguments,
                summary=summary,
                downgrade_reason=downgrade_reason,
                fingerprint=fingerprint,
            )
        if (
            str(existing.get("op") or "") == op.name
            and str((existing.get("context") or {}).get("taskId") or "") == (ctx.task_id or "")
            and ctx.task_id
        ):
            existing_args = {k: v for k, v in (existing.get("arguments") or {}).items() if k != "reason"}
            new_args = {k: v for k, v in (arguments or {}).items() if k != "reason"}
            if existing_args == new_args:
                return existing
            if op.name == "code_run_task" and _same_code_run_target(existing.get("arguments") or {}, arguments):
                return _refresh_pending_approval(
                    ctx,
                    op,
                    existing,
                    arguments,
                    summary=summary,
                    downgrade_reason=downgrade_reason,
                    fingerprint=fingerprint,
                )
            if op.name == "github_create_issue" and _same_github_issue_title(
                existing.get("arguments") or {}, arguments
            ):
                return _refresh_pending_approval(
                    ctx,
                    op,
                    existing,
                    arguments,
                    summary=summary,
                    downgrade_reason=downgrade_reason,
                    fingerprint=fingerprint,
                )
            if op.name == "mail_send" and _same_mail_recipients(existing.get("arguments") or {}, arguments):
                return existing
    if len(pending) >= BOARD_MAX_PENDING_APPROVALS:
        raise ToolPermissionError("Too many pending approvals; ask the founder to review the queue first.")
    now = board_store.now_iso()
    preview = render_preview(ctx, op, arguments)
    doc = {
        "approvalId": board_store.new_id(),
        "status": "pending",
        "personaId": ctx.persona_id,
        "displayName": ctx.display_name,
        "toolId": op.tool_id,
        "toolLabel": TOOL_LABELS.get(op.tool_id, op.tool_id),
        "op": op.name,
        "kind": op.kind,
        "arguments": arguments,
        "summary": summary,
        "reason": str(arguments.get("reason") or "")[:400],
        "fingerprint": fingerprint,
        "context": ctx.public(),
        "createdAt": now,
        "updatedAt": now,
        "autoRejectAt": _approval_expires_at(now),
    }
    if downgrade_reason:
        doc["downgradeReason"] = downgrade_reason[:300]
    if preview is not None:
        doc["preview"] = preview
    board_store.put_approval(ctx.table, doc)
    return doc


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def _completion_hit_length_limit(completion: ChatCompletion | None) -> bool:
    return bool(completion and str(getattr(completion, "finish_reason", "") or "") == "length")


def _board_completion_with_length_retry(
    *,
    ctx: ToolContext,
    messages: list[dict[str, Any]],
    model: str,
    timeout_s: int,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    tag: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    wall_clock_seconds: float | None = None,
) -> ChatCompletion:
    """Call the model; if the reply hits the token cap below 6000, retry once at 6000.

    ``wall_clock_seconds`` is the hard abort for a provider that keeps the
    socket busy (staff steps pass their loop budget); ``None`` keeps
    socket-inactivity semantics for owner chat and jobs.
    """
    kwargs: dict[str, Any] = {}
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice
    if wall_clock_seconds is not None:
        kwargs["wall_clock_seconds"] = wall_clock_seconds
    completion = board_budget.board_completion(
        table=ctx.table,
        messages=messages,
        model=model,
        timeout=timeout_s,
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
        tag=tag,
        usage_sink=ctx.usage_sink,
        settings=ctx.settings,
        **kwargs,
    )
    if _completion_hit_length_limit(completion) and max_tokens < 6000:
        _log_event(
            "info",
            tag="board_tool_loop_length_retry",
            persona=ctx.persona_id,
            max_tokens=max_tokens,
        )
        retry = board_budget.board_completion(
            table=ctx.table,
            messages=messages,
            model=model,
            timeout=timeout_s,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=6000,
            tag=tag,
            usage_sink=ctx.usage_sink,
            settings=ctx.settings,
            **kwargs,
        )
        retry.usage = add_usage(completion.usage, retry.usage)
        return retry
    return completion


def _loop_wall_clock(ctx: ToolContext, left: float, timeout_s: int) -> float | None:
    """Hard abort for one model call inside a deadline-bound loop.

    The call may use the rest of the loop budget while the provider keeps
    the socket busy, and never less than the socket timeout it was granted
    (the final-answer floor may exceed the leftover budget by design).
    Contexts without a deadline (owner chat, jobs) get ``None``.
    """
    if not ctx.deadline:
        return None
    return float(max(1, int(timeout_s), math.ceil(max(0.0, left))))


def run_tool_loop(
    *,
    ctx: ToolContext,
    messages: list[dict[str, Any]],
    model: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    tag: str,
    max_seconds: int,
    on_progress: Callable[[list[dict[str, Any]]], None] | None = None,
    require_op: str | None = None,
) -> ToolLoopResult:
    """Call the model, execute any requested tools, repeat, then return the final text.

    Falls back to a single plain completion when the member has no tools.
    The final answer is always produced by a call where the model was not
    allowed to request more tools, so the loop terminates deterministically.
    ``require_op`` sets OpenAI ``tool_choice`` to that function (staff last
    step: force ``task_finish`` so the seat cannot stall in prose).
    """
    seats = None
    if ctx.seat_id:
        import board_staff

        seats = board_staff.seats_by_id(ctx.table, ctx.settings)
    ops = available_ops(
        ctx.settings,
        ctx.persona_id,
        context=ctx.kind,
        seat_id=ctx.seat_id,
        seats_by_id=seats,
    )
    if ctx.task_id:
        current = board_store.get_task(ctx.table, ctx.task_id)
        if current and current.get("parentTaskId"):
            ops = [(op, lvl) for op, lvl in ops if op.name != "task_request_help"]
    if not ops:
        completion = _board_completion_with_length_retry(
            ctx=ctx,
            messages=messages,
            model=model,
            timeout_s=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            tag=tag,
            wall_clock_seconds=_loop_wall_clock(ctx, float(max_seconds), timeout),
        )
        return ToolLoopResult(text=completion.text, usage=completion.usage, model=completion.model, rounds=1, completion=completion)

    by_name = {op.name: op for op, _lvl in ops}
    schemas = [op.schema() for op, _lvl in ops]
    choice: str | dict[str, Any] = "auto"
    if require_op and require_op in by_name:
        choice = {"type": "function", "function": {"name": require_op}}
    convo: list[dict[str, Any]] = [*messages]
    preamble = tools_preamble(ops)
    if preamble:
        # After the persona prompt and context pack, before the conversation.
        index = 0
        while index < len(convo) and convo[index].get("role") == "system":
            index += 1
        convo.insert(index, {"role": "system", "content": preamble})

    usage = add_usage(None, None)
    calls: list[dict[str, Any]] = []
    started = time.monotonic()
    ctx.deadline = started + max_seconds
    rounds = 0
    synthetic_rounds = 0
    final: ChatCompletion | None = None
    stop_reason = ""
    while rounds < BOARD_MAX_TOOL_ROUNDS_PER_TURN:
        left = max_seconds - (time.monotonic() - started)
        calls_left = BOARD_MAX_TOOL_CALLS_PER_TURN - len(calls)
        if left <= 0 or calls_left <= 0:
            break
        timeout_s = completion_timeout(timeout, left, MODEL_CALL_TIMEOUT_FLOOR_SECONDS)
        if timeout_s <= 0:
            break
        if rounds:
            # The caller checked the daily cap before the turn; every further
            # round is another paid call, so re-check between rounds.
            try:
                board_budget.check_budget(ctx.table, ctx.settings)
            except board_budget.BudgetExceeded as exc:
                stop_reason = str(exc)
                _log_event("warning", tag="board_tool_loop_budget_stop", persona=ctx.persona_id, rounds=rounds)
                break
        rounds += 1
        completion = _board_completion_with_length_retry(
            ctx=ctx,
            messages=convo,
            model=model,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=False,
            tag=tag,
            tools=schemas,
            tool_choice=choice,
            wall_clock_seconds=_loop_wall_clock(ctx, left, timeout_s),
        )
        usage = add_usage(usage, completion.usage)
        tool_calls = list(completion.tool_calls or [])
        if not tool_calls:
            tool_calls = parse_prose_tool_calls(completion.text)
            if tool_calls:
                synthetic_rounds += 1
                if synthetic_rounds >= 2:
                    fallbacks = board_budget.fallback_models_for(model, ctx.settings)
                    if fallbacks:
                        model = fallbacks[0]
        if not tool_calls:
            final = completion
            break
        convo.append(completion.assistant_message() if completion.tool_calls else {"role": "assistant", "content": completion.text or "", "tool_calls": [tc.as_message_entry() for tc in tool_calls]})
        for index, tc in enumerate(tool_calls):
            if index >= calls_left:
                convo.append(_tool_message(tc, {"error": "Call budget for this reply is exhausted; answer with what you have."}))
            elif time.monotonic() >= ctx.deadline:
                convo.append(_tool_message(tc, {"error": "Time budget for this reply is exhausted; answer with what you have."}))
            else:
                convo.append(_run_one(ctx, by_name, tc, calls))
        if any(c.get("op") == "task_finish" and c.get("status") == "ok" for c in calls):
            # The task is already in review; a paid final-answer call would
            # race the manager review and overwrite the row.
            final = completion
            break
        if on_progress:
            try:
                on_progress(list(calls))
            except Exception:  # pragma: no cover - progress is best effort
                logging.getLogger(__name__).debug("suppressed", exc_info=True)

    if final is None:
        if stop_reason:
            convo.append({"role": "system", "content": f"No more tool calls are possible: {stop_reason} Answer with what you have."})
        rounds += 1
        # The answer call may run past the loop budget, but only up to the
        # OpenRouter timeout; the sums in the module header rely on that.
        left = max_seconds - (time.monotonic() - started)
        timeout_s = completion_timeout(
            timeout,
            left,
            FINAL_CALL_TIMEOUT_FLOOR_SECONDS,
            allow_floor_overrun=True,
        )
        if timeout_s <= 0:
            return ToolLoopResult(text="", usage=usage, model=model, calls=calls, rounds=rounds)
        final = _board_completion_with_length_retry(
            ctx=ctx,
            messages=convo,
            model=model,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            tag=tag,
            tools=schemas,
            tool_choice="none",
            wall_clock_seconds=_loop_wall_clock(ctx, left, timeout_s),
        )
        usage = add_usage(usage, final.usage)
    return ToolLoopResult(text=final.text, usage=usage, model=final.model, calls=calls, rounds=rounds, completion=final)


_PROSE_FC_RE = re.compile(r"!function_call:\s*")


def _tool_call_from_prose_payload(data: Any, *, call_id: str = "prose-call") -> ToolCall | None:
    if not isinstance(data, dict):
        return None
    name = str(data.get("call") or data.get("name") or "").strip()
    args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
    if not name:
        return None
    return ToolCall(
        id=str(data.get("id") or call_id),
        name=name,
        arguments=args,
        raw_arguments=json.dumps(args),
    )


def parse_prose_tool_calls(text: str) -> list[ToolCall]:
    """Recover DeepSeek-style ``!function_call:{...}`` blobs as real tool calls."""
    raw = text or ""
    found: list[ToolCall] = []
    decoder = json.JSONDecoder()
    for index, match in enumerate(_PROSE_FC_RE.finditer(raw)):
        try:
            data, _end = decoder.raw_decode(raw, match.end())
        except json.JSONDecodeError:
            continue
        call = _tool_call_from_prose_payload(data, call_id=f"prose-call-{index}")
        if call:
            found.append(call)
    if found:
        return found
    fence = re.search(r"```(?:json)?\s*(\{\s*\"(?:id|call|name)\".*?\})\s*```", raw, re.S)
    if not fence:
        return []
    try:
        data = json.loads(fence.group(1))
    except json.JSONDecodeError:
        return []
    call = _tool_call_from_prose_payload(data)
    return [call] if call else []


def _same_merge_pr(left: dict[str, Any], right: dict[str, Any]) -> bool:
    try:
        left_pr = int(left.get("prNumber") or 0)
        right_pr = int(right.get("prNumber") or 0)
    except (TypeError, ValueError):
        return False
    return bool(left_pr) and left_pr == right_pr


def _same_code_run_target(left: dict[str, Any], right: dict[str, Any]) -> bool:
    try:
        left_issue = int(left.get("issueNumber") or 0)
        right_issue = int(right.get("issueNumber") or 0)
    except (TypeError, ValueError):
        return False
    return bool(left_issue) and left_issue == right_issue


def _norm_issue_title(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _same_github_issue_title(left: dict[str, Any], right: dict[str, Any]) -> bool:
    title = _norm_issue_title(left.get("title"))
    return bool(title) and title == _norm_issue_title(right.get("title"))


def _mail_recipient_key(args: dict[str, Any]) -> tuple[str, ...]:
    raw = args.get("to")
    if isinstance(raw, str):
        values = [v.strip().lower() for v in re.split(r"[,;\s]+", raw) if v.strip()]
    elif isinstance(raw, list):
        values = [str(v).strip().lower() for v in raw if v]
    else:
        values = [str(raw).strip().lower()] if raw else []
    return tuple(sorted(values))


def _same_mail_recipients(left: dict[str, Any], right: dict[str, Any]) -> bool:
    key = _mail_recipient_key(left)
    return bool(key) and key == _mail_recipient_key(right)


def _refresh_pending_approval(
    ctx: ToolContext,
    op: ToolOp,
    existing: dict[str, Any],
    arguments: dict[str, Any],
    *,
    summary: str,
    downgrade_reason: str,
    fingerprint: str,
) -> dict[str, Any]:
    """Keep one pending row but show the latest brief/args to the founder."""
    now = board_store.now_iso()
    updated = {
        **existing,
        "arguments": arguments,
        "summary": summary,
        "reason": str(arguments.get("reason") or existing.get("reason") or "")[:400],
        "fingerprint": fingerprint,
        "updatedAt": now,
    }
    preview = render_preview(ctx, op, arguments)
    if preview is not None:
        updated["preview"] = preview
    if downgrade_reason:
        updated["downgradeReason"] = downgrade_reason[:300]
    board_store.put_approval(ctx.table, updated)
    return updated


def _run_one(
    ctx: ToolContext,
    by_name: dict[str, ToolOp],
    tc: ToolCall,
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    op = by_name.get(tc.name)
    if op is None:
        return _tool_message(tc, {"error": f"Unknown tool {tc.name}"})
    if tc.name == "task_finish" and any(
        str(c.get("status") or "") == "pending_approval" and c.get("blocksTask") is not False for c in calls
    ):
        return _tool_message(
            tc,
            {
                "error": (
                    "a blocking approval is pending in this step; "
                    "wait for the founder before calling task_finish"
                )
            },
        )
    bound = replace(ctx, llm_tool_call_id=str(tc.id or ""))
    try:
        outcome = execute_call(bound, op, tc.arguments)
    except ToolPermissionError as exc:
        return _tool_message(tc, {"error": str(exc)})
    calls.append(outcome.public(op))
    return _tool_message(tc, outcome.result)


def _tool_message(tc: ToolCall, result: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tc.id,
        "name": tc.name,
        "content": _truncate_json(result, BOARD_TOOL_RESULT_MAX_CHARS),
    }


# ---------------------------------------------------------------------------
# Owner decisions on approvals
# ---------------------------------------------------------------------------

def decide_approval(
    table: Any,
    settings: dict[str, Any],
    approval_id: str,
    *,
    approve: bool,
    owner_sub: str,
    note: str = "",
    arguments_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Approve (execute as the owner) or reject a pending proposal."""
    doc = board_store.get_approval(table, approval_id)
    if not doc:
        raise LookupError("Approval not found")
    if doc.get("status") != "pending":
        raise ValueError(f"Approval is already {doc.get('status')}")
    op = REGISTRY.get(str(doc.get("op") or ""))
    arguments = dict(doc.get("arguments") or {})
    if approve:
        # Everything that can be checked up front happens before the claim so a
        # refused decision leaves the approval pending instead of half-decided.
        if not tools_enabled(settings):
            raise ValueError("Board tools are switched off; enable them before approving proposals.")
        if global_cap(settings) == "read":
            raise ValueError("The board is in read-only mode; switch it to propose or act before approving proposals.")
        if isinstance(arguments_override, dict):
            arguments.update(arguments_override)
        if op is not None:
            arguments = validate_arguments(
                op, _clean_arguments(arguments, limit=_argument_char_limit(op.name))
            )
    next_status = "approved" if approve else "rejected"
    if not board_store.claim_approval_decision(table, approval_id, status=next_status):
        raise ValueError("Approval was decided by someone else a moment ago")
    now = board_store.now_iso()
    decided = {
        **doc,
        "status": next_status,
        "decidedAt": now,
        "decidedBySub": owner_sub,
        "note": note[:1000],
        "updatedAt": now,
    }
    if not approve:
        board_store.put_approval(table, decided)
        _resume_waiting_staff(table, settings, decided)
        return decided

    if op is None:
        decided.update({"status": "failed", "errorMessage": "This operation no longer exists."})
        board_store.put_approval(table, decided)
        return decided
    profile = board_personas.persona_default(str(doc.get("personaId") or "")) or {}
    ctx = ToolContext(
        table=table,
        settings=settings,
        persona_id=str(doc.get("personaId") or ""),
        display_name=str(doc.get("displayName") or profile.get("shortName") or ""),
        kind=str((doc.get("context") or {}).get("kind") or "approval"),
        meeting_id=str((doc.get("context") or {}).get("meetingId") or ""),
        task_id=str((doc.get("context") or {}).get("taskId") or ""),
        seat_id=str((doc.get("context") or {}).get("seatId") or ""),
        actor="owner",
        owner_sub=owner_sub,
    )
    if isinstance(arguments_override, dict) and arguments_override:
        refreshed = render_preview(ctx, op, arguments)
        if refreshed is not None:
            decided["preview"] = refreshed
    decided["arguments"] = arguments
    try:
        outcome = execute_call(ctx, op, arguments)
    except Exception as exc:  # pragma: no cover - the claim is taken; never leave it "approved" forever
        _log_event("error", tag="board_approval_execute_crashed", op=op.name, error=str(exc)[:300])
        decided.update({"status": "failed", "errorMessage": f"Execution failed: {str(exc)[:400]}"})
        board_store.put_approval(table, decided)
        return decided
    decided["executedCallId"] = outcome.call_id
    if outcome.status == "ok":
        decided.update({"status": "executed", "result": outcome.result})
    else:
        decided.update({"status": "failed", "errorMessage": str(outcome.result.get("error") or "Execution failed")[:500]})
    board_store.put_approval(table, decided)
    _resume_waiting_staff(table, settings, decided)
    return decided


def _resume_waiting_staff(table: Any, settings: dict[str, Any], approval: dict[str, Any]) -> None:
    try:
        import board_staff

        board_staff.resume_after_approval(table, settings, approval)
    except Exception as exc:
        _log_event("warning", tag="board_staff_resume_after_approval_failed", error=str(exc)[:200])


def expire_stale_approvals(table: Any, settings: dict[str, Any], now_iso: str | None = None) -> int:
    """Reject pending approvals that carry ``autoRejectAt`` and are due.

    ``expiresAt`` on the Dynamo row is the table TTL, not this deadline.
    Approvals created before ``autoRejectAt`` existed are left for the founder.
    """
    now = now_iso or board_store.now_iso()
    expired = 0
    for approval in board_store.list_approvals(table):
        if approval.get("status") != "pending":
            continue
        expires = str(approval.get("autoRejectAt") or "")
        if not expires or expires > now:
            continue
        approval_id = str(approval.get("approvalId") or "")
        if not approval_id:
            continue
        if not board_store.claim_approval_decision(table, approval_id, status="rejected"):
            continue
        decided = {
            **approval,
            "status": "rejected",
            "decidedAt": now,
            "decidedBySub": "system:expiry",
            "note": f"Expired after {BOARD_STAFF_APPROVAL_EXPIRY_HOURS}h without a founder decision.",
            "updatedAt": now,
        }
        board_store.put_approval(table, decided)
        _resume_waiting_staff(table, settings, decided)
        expired += 1
    return expired


def public_approval(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("decidedBySub",)}
