"""Share one OpenRouter wall clock across the model walk.

The first model keeps a reserve for a later model only when that reserve
still leaves the current attempt thirty seconds. The last model receives
whatever time remains.
"""

from __future__ import annotations

from typing import Any

_MODEL_WALK_STATUSES = frozenset({429, 502, 503})
FALLBACK_RESERVE_SECONDS = 45.0
MIN_MODEL_ATTEMPT_SECONDS = 30.0


def slice_wall_clock(wall_left: float | None, later_models: int) -> float | None:
    """Cap one attempt so a later model still has a slice of the same budget."""
    if wall_left is None or later_models <= 0:
        return wall_left
    reserve = min(FALLBACK_RESERVE_SECONDS, wall_left / 2)
    if wall_left - reserve < MIN_MODEL_ATTEMPT_SECONDS:
        return wall_left
    return wall_left - reserve


def walk_model(exc: Any, index: int, chain_len: int, wall_left: float | None) -> bool:
    """True when this failure should try the next model in the chain."""
    if index >= chain_len - 1:
        return False
    if getattr(exc, "status", None) in _MODEL_WALK_STATUSES:
        return True
    timed_out = "wall-clock budget exhausted" in str(exc)
    return timed_out and (wall_left or 0) >= MIN_MODEL_ATTEMPT_SECONDS
