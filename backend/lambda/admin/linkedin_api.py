"""LinkedIn OAuth and the versioned Posts API.

The admin Lambda calls this only after the owner has connected. Tokens stay
in the records table under ``LINKEDIN#`` and are never returned to the SPA.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_VERSION = "202609"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
REST = "https://api.linkedin.com/rest"
PROFILE_SCOPES = "openid profile w_member_social"
ORGANIZATION_SCOPES = (
    "openid profile w_member_social w_organization_social "
    "r_organization_social rw_organization_admin"
)
COMMENTARY_MAX = 3000
SECRET_ID_ENV = "LINKEDIN_APP_SECRET_ID"
METRICS_TIMEOUT_SECONDS = 8

_transport = None
_credentials_cache: dict[str, Any] = {"at": 0.0, "status": ""}
_PROTECTED = re.compile(r"https?://\S+|#[^\s#]+")
_RESERVED = set("\\()[]{}@|~_<>*")


class LinkedInApiError(RuntimeError):
    """LinkedIn rejected a call, or the app credentials are missing."""

    def __init__(self, message: str, *, status: int | None = None, counts_attempt: bool = True) -> None:
        super().__init__(message)
        self.status = status
        self.counts_attempt = counts_attempt


def set_transport_for_tests(fn) -> None:
    global _transport
    _transport = fn


def _call(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    *,
    timeout: float = 20,
) -> tuple[int, dict[str, str], bytes]:
    if _transport is not None:
        status, response_headers, payload = _transport(method, url, headers, body)
        return int(status), {str(k).lower(): str(v) for k, v in dict(response_headers).items()}, payload or b""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_headers = {key.lower(): value for key, value in response.headers.items()}
            return int(response.status), raw_headers, response.read()
    except urllib.error.HTTPError as exc:
        raw_headers = {key.lower(): value for key, value in exc.headers.items()} if exc.headers else {}
        return int(exc.code), raw_headers, exc.read() or b""
    except urllib.error.URLError as exc:
        raise LinkedInApiError("LinkedIn could not be reached.") from exc


def _json_body(payload: bytes) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _error_message(payload: bytes, status: int) -> str:
    parsed = _json_body(payload)
    text = str(parsed.get("error_description") or parsed.get("message") or parsed.get("error") or "").strip()
    if not text:
        text = f"LinkedIn returned {status}."
    return text[:240]


def _expect(status: int, payload: bytes, *, ok: set[int]) -> dict[str, Any]:
    if status not in ok:
        raise LinkedInApiError(_error_message(payload, status), status=status)
    return _json_body(payload)


def load_credentials() -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` from the LinkedIn app secret."""
    secret_id = (os.environ.get(SECRET_ID_ENV) or "").strip()
    if not secret_id:
        raise LinkedInApiError("LinkedIn app credentials are not configured.", counts_attempt=False)
    from admin_runtime import _get_secretsmanager_client
    from secret_store import read_secret_raw

    raw = read_secret_raw(_get_secretsmanager_client(), secret_id, what="LinkedIn app")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LinkedInApiError("LinkedIn app secret is not JSON.", counts_attempt=False) from exc
    if not isinstance(parsed, dict):
        raise LinkedInApiError("LinkedIn app secret is not JSON.", counts_attempt=False)
    client_id = str(parsed.get("clientId") or "").strip()
    client_secret = str(parsed.get("clientSecret") or "").strip()
    if not client_id or client_id == "replace-me" or not client_secret:
        raise LinkedInApiError("LinkedIn app credentials are not configured.", counts_attempt=False)
    return client_id, client_secret


def reset_credentials_cache_for_tests() -> None:
    _credentials_cache["at"] = 0.0
    _credentials_cache["status"] = ""


def credentials_status() -> str:
    """``ready``, ``missing``, or ``unreadable``. Cached for a minute."""
    now = time.monotonic()
    if _credentials_cache["status"] and now - float(_credentials_cache["at"]) < 60:
        return str(_credentials_cache["status"])
    status = "ready"
    try:
        load_credentials()
    except LinkedInApiError as exc:
        status = "missing" if "not configured" in str(exc) else "unreadable"
    except Exception:  # noqa: BLE001 — overview must load when Secrets Manager fails
        status = "unreadable"
    _credentials_cache["at"] = now
    _credentials_cache["status"] = status
    return status


