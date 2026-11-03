"""Meta token caches: System User secret, app secret, and Page-token exchange.

``graph()`` lives in ``board_meta`` so existing ``_urlopen`` patches keep
working. This module is imported by ``board_meta``; ``page_token`` lazy-imports
``graph`` to avoid a cycle.
"""

from __future__ import annotations

import os

from admin_runtime import _get_secretsmanager_client
from http_common import _log_event
from openrouter_client import OpenRouterError
from secret_store import read_secret_string

_token_cache: str | None = None
_token_checked = False
_app_secret_cache: str | None = None
_app_secret_checked = False
_page_token_cache: dict[str, str] = {}


def reset_caches() -> None:
    global _token_cache, _token_checked, _app_secret_cache, _app_secret_checked
    _page_token_cache.clear()
    _token_cache = None
    _token_checked = False
    _app_secret_cache = None
    _app_secret_checked = False


def _secret(env_plain: str, env_arn: str, *, what: str) -> str:
    plain = (os.environ.get(env_plain) or "").strip()
    if plain:
        return plain
    arn = (os.environ.get(env_arn) or "").strip()
    if not arn:
        return ""
    try:
        return read_secret_string(_get_secretsmanager_client(), arn, what=what).strip()
    except OpenRouterError as exc:
        _log_event("warning", tag="board_meta_secret_failed", error=str(exc)[:200])
        return ""


def board_token() -> str:
    global _token_cache, _token_checked
    if _token_checked:
        return _token_cache or ""
    _token_checked = True
    _token_cache = _secret("META_BOARD_TOKEN", "META_BOARD_TOKEN_SECRET_ARN", what="Meta board token")
    return _token_cache or ""


def app_secret() -> str:
    global _app_secret_cache, _app_secret_checked
    if _app_secret_checked:
        return _app_secret_cache or ""
    _app_secret_checked = True
    _app_secret_cache = _secret("META_APP_SECRET", "META_APP_SECRET_SECRET_ARN", what="Meta app secret")
    return _app_secret_cache or ""


def page_scoped(path: str, pid: str) -> bool:
    """True for ``/{page-id}/…`` and Page-prefixed object ids (``{page-id}_{post}``)."""
    if not pid:
        return False
    head = path.lstrip("/").split("/", 1)[0].split("?", 1)[0]
    return head == pid or head.startswith(f"{pid}_")


def page_token(pid: str) -> str:
    """Page access token derived from the System User token.

    Pages on the new Pages experience reject user and System User tokens on
    Page edges (Graph code 190, subcode 2069032), so the token is exchanged
    through ``GET /{page-id}?fields=access_token`` once per warm container.
    Returns "" when the exchange yields nothing; nothing is cached then so
    the next call retries. The caller falls back to the System User token
    so Meta's own error reaches the persona.
    """
    cached = _page_token_cache.get(pid)
    if cached:
        return cached
    import board_meta

    try:
        data = board_meta.graph("GET", pid, params={"fields": "access_token"}, token=board_token())
    except board_meta.MetaError as exc:
        _log_event("warning", tag="board_meta_page_token_failed", page=pid, error=str(exc)[:200])
        return ""
    token = str(data.get("access_token") or "").strip()
    if not token:
        _log_event("warning", tag="board_meta_page_token_missing", page=pid)
        return ""
    _page_token_cache[pid] = token
    return token


def token_for(path: str) -> str:
    import board_meta

    token = board_token()
    pid = board_meta.page_id()
    if token and page_scoped(path, pid):
        return page_token(pid) or token
    return token
