"""Executive Board: model selection, daily budget guard and usage accounting."""

from __future__ import annotations

import os
from typing import Any

import board_store
import openrouter_client
import openrouter_usage
from admin_runtime import _get_secretsmanager_client
from contract_constants import BOARD_MAX_DAILY_BUDGET_USD
from http_common import _log_event

DEFAULT_CHAT_MODEL = "openai/gpt-4.1-mini"
DEFAULT_STANDUP_MODEL = "openai/gpt-4.1-mini"
DEFAULT_DEEP_DIVE_MODEL = "anthropic/claude-sonnet-4"


class BudgetExceeded(RuntimeError):
    """Daily spend cap reached; refuse new work until tomorrow (UTC)."""


def model_for(kind: str, settings: dict[str, Any]) -> str:
    override = str((settings.get("models") or {}).get(kind) or "").strip()
    if override:
        return override
    env_name = {
        "chat": "BOARD_CHAT_MODEL",
        "standup": "BOARD_MEETING_MODEL",
        "deepDive": "BOARD_DEEP_DIVE_MODEL",
    }.get(kind, "BOARD_CHAT_MODEL")
    from_env = (os.environ.get(env_name) or "").strip()
    if from_env:
        return from_env
    return {
        "chat": DEFAULT_CHAT_MODEL,
        "standup": DEFAULT_STANDUP_MODEL,
        "deepDive": DEFAULT_DEEP_DIVE_MODEL,
    }.get(kind, DEFAULT_CHAT_MODEL)


def daily_budget_usd(settings: dict[str, Any]) -> float:
    try:
        value = float(settings.get("dailyBudgetUsd") or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(float(BOARD_MAX_DAILY_BUDGET_USD), value))


def check_budget(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    """Return today's usage; raise BudgetExceeded when the cap is reached."""
    usage = board_store.load_usage_day(table)
    cap = daily_budget_usd(settings)
    if cap > 0 and usage["cost"] >= cap:
        _log_event(
            "warning",
            tag="board_budget_refused",
            spent_usd=round(usage["cost"], 4),
            cap_usd=cap,
        )
        raise BudgetExceeded(
            f"Daily board budget of USD {cap:.2f} is exhausted "
            f"(spent USD {usage['cost']:.2f} today). Raise the cap in settings or try tomorrow."
        )
    return usage


def board_completion(
    *,
    table: Any,
    messages: list[dict[str, Any]],
    model: str,
    timeout: int,
    json_mode: bool = False,
    temperature: float | None = 0.4,
    max_tokens: int | None = None,
    max_retries: int = 1,
    tag: str = "board_completion",
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> openrouter_client.ChatCompletion:
    """One board LLM call with usage recorded against today's budget."""
    completion = openrouter_client.chat_completion(
        messages=messages,
        model=model,
        secrets_client=_get_secretsmanager_client(),
        timeout=timeout,
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
        include_usage=True,
        deny_data_collection=True,
        max_retries=max_retries,
        tools=tools,
        tool_choice=tool_choice,
        service=openrouter_client.SERVICE_EXECUTIVE_BOARD,
        owner=board_store.BOARD_KEY,
    )
    try:
        board_store.add_usage_day(table, completion.usage)
    except Exception as exc:  # pragma: no cover - accounting must not break the call
        _log_event("warning", tag="board_usage_record_failed", error=str(exc)[:200])
    try:
        openrouter_usage.add_usage_day(
            table,
            service=openrouter_client.SERVICE_EXECUTIVE_BOARD,
            owner=board_store.BOARD_KEY,
            usage=completion.usage,
        )
    except Exception as exc:  # pragma: no cover - accounting must not break the call
        _log_event("warning", tag="openrouter_usage_record_failed", error=str(exc)[:200])
    _log_event(
        "info",
        tag=tag,
        model=completion.model,
        prompt_tokens=completion.usage.get("promptTokens"),
        completion_tokens=completion.usage.get("completionTokens"),
        cost_usd=completion.usage.get("cost"),
        tool_calls=len(completion.tool_calls),
    )
    return completion