def app_configured() -> bool:
    return credentials_status() == "ready"


def redirect_uri(origin: str) -> str:
    return origin.rstrip("/") + "/lx-software/linkedin/callback"


def authorize_url(*, client_id: str, redirect: str, state: str, include_organizations: bool = False) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "state": state,
            "scope": ORGANIZATION_SCOPES if include_organizations else PROFILE_SCOPES,
        }
    )
    return f"{AUTH_URL}?{query}"


def _form(fields: dict[str, str]) -> bytes:
    return urllib.parse.urlencode(fields).encode("utf-8")


def _token_request(fields: dict[str, str]) -> dict[str, Any]:
    status, _headers, payload = _call(
        "POST",
        TOKEN_URL,
        {"Content-Type": "application/x-www-form-urlencoded"},
        _form(fields),
    )
    return _expect(status, payload, ok={200})


def exchange_code(*, client_id: str, client_secret: str, code: str, redirect: str) -> dict[str, Any]:
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )


def refresh_access_token(*, client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    return _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )


def _api_headers(token: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def userinfo(token: str) -> dict[str, str]:
    status, _headers, payload = _call("GET", USERINFO_URL, {"Authorization": f"Bearer {token}"}, None)
    parsed = _expect(status, payload, ok={200})
    member_id = str(parsed.get("sub") or "").strip()
    if not member_id:
        raise LinkedInApiError("LinkedIn did not return a member id.")
    return {"memberId": member_id, "memberName": str(parsed.get("name") or "").strip()}


def list_organizations(token: str) -> list[dict[str, str]]:
    """Pages the member administers. A 403 leaves the profile connection usable."""
    query = urllib.parse.urlencode(
        {"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"}
    )
    status, _headers, payload = _call(
        "GET",
        f"{REST}/organizationAcls?{query}",
        _api_headers(token),
        None,
    )
    if status == 403:
        return []
    parsed = _expect(status, payload, ok={200})
    found: list[dict[str, str]] = []
    elements = parsed.get("elements") if isinstance(parsed.get("elements"), list) else []
    for row in elements:
        if not isinstance(row, dict):
            continue
        urn = str(row.get("organization") or "")
        org_id = urn.rsplit(":", 1)[-1].strip()
        if not org_id or any(item["id"] == org_id for item in found):
            continue
        found.append({"id": org_id, "name": _organization_name(token, org_id)})
        if len(found) >= 10:
            break
    return found


def _organization_name(token: str, org_id: str) -> str:
    status, _headers, payload = _call(
        "GET",
        f"{REST}/organizations/{urllib.parse.quote(org_id, safe='')}",
        _api_headers(token),
        None,
    )
    if status != 200:
        return f"Page {org_id}"
    parsed = _json_body(payload)
    name = str(parsed.get("localizedName") or "").strip()
    return name or f"Page {org_id}"


def _escape_segment(text: str) -> str:
    out: list[str] = []
    for char in text:
        if char in _RESERVED:
            out.append("\\")
        out.append(char)
    return "".join(out)


def escape_commentary(text: str) -> str:
    """Escape little text outside URLs and hashtags so links stay clickable."""
    parts: list[str] = []
    last = 0
    for match in _PROTECTED.finditer(text):
        parts.append(_escape_segment(text[last : match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_escape_segment(text[last:]))
    return "".join(parts)


def commentary(body: str, hashtags: list[str]) -> str:
    text = (body or "").strip()
    extras: list[str] = []
    folded = text.lower()
    for tag in hashtags:
        cleaned = str(tag).strip().lstrip("#")
        if not cleaned:
            continue
        token = "#" + cleaned
        if token.lower() not in folded:
            extras.append(token)
    if extras:
        text = f"{text}\n\n{' '.join(extras)}"
    escaped = escape_commentary(text)
    if len(escaped) > COMMENTARY_MAX:
        raise LinkedInApiError(
            f"The post is {len(escaped)} characters after hashtags and formatting. "
            f"LinkedIn allows {COMMENTARY_MAX}."
        )
    return escaped


def author_urn(connection: dict[str, Any]) -> str:
    if str(connection.get("channel") or "") == "page":
        org_id = str(connection.get("organizationId") or "").strip()
        if not org_id:
            raise LinkedInApiError("Choose a company page before posting.", counts_attempt=False)
        return f"urn:li:organization:{org_id}"
    member_id = str(connection.get("memberId") or "").strip()
    if not member_id:
        raise LinkedInApiError("LinkedIn is not connected.", counts_attempt=False)
    return f"urn:li:person:{member_id}"


def create_post(token: str, author: str, text: str, *, image_urn: str = "") -> str:
    document: dict[str, Any] = {
        "author": author,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        document["content"] = {"media": {"id": image_urn}}
    status, headers, payload = _call(
        "POST",
        f"{REST}/posts",
        _api_headers(token, json_body=True),
        json.dumps(document).encode("utf-8"),
    )
    _expect(status, payload, ok={201})
    urn = str(headers.get("x-restli-id") or _json_body(payload).get("id") or "").strip()
    if not urn:
        raise LinkedInApiError("LinkedIn did not return a post id.")
    return urn


def create_comment(token: str, post_urn: str, actor: str, text: str) -> None:
    encoded = urllib.parse.quote(post_urn, safe="")
    document = {"actor": actor, "object": post_urn, "message": {"text": text}}
    status, _headers, payload = _call(
        "POST",
        f"{REST}/socialActions/{encoded}/comments",
        _api_headers(token, json_body=True),
        json.dumps(document).encode("utf-8"),
    )
    _expect(status, payload, ok={201})


def upload_image(token: str, owner: str, data: bytes) -> str:
    status, _headers, payload = _call(
        "POST",
        f"{REST}/images?action=initializeUpload",
        _api_headers(token, json_body=True),
        json.dumps({"initializeUploadRequest": {"owner": owner}}).encode("utf-8"),
    )
    parsed = _expect(status, payload, ok={200})
    value = parsed.get("value") if isinstance(parsed.get("value"), dict) else {}
    upload_url = str(value.get("uploadUrl") or "")
    image_urn = str(value.get("image") or "")
    if not upload_url or not image_urn:
        raise LinkedInApiError("LinkedIn did not return an image upload.")
    put_status, _put_headers, put_payload = _call(
        "PUT",
        upload_url,
        {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
        data,
    )
    if put_status not in {200, 201}:
        raise LinkedInApiError(_error_message(put_payload, put_status), status=put_status)
    return image_urn


def social_counts(token: str, post_urn: str) -> dict[str, int]:
    encoded = urllib.parse.quote(post_urn, safe="")
    status, _headers, payload = _call(
        "GET",
        f"{REST}/socialActions/{encoded}",
        _api_headers(token),
        None,
        timeout=METRICS_TIMEOUT_SECONDS,
    )
    parsed = _expect(status, payload, ok={200})
    likes = parsed.get("likesSummary") if isinstance(parsed.get("likesSummary"), dict) else {}
    comments = parsed.get("commentsSummary") if isinstance(parsed.get("commentsSummary"), dict) else {}
    return {
        "reactions": int(likes.get("totalLikes") or 0),
        "comments": int(comments.get("aggregatedTotalComments") or comments.get("totalFirstLevelComments") or 0),
    }


def page_impressions(token: str, organization_id: str, post_urn: str) -> int | None:
    org = urllib.parse.quote(f"urn:li:organization:{organization_id}", safe="")
    encoded = urllib.parse.quote(post_urn, safe="")
    # Share statistics take a share URN or a ugcPost URN, not both.
    key = "ugcPosts" if ":ugcPost:" in post_urn else "shares"
    status, _headers, payload = _call(
        "GET",
        f"{REST}/organizationalEntityShareStatistics?q=organizationalEntity"
        f"&organizationalEntity={org}&{key}=List({encoded})",
        _api_headers(token),
        None,
        timeout=METRICS_TIMEOUT_SECONDS,
    )
    if status != 200:
        return None
    elements = _json_body(payload).get("elements")
    if not isinstance(elements, list) or not elements or not isinstance(elements[0], dict):
        return None
    stats = elements[0].get("totalShareStatistics")
    if not isinstance(stats, dict) or "impressionCount" not in stats:
        return None
    try:
        return int(stats["impressionCount"])
    except (TypeError, ValueError):
        return None
