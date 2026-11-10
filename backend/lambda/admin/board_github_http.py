"""GitHub reads with a hard deadline and one retry for idempotent GETs.

``urlopen`` times out on socket inactivity. A job log that trickles bytes
resets that timer and can hold a staff tick until Lambda kills it. The body
is read with ``read1`` so the deadline is checked after each socket receive,
and a timed-out read becomes a snapshot error so one run cannot abort the
whole code tick. A retried GET waits briefly first; an immediate second
attempt usually meets the same gateway error.
"""

from __future__ import annotations

import http.client
import json
import time
from typing import Any
from urllib import error as urlerror

import board_deadline
from http_common import _close_http_error, _log_event, _read_http_error

_GET_RETRY_STATUSES = frozenset({500, 502, 503, 504})
# Long enough that a GitHub 502 is usually gone, short enough to stay inside a tick.
_GET_RETRY_PAUSE_SECONDS = 1.0


def _github():
    # Imported lazily so this module can load while board_github is still
    # initialising. Callers patch names on board_github.
    import board_github

    return board_github


def _next_chunk(resp: Any) -> tuple[bytes, bool]:
    """Next bytes, and whether this read consumed the whole body.

    ``read(size)`` blocks until ``size`` bytes arrive or the peer closes.
    A trickling log resets the socket timeout on every byte, so the deadline
    check between reads never runs. ``read1`` returns after one socket receive.
    """
    read1 = getattr(resp, "read1", None)
    reader = read1 if read1 is not None else resp.read
    try:
        return reader(65536), False
    except TypeError:
        # Test doubles implement read() with no size. A real response accepts it.
        return reader(), True


def _read_body(resp: Any, *, raw: bool, deadline: float) -> str:
    """Read in chunks and stop when ``deadline`` (monotonic) passes."""
    gh = _github()
    buf = bytearray()
    while True:
        if time.monotonic() >= deadline:
            raise gh.GitHubSnapshotError("GitHub API read exceeded the request timeout")
        chunk, one_shot = _next_chunk(resp)
        if chunk:
            buf.extend(chunk)
            if raw and len(buf) > gh.RAW_LOG_TAIL_BYTES:
                del buf[: -gh.RAW_LOG_TAIL_BYTES]
        if one_shot or not chunk:
            break
    return bytes(buf).decode("utf-8", errors="replace")


def _retryable_get(exc: Any) -> bool:
    if exc.status in _GET_RETRY_STATUSES:
        return True
    if exc.status is not None or exc.retry_after is not None:
        return False
    text = str(exc)
    return "transport error" in text or "exceeded the request timeout" in text or "invalid JSON" in text


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
    timeout: int | None = None,
) -> Any:
    gh = _github()
    if timeout is None:
        timeout = gh.HTTP_TIMEOUT_SECONDS
    attempts = 2 if method == "GET" else 1
    last: Any = None
    for attempt in range(attempts):
        try:
            return _request_once(method, path, body=body, accept=accept, timeout=timeout)
        except gh.GitHubSnapshotError as exc:
            last = exc
            if attempt + 1 < attempts and _retryable_get(exc):
                pause = board_deadline.remaining(_GET_RETRY_PAUSE_SECONDS)
                if pause:
                    time.sleep(pause)
                continue
            raise
    assert last is not None
    raise last


def _request_once(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None,
    accept: str,
    timeout: int,
) -> Any:
    gh = _github()
    url = path if path.startswith("http") else f"{gh.API_ORIGIN}{path}"
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lxsoftware-admin-board",
    }
    token = gh._token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = gh.urlrequest.Request(url, data=data, method=method, headers=headers)  # noqa: S310 - fixed API origin
    raw = accept.endswith("raw") or accept == "application/vnd.github.diff"
    granted = board_deadline.remaining(timeout)
    if granted is None:
        granted = float(timeout)
    try:
        with gh._urlopen(req, timeout=granted) as resp:  # noqa: S310
            text = _read_body(resp, raw=raw, deadline=time.monotonic() + float(granted))
    except urlerror.HTTPError as exc:
        if exc.code == 404 and method == "GET" and _close_http_error(exc):
            return None
        wait = gh._rate_limit_wait_seconds(exc)
        if wait is not None:
            _log_event("warning", tag="board_github_rate_limited", status=exc.code, retryAfter=wait, path=path[:120])
            raise gh.GitHubSnapshotError(
                f"GitHub rate limit; retry after {wait}s", status=exc.code, retry_after=wait
            ) from _close_http_error(exc)
        detail = ""
        try:
            payload = json.loads(_read_http_error(exc).decode("utf-8", errors="replace"))
            detail = str(payload.get("message") or "") if isinstance(payload, dict) else ""
        except Exception:  # pragma: no cover - defensive
            detail = ""
        suffix = f": {detail[:200]}" if detail else ""
        if exc.code in (401, 403) and not token:
            suffix += " (no GitHub token configured; anonymous access is rate-limited and cannot write)"
        raise gh.GitHubSnapshotError(
            f"GitHub API returned status {exc.code} for {method} {path}{suffix}", status=exc.code
        ) from exc
    except urlerror.URLError as exc:
        raise gh.GitHubSnapshotError(f"GitHub API transport error: {exc.reason}") from exc
    except (http.client.HTTPException, TimeoutError, OSError) as exc:
        # IncompleteRead and RemoteDisconnected escape urlopen during resp.read.
        raise gh.GitHubSnapshotError(f"GitHub API transport error: {exc}") from exc
    if accept.endswith("raw") or accept == "application/vnd.github.diff":
        return text
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise gh.GitHubSnapshotError("GitHub API returned invalid JSON") from exc
