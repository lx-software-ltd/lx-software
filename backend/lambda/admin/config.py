"""Process environment accessors.

Read ``os.environ`` on each call. Tests patch the environment after import, so
these helpers must not cache values at module load.
"""

from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSEY = frozenset({"0", "false", "no", "off"})


def records_table_name() -> str:
    return os.environ["RECORDS_TABLE_NAME"]


def assets_bucket() -> str:
    return (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()


def flag_value(raw: object, default: bool = False) -> bool:
    """Parse one boolean token.

    Truthy values are ``1``, ``true``, ``yes``, ``on``. False values are
    ``0``, ``false``, ``no``, ``off``. Matching is case-insensitive. A blank
    value, ``None``, and any other token return ``default``. Booleans pass
    through.
    """
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if not text:
        return default
    if text in _TRUTHY:
        return True
    if text in _FALSEY:
        return False
    return default


def env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable. See :func:`flag_value`."""
    if name not in os.environ:
        return default
    return flag_value(os.environ.get(name), default)
