#!/usr/bin/env python3
"""Check a deployed admin SPA config.json uses the API custom domain.

Reads ``ADMIN_SPA_CONFIG_URL``. When that variable is unset, the check is
skipped and the process exits 0. The script only GETs the URL. It does not
call AWS.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

CUSTOM_DOMAIN = "https://api.lx-software.com"
_KEYS = ("apiBaseUrl", "api_base_url")
_MAX_CONFIG_BYTES = 65536


def api_base(payload: Any) -> str:
    """Return the API origin from a SPA config object."""
    if not isinstance(payload, dict):
        raise ValueError("config is not a JSON object")
    for key in _KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/")
    raise ValueError("config has no API base")


def check_config(payload: Any) -> str | None:
    """Return an error message, or None when the base is the custom domain."""
    try:
        base = api_base(payload)
    except ValueError as exc:
        return str(exc)
    if "execute-api" in base or base != CUSTOM_DOMAIN:
        return f"API base {base} is not {CUSTOM_DOMAIN}"
    return None


def _https_url(url: str) -> str:
    """Reject any scheme other than https, including file."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"refusing a URL that is not https: {url}")
    return url


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect whose target is not https."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urlsplit(newurl).scheme != "https":
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                f"refusing redirect to a non-https URL: {newurl}",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_HttpsOnlyRedirect)


def _fetch(url: str) -> Any:
    req = urllib.request.Request(_https_url(url), method="GET")
    # The URL is https-only, and the opener refuses a non-https redirect.
    # It comes from the operator's environment.
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with _opener().open(req, timeout=10) as resp:  # nosec B310
        raw = resp.read(_MAX_CONFIG_BYTES + 1)
    if len(raw) > _MAX_CONFIG_BYTES:
        raise ValueError(f"config is larger than {_MAX_CONFIG_BYTES} bytes")
    return json.loads(raw.decode("utf-8"))


def main(
    environ: Mapping[str, str] | None = None,
    fetch: Callable[[str], Any] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    url = env.get("ADMIN_SPA_CONFIG_URL", "").strip()
    if not url:
        print("admin SPA config check skipped: ADMIN_SPA_CONFIG_URL is unset")
        return 0
    payload = (fetch or _fetch)(url)
    error = check_config(payload)
    if error:
        print(error, file=sys.stderr)
        return 1
    print(f"admin SPA API base is {CUSTOM_DOMAIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
