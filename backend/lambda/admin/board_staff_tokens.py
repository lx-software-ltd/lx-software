"""Completion-token budget for one staff step.

A retried step already spent the wall clock, so the second model is asked
for a shorter completion.
"""

from __future__ import annotations

from typing import Any

_STEP_TOKENS_DEFAULT = 2500
_STEP_TOKENS_LARGE = 6000
_STEP_TOKENS_RETRY = 1500
_STEP_TOKENS_CONTENT_PLAN = 6000


def _step_max_tokens(task: dict[str, Any], *, retried: bool = False) -> int:
    """JSON and the last step use 6000. Everything else uses 2500. A retry uses 1500."""
    import board_staff as staff

    if staff._is_content_plan(task):
        budget = _STEP_TOKENS_CONTENT_PLAN
    elif str(task.get("deliverableType") or "") == "json" or staff._should_require_finish(task):
        budget = _STEP_TOKENS_LARGE
    else:
        budget = _STEP_TOKENS_DEFAULT
    return min(budget, _STEP_TOKENS_RETRY) if retried else budget
