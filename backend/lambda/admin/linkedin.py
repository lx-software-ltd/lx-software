"""HTTP and scheduled workers for the LX Software LinkedIn tab.

Drafts, the share box, and — when ``LINKEDIN_PUBLISH_ENABLED`` is true — the
LinkedIn Posts API. A due slot posts as the connected member or company page,
then adds the first comment and refreshes reaction counts.
"""

from __future__ import annotations

import base64
import os
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import board_async
import board_store
import linkedin_api
import linkedin_draft
import linkedin_image
import linkedin_store
from http_common import _audit, _json_response, _log_event, _parse_json_body
from linkedin_api import LinkedInApiError
from linkedin_store import HKT, LinkedInError
from openrouter_client import OpenRouterError

PREFIX = "/lx-software/linkedin"

_sesv2: Any = None


def _ses_client() -> Any:
    global _sesv2
    if _sesv2 is None:
        import boto3

        _sesv2 = boto3.client("sesv2")
    return _sesv2


def reset_ses_client_for_tests() -> None:
    global _sesv2
    _sesv2 = None


def notify_from_address() -> str:
    domain = (os.environ.get("INBOUND_MAIL_DOMAIN") or "inbound.lx-software.com").strip()
    return f"linkedin@{domain}"


def send_notice(to_address: str, subject: str, body: str) -> bool:
    address = str(to_address or "").strip()
    if not address:
        return False
    try:
        _ses_client().send_email(
            FromEmailAddress=notify_from_address(),
            Destination={"ToAddresses": [address]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )
    except Exception as exc:  # noqa: BLE001 — a missed note must not fail the job
        _log_event("warning", tag="linkedin_notice_failed", error=str(exc)[:300])
        return False
    _log_event("info", tag="linkedin_notice_sent", subject=subject[:80])
    return True


def _admin_origin() -> str:
    return (os.environ.get("ADMIN_WEB_ORIGIN") or "https://admin.lx-software.com").rstrip("/")


def _require_enabled():
    if linkedin_store.feature_enabled():
        return None
    return _json_response(403, {"message": "LinkedIn is turned off.", "reason": "linkedin_disabled"})


def _table():
    return board_store.records_table()


def _parts(path: str) -> list[str]:
    rest = path[len(PREFIX) :] if path.startswith(PREFIX) else path
    return [part for part in rest.split("/") if part]


def handle_http(event: dict[str, Any], method: str, path: str, user_sub: str | None) -> dict[str, Any]:
    parts = _parts(path)
    if not parts and method == "GET":
        return _json_response(200, linkedin_store.overview(_table()))
    if parts == ["settings"] and method == "PUT":
        blocked = _require_enabled()
        if blocked:
            return blocked
        try:
            settings = linkedin_store.save_settings(_table(), _parse_json_body(event))
        except LinkedInError as exc:
            return _json_response(400, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_SETTINGS", "state", event)
        return _json_response(200, {"settings": settings})
    if parts == ["posts"] and method == "GET":
        status = (parse_qs(event.get("rawQueryString") or "").get("status") or [""])[0]
        rows = linkedin_store.list_posts(_table(), status=status or None)
        return _json_response(200, {"items": [linkedin_store.public_post(row) for row in rows]})
    if parts == ["posts"] and method == "POST":
        blocked = _require_enabled()
        if blocked:
            return blocked
        try:
            doc = linkedin_store.create_post(_table(), _parse_json_body(event))
        except LinkedInError as exc:
            return _json_response(400, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_POST_CREATE", str(doc["postId"]), event)
        return _json_response(201, {"item": linkedin_store.public_post(doc)})
    if len(parts) == 2 and parts[0] == "posts" and method == "PUT":
        blocked = _require_enabled()
        if blocked:
            return blocked
        try:
            doc = linkedin_store.update_post(_table(), parts[1], _parse_json_body(event))
        except LinkedInError as exc:
            status = 404 if str(exc) == "post not found" else 400
            return _json_response(status, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_POST_UPDATE", parts[1], event)
        return _json_response(200, {"item": linkedin_store.public_post(doc)})
    if parts and parts[0] == "character":
        return _character(event, method, parts, user_sub)
    if len(parts) == 4 and parts[0] == "posts" and parts[2] == "image" and parts[3] == "regenerate":
        return _image_regenerate(event, method, parts[1], user_sub)
    if len(parts) == 3 and parts[0] == "posts" and parts[2] == "image":
        return _image(event, method, parts[1], user_sub)
    if len(parts) == 3 and parts[0] == "posts" and method == "POST":
        return _post_action(event, parts[1], parts[2], user_sub)
    if parts == ["ideas"] and method == "GET":
        return _json_response(200, {"items": linkedin_store.list_ideas(_table())})
    if parts == ["ideas"] and method == "POST":
        blocked = _require_enabled()
        if blocked:
            return blocked
        body = _parse_json_body(event)
        try:
            doc = linkedin_store.create_idea(
                _table(),
                str(body.get("text") or ""),
                str(body.get("pillar") or ""),
            )
        except LinkedInError as exc:
            return _json_response(400, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_IDEA_CREATE", str(doc["ideaId"]), event)
        return _json_response(201, {"item": doc})
    if len(parts) == 2 and parts[0] == "ideas" and method == "DELETE":
        blocked = _require_enabled()
        if blocked:
            return blocked
        linkedin_store.delete_idea(_table(), parts[1])
        _audit(user_sub, "LINKEDIN_IDEA_DELETE", parts[1], event)
        return _json_response(200, {"deleted": parts[1]})
    if parts == ["connect"] and method == "POST":
        return _connect(event, user_sub)
    if parts == ["oauth", "exchange"] and method == "POST":
        return _exchange(event, user_sub)
    if parts == ["disconnect"] and method == "POST":
        return _disconnect(event, user_sub)
    if parts == ["connection", "refresh"] and method == "POST":
        return _refresh_organizations(event, user_sub)
    if parts == ["connection"] and method == "PUT":
        return _connection(event, user_sub)
    if parts == ["generate"] and method == "POST":
        return _generate(event, user_sub)
    if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
        table = _table()
        doc = linkedin_store.get_job(table, parts[1])
        if not doc:
            return _json_response(404, {"message": "Job not found"})
        doc = linkedin_store.expire_character_job(table, doc)
        return _json_response(200, {"job": _public_job(doc)})
    return _json_response(404, {"message": "Not found"})


def _post_action(event: dict[str, Any], post_id: str, action: str, user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    table = _table()
    try:
        if action == "approve":
            doc = linkedin_store.approve_post(table, post_id, user_sub or "")
        elif action == "unapprove":
            doc = linkedin_store.unapprove_post(table, post_id)
        elif action == "archive":
            doc = linkedin_store.archive_post(table, post_id)
        elif action == "mark-posted":
            body = _parse_json_body(event)
            doc = linkedin_store.mark_posted(table, post_id, str(body.get("url") or ""))
        elif action == "regenerate":
            return _regenerate(event, table, post_id, user_sub)
        else:
            return _json_response(404, {"message": "Not found"})
    except LinkedInError as exc:
        status = 404 if str(exc) == "post not found" else 400
        return _json_response(status, {"message": str(exc)})
    _audit(user_sub, f"LINKEDIN_POST_{action.upper()}", post_id, event)
    return _json_response(200, {"item": linkedin_store.public_post(doc)})


def _generate(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _parse_json_body(event)
    payload = {
        "count": body.get("count"),
        "pillar": str(body.get("pillar") or ""),
        "ideaIds": body.get("ideaIds") if isinstance(body.get("ideaIds"), list) else [],
        "postId": "",
    }
    return _queue(event, payload, user_sub)


def _regenerate(event: dict[str, Any], table: Any, post_id: str, user_sub: str | None) -> dict[str, Any]:
    doc = linkedin_store.get_post(table, post_id)
    if not doc:
        return _json_response(404, {"message": "post not found"})
    payload = {
        "count": 1,
        "pillar": str(doc.get("pillar") or ""),
        "ideaIds": [doc["ideaId"]] if doc.get("ideaId") else [],
        "postId": post_id,
    }
    return _queue(event, payload, user_sub)


def _queue(event: dict[str, Any], payload: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    table = _table()
    job = linkedin_store.new_job(table, "generate", payload)
    accepted = board_async.try_invoke_event(
        {"internal": "linkedin_generate", "jobId": job["jobId"]}
    )
    if not accepted:
        job["status"] = "failed"
        job["error"] = "Could not queue generation."
        linkedin_store.put_job(table, job)
        return _json_response(503, {"message": job["error"], "job": _public_job(job)})
    _audit(user_sub, "LINKEDIN_GENERATE", job["jobId"], event)
    return _json_response(202, {"job": _public_job(job)})


def _public_job(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": doc.get("jobId"),
        "status": doc.get("status"),
        "postIds": list(doc.get("postIds") or []),
        "error": doc.get("error") or "",
    }


def _fail_job(table: Any, job: dict[str, Any] | None, message: str) -> None:
    if not job:
        return
    job["status"] = "failed"
    job["error"] = message
    linkedin_store.put_job(table, job)


def handle_generate(event: dict[str, Any] | None = None) -> dict[str, Any]:
    event = event or {}
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    job_id = str(event.get("jobId") or "")
    if not job_id:
        return {"skipped": "missing_job"}
    table = _table()
    job = linkedin_store.get_job(table, job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    payload = dict(job.get("payload") or {})
    job["status"] = "running"
    linkedin_store.put_job(table, job)
    replacing = str(payload.get("postId") or "")
    try:
        count = payload.get("count")
        result = linkedin_draft.generate_drafts(
            table,
            count=1 if replacing else (int(count) if isinstance(count, int) else None),
            pillar=str(payload.get("pillar") or "") or None,
            idea_ids=[str(item) for item in payload.get("ideaIds") or []],
            job_id=job_id,
            persist=not replacing,
        )
        if replacing and result["posts"]:
            _replace_post(table, replacing, result["posts"][0])
            updated = linkedin_store.get_post(table, replacing) or {}
            result = {**result, "posts": [linkedin_store.public_post(updated)]}
    except (LinkedInError, linkedin_draft.DraftError, OpenRouterError) as exc:
        _log_event("warning", tag="linkedin_generate_failed", error=str(exc)[:300])
        _fail_job(table, job, str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a worker error must not leave the job running
        _log_event("error", tag="linkedin_generate_failed", error=str(exc)[:300])
        _fail_job(table, job, "Generation failed.")
        return {"ok": False, "error": "Generation failed."}
    job["status"] = "done"
    job["postIds"] = [row["postId"] for row in result["posts"]]
    job["error"] = "; ".join(result["errors"])
    linkedin_store.put_job(table, job)
    _notify_ready(table, len(result["posts"]))
    return {"ok": True, "postIds": [row.get("postId") for row in result["posts"]], "error": job["error"]}


def _replace_post(table: Any, post_id: str, generated: dict[str, Any]) -> None:
    """Regenerate keeps the same id and drops approval."""
    current = linkedin_store.get_post(table, post_id)
    if not current:
        return
    updated = linkedin_store.update_post(
        table,
        post_id,
        {
            "body": generated.get("body") or "",
            "firstComment": generated.get("firstComment") or "",
            "hashtags": generated.get("hashtags") or [],
            "pillar": generated.get("pillar") or current.get("pillar"),
        },
    )
    settings = linkedin_store.load_settings(table)
    generation = dict(updated.get("generation") or {})
    generation["model"] = linkedin_draft.draft_model(settings)
    generation["voiceHash"] = linkedin_draft.voice_hash(settings)
    updated["generation"] = generation
    linkedin_store.put_post(table, updated)
    if settings.get("imagesEnabled"):
        try:
            linkedin_image.queue_for_post(
                table,
                post_id,
                scene=str(generated.get("imageScene") or ""),
                caption=str(generated.get("imageCaption") or ""),
                expression=str(generated.get("imageExpression") or ""),
                force=True,
            )
        except LinkedInError as exc:
            _log_event("warning", tag="linkedin_image_enqueue_failed", error=str(exc)[:300])
        except Exception as exc:  # noqa: BLE001 — the rewritten draft is already saved
            _log_event("warning", tag="linkedin_image_enqueue_failed", error=str(exc)[:300])


def _notify_ready(table: Any, count: int) -> None:
    if count < 1:
        return
    settings = linkedin_store.load_settings(table)
    address = str(settings.get("notifyEmail") or "")
    if not address:
        return
    origin = _admin_origin()
    send_notice(
        address,
        "LinkedIn drafts are ready",
        (
            f"{count} new draft{'s' if count != 1 else ''} {'are' if count != 1 else 'is'} "
            f"waiting for review.\n\n{origin}/lx-software?tab=linkedin\n"
        ),
    )


def handle_weekly_plan(event: dict[str, Any] | None = None) -> dict[str, Any]:
    del event
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    table = _table()
    today = linkedin_store._as_hkt().date().isoformat()
    if linkedin_store.load_plan_date(table) == today:
        return {"skipped": "already_ran"}
    try:
        result = linkedin_draft.generate_drafts(table)
    except (LinkedInError, linkedin_draft.DraftError, OpenRouterError) as exc:
        _log_event("warning", tag="linkedin_weekly_plan_failed", error=str(exc)[:300])
        return {"ok": False, "error": str(exc)}
    linkedin_store.save_plan_date(table, today)
    _notify_ready(table, len(result["posts"]))
    return {"ok": True, "created": len(result["posts"])}


def _connect(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    try:
        client_id, _secret = linkedin_api.load_credentials()
    except LinkedInApiError as exc:
        return _json_response(503, {"message": str(exc)})
    body = _parse_json_body(event)
    include_organizations = bool(body.get("includeOrganizations"))
    state = secrets.token_urlsafe(18)
    linkedin_store.save_oauth_state(
        _table(),
        state,
        user_sub or "",
        include_organizations=include_organizations,
    )
    url = linkedin_api.authorize_url(
        client_id=client_id,
        redirect=linkedin_api.redirect_uri(_admin_origin()),
        state=state,
        include_organizations=include_organizations,
    )
    _audit(user_sub, "LINKEDIN_CONNECT", "pages" if include_organizations else "profile", event)
    return _json_response(200, {"url": url})


def _exchange(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _parse_json_body(event)
    code = str(body.get("code") or "").strip()
    state = str(body.get("state") or "").strip()
    if not code or not state:
        return _json_response(400, {"message": "code and state are required"})
    table = _table()
    try:
        owner, include_organizations = linkedin_store.consume_oauth_state(table, state)
        if owner and user_sub and owner != user_sub:
            raise LinkedInError("That LinkedIn sign-in belongs to another session.")
        client_id, client_secret = linkedin_api.load_credentials()
        token = linkedin_api.exchange_code(
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect=linkedin_api.redirect_uri(_admin_origin()),
        )
        access = str(token.get("access_token") or "")
        if not access:
            raise LinkedInApiError("LinkedIn did not return an access token.")
        profile = linkedin_api.userinfo(access)
        organizations: list[dict[str, str]] = []
        if include_organizations:
            try:
                organizations = linkedin_api.list_organizations(access)
            except LinkedInApiError as exc:
                _log_event("warning", tag="linkedin_organizations_failed", error=str(exc)[:200])
        previous = linkedin_store.load_connection(table)
        channel = "page" if include_organizations and previous.get("channel") == "page" else "profile"
        organization_id = str(previous.get("organizationId") or "") if channel == "page" else ""
        organization_name = str(previous.get("organizationName") or "") if channel == "page" else ""
        if channel == "page" and not any(row["id"] == organization_id for row in organizations):
            channel = "profile"
            organization_id = ""
            organization_name = ""
        linkedin_store.save_connection(
            table,
            {
                "accessToken": access,
                "refreshToken": str(token.get("refresh_token") or previous.get("refreshToken") or ""),
                "tokenExpiresAt": _token_expiry(token),
                "memberId": profile["memberId"],
                "memberName": profile["memberName"],
                "channel": channel,
                "organizationId": organization_id,
                "organizationName": organization_name,
                "organizations": organizations,
                "includeOrganizations": include_organizations,
                "connectedAt": board_store.now_iso(),
            },
        )
    except (LinkedInError, LinkedInApiError) as exc:
        return _json_response(400, {"message": str(exc)})
    _audit(user_sub, "LINKEDIN_CONNECT", "exchange", event)
    return _json_response(200, {"connection": linkedin_store.public_connection(linkedin_store.load_connection(table))})


def _disconnect(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    linkedin_store.clear_connection(_table())
    _audit(user_sub, "LINKEDIN_DISCONNECT", "state", event)
    return _json_response(200, {"connection": linkedin_store.public_connection({})})


def _connection(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _parse_json_body(event)
    try:
        connection = linkedin_store.set_connection_target(
            _table(),
            str(body.get("channel") or "profile"),
            str(body.get("organizationId") or ""),
        )
    except LinkedInError as exc:
        return _json_response(400, {"message": str(exc)})
    channel = str(body.get("channel") or "")
    organization_id = str(body.get("organizationId") or "")
    target = f"page:{organization_id}" if channel == "page" else "profile"
    _audit(user_sub, "LINKEDIN_CONNECTION", target, event)
    return _json_response(200, {"connection": connection})


def _refresh_organizations(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    table = _table()
    connection = linkedin_store.load_connection(table)
    if not connection:
        return _json_response(400, {"message": "LinkedIn is not connected."})
    if not connection.get("includeOrganizations"):
        return _json_response(
            400,
            {"message": "This connection is profile only. Disconnect and connect again with company pages included."},
        )
    try:
        token = _access_token(table, connection)
        organizations = linkedin_api.list_organizations(token)
    except (LinkedInError, LinkedInApiError) as exc:
        return _json_response(400, {"message": str(exc)})
    connection = linkedin_store.load_connection(table)
    connection["organizations"] = organizations
    if connection.get("channel") == "page" and not any(
        str(row.get("id") or "") == str(connection.get("organizationId") or "") for row in organizations
    ):
        connection["channel"] = "profile"
        connection["organizationId"] = ""
        connection["organizationName"] = ""
    linkedin_store.save_connection(table, connection)
    _audit(user_sub, "LINKEDIN_CONNECTION", "refresh", event)
    return _json_response(200, {"connection": linkedin_store.public_connection(connection)})


def handle_post_image(event: dict[str, Any] | None = None) -> dict[str, Any]:
    event = event or {}
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    post_id = str(event.get("postId") or "")
    if not post_id:
        return {"skipped": "missing_post"}
    return linkedin_image.render_post(_table(), post_id)


def handle_character_draw(event: dict[str, Any] | None = None) -> dict[str, Any]:
    event = event or {}
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    job_id = str(event.get("jobId") or "")
    table = _table()
    job = linkedin_store.get_job(table, job_id) if job_id else None
    if job:
        job["status"] = "running"
        job["startedAt"] = board_store.now_iso()
        linkedin_store.put_job(table, job)
    try:
        result = linkedin_image.draw_character(table)
    except Exception as exc:  # noqa: BLE001 — a draw that raises must not leave the job running
        _log_event("error", tag="linkedin_character_failed", error=str(exc)[:300])
        result = {"ok": False, "error": "The character sheet failed."}
    if job:
        job["status"] = "done" if result.get("ok") else "failed"
        job["error"] = "" if result.get("ok") else str(result.get("error") or "The character sheet failed.")
        linkedin_store.put_job(table, job)
    return result


def _character(event: dict[str, Any], method: str, parts: list[str], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked and method != "GET":
        return blocked
    table = _table()
    try:
        if parts == ["character"] and method == "GET":
            return _json_response(200, linkedin_store.public_character(linkedin_store.load_character(table)))
        if parts == ["character", "photo"] and method == "GET":
            loaded = linkedin_store.load_character_photo(table)
            if not loaded:
                return _json_response(404, {"message": "No photo stored."})
            return _json_response(200, {"contentType": loaded[0], "dataBase64": base64.b64encode(loaded[1]).decode("ascii")})
        if parts == ["character", "photo"] and method == "POST":
            content_type, data = _image_body(event)
            stored = linkedin_store.save_character_photo(table, content_type, data)
            _audit(user_sub, "LINKEDIN_CHARACTER_PHOTO", "state", event)
            return _json_response(200, stored)
        if parts == ["character", "photo"] and method == "DELETE":
            stored = linkedin_store.delete_character_photo(table)
            _audit(user_sub, "LINKEDIN_CHARACTER_PHOTO", "state", event)
            return _json_response(200, stored)
        if parts == ["character", "sheet"] and method == "GET":
            loaded = linkedin_store.load_character_sheet()
            if not loaded:
                return _json_response(404, {"message": "No character sheet yet."})
            return _json_response(200, {"contentType": loaded[0], "dataBase64": base64.b64encode(loaded[1]).decode("ascii")})
        if parts == ["character", "draw"] and method == "POST":
            if not linkedin_store.load_character_photo(table):
                return _json_response(400, {"message": "Upload a photo first."})
            job = linkedin_store.new_job(table, "character", {})
            accepted = board_async.try_invoke_event({"internal": "linkedin_character", "jobId": job["jobId"]})
            if not accepted:
                job["status"] = "failed"
                job["error"] = "Could not queue the character sheet."
                linkedin_store.put_job(table, job)
                return _json_response(503, {"message": job["error"], "job": _public_job(job)})
            _audit(user_sub, "LINKEDIN_CHARACTER_DRAW", job["jobId"], event)
            return _json_response(202, {"job": _public_job(job)})
        if len(parts) == 3 and parts[1] == "candidates" and method == "GET":
            if not linkedin_store.valid_candidate_id(parts[2]):
                return _json_response(400, {"message": "That candidate is not one of the four drawings."})
            loaded = linkedin_store.load_character_candidate(parts[2])
            if not loaded:
                return _json_response(404, {"message": "That candidate is gone."})
            return _json_response(200, {"contentType": loaded[0], "dataBase64": base64.b64encode(loaded[1]).decode("ascii")})
        if parts == ["character", "choose"] and method == "POST":
            body = _parse_json_body(event)
            stored = linkedin_store.choose_character(table, str(body.get("candidateId") or ""))
            _audit(user_sub, "LINKEDIN_CHARACTER_CHOOSE", "state", event)
            return _json_response(200, stored)
    except LinkedInError as exc:
        return _json_response(400, {"message": str(exc)})
    return _json_response(404, {"message": "Not found"})


def _image_body(event: dict[str, Any]) -> tuple[str, bytes]:
    body = _parse_json_body(event)
    try:
        data = base64.b64decode(str(body.get("dataBase64") or ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise LinkedInError("The image is not valid base64.") from exc
    return str(body.get("contentType") or ""), data


def _image_regenerate(event: dict[str, Any], method: str, post_id: str, user_sub: str | None) -> dict[str, Any]:
    if method != "POST":
        return _json_response(404, {"message": "Not found"})
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _parse_json_body(event)
    try:
        doc = linkedin_image.queue_for_post(
            _table(),
            post_id,
            scene=str(body.get("scene") or ""),
            caption=str(body.get("caption") or ""),
            expression=str(body.get("expression") or ""),
        )
    except LinkedInError as exc:
        status = 409 if "already being drawn" in str(exc) else 404 if str(exc) == "post not found" else 400
        return _json_response(status, {"message": str(exc)})
    _audit(user_sub, "LINKEDIN_IMAGE_REGENERATE", post_id, event)
    return _json_response(202, {"item": linkedin_store.public_post(doc)})


def _image(event: dict[str, Any], method: str, post_id: str, user_sub: str | None) -> dict[str, Any]:
    if method == "GET":
        loaded = linkedin_store.load_post_image(post_id)
        if not loaded:
            return _json_response(404, {"message": "No picture stored."})
        return _json_response(
            200,
            {"contentType": loaded[0], "dataBase64": base64.b64encode(loaded[1]).decode("ascii")},
        )
    blocked = _require_enabled()
    if blocked:
        return blocked
    table = _table()
    try:
        if method == "DELETE":
            doc = linkedin_store.delete_post_image(table, post_id)
        elif method == "POST":
            body = _parse_json_body(event)
            try:
                data = base64.b64decode(str(body.get("dataBase64") or ""), validate=True)
            except (ValueError, TypeError) as exc:
                raise LinkedInError("The image is not valid base64.") from exc
            doc = linkedin_store.save_post_image(
                table,
                post_id,
                str(body.get("contentType") or ""),
                data,
            )
        else:
            return _json_response(404, {"message": "Not found"})
    except LinkedInError as exc:
        status = 404 if str(exc) == "post not found" else 400
        return _json_response(status, {"message": str(exc)})
    _audit(user_sub, "LINKEDIN_IMAGE", post_id, event)
    return _json_response(200, {"item": linkedin_store.public_post(doc)})


def _token_expiry(token: dict[str, Any]) -> str:
    try:
        seconds = int(token.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        seconds = 60 * 24 * 3600
    from timeutil import format_iso_millis

    return format_iso_millis(datetime.now(HKT) + timedelta(seconds=seconds))


def _access_token(table: Any, connection: dict[str, Any]) -> str:
    expires = linkedin_store._parse_slot(str(connection.get("tokenExpiresAt") or ""))
    if expires is not None and expires > datetime.now(HKT) + timedelta(minutes=2):
        return str(connection["accessToken"])
    refresh = str(connection.get("refreshToken") or "")
    if not refresh:
        raise LinkedInApiError("Reconnect LinkedIn. The access token expired.", counts_attempt=False)
    try:
        client_id, client_secret = linkedin_api.load_credentials()
    except LinkedInApiError:
        raise
    except Exception as exc:
        raise LinkedInApiError("LinkedIn app credentials could not be read.", counts_attempt=False) from exc
    try:
        token = linkedin_api.refresh_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh,
        )
    except LinkedInApiError as exc:
        raise LinkedInApiError("Reconnect LinkedIn. The access token expired.", counts_attempt=False) from exc
    access = str(token.get("access_token") or "")
    if not access:
        raise LinkedInApiError("Reconnect LinkedIn. The access token expired.", counts_attempt=False)
    connection["accessToken"] = access
    if token.get("refresh_token"):
        connection["refreshToken"] = str(token["refresh_token"])
    connection["tokenExpiresAt"] = _token_expiry(token)
    linkedin_store.save_connection(table, connection)
    return access


def _counts_attempt(exc: BaseException) -> bool:
    if isinstance(exc, LinkedInApiError):
        return exc.counts_attempt
    return True


def _reconnect_error(message: str) -> bool:
    text = message.lower()
    return any(
        phrase in text
        for phrase in (
            "reconnect linkedin",
            "not connected",
            "credentials are not configured",
            "credentials could not be read",
            "choose a company page",
        )
    )


def publish_one(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    """Post one approved draft. A comment failure still leaves the post published."""
    connection = linkedin_store.load_connection(table)
    if not connection:
        raise LinkedInApiError("LinkedIn is not connected.", counts_attempt=False)
    token = _access_token(table, connection)
    author = linkedin_api.author_urn(connection)
    text = linkedin_api.commentary(str(doc.get("body") or ""), list(doc.get("hashtags") or []))
    platform = doc.get("platform") if isinstance(doc.get("platform"), dict) else {}
    urn = str(platform.get("urn") or "")
    skipped_picture = False
    if not urn:
        image_meta = doc.get("image") if isinstance(doc.get("image"), dict) else None
        image_urn = ""
        alt_text = ""
        chosen = linkedin_store.publishable_image(image_meta)
        if chosen:
            loaded = linkedin_store.load_post_image(str(doc["postId"]))
            if not loaded:
                raise LinkedInApiError("The attached image could not be loaded.")
            image_urn = linkedin_api.upload_image(token, author, loaded[1])
            alt_text = linkedin_store.caption_alt(str(chosen.get("caption") or ""))
        elif image_meta and str(image_meta.get("status") or "") in ("pending", "failed"):
            skipped_picture = True
        urn = linkedin_api.create_post(token, author, text, image_urn=image_urn, alt_text=alt_text)
        doc = linkedin_store.remember_publish_urn(table, str(doc["postId"]), urn)
    channel = "page" if connection.get("channel") == "page" else "profile"
    organization_id = str(connection.get("organizationId") or "") if channel == "page" else ""
    updated = linkedin_store.mark_api_published(table, str(doc["postId"]), urn, channel, organization_id)
    if skipped_picture:
        updated["imageNote"] = "Posted without the picture; it was not ready."
        updated = linkedin_store.put_post(table, updated)
    comment = str(doc.get("firstComment") or "").strip()
    if comment:
        try:
            linkedin_api.create_comment(token, urn, author, comment)
        except LinkedInApiError as exc:
            updated["publishError"] = f"Posted. The first comment failed: {exc}"
            updated = linkedin_store.put_post(table, updated)
    return updated


def _refresh_metrics(table: Any, connection: dict[str, Any]) -> int:
    token = _access_token(table, connection)
    now = datetime.now(HKT)
    cutoff = now - timedelta(hours=6)
    oldest = now - timedelta(days=30)
    refreshed = 0
    for row in linkedin_store.list_posts(table, status="published", limit=80):
        if refreshed >= 5:
            break
        platform = row.get("platform") if isinstance(row.get("platform"), dict) else {}
        urn = str(platform.get("urn") or "")
        if not urn:
            continue
        published_at = linkedin_store._parse_slot(str(platform.get("publishedAt") or ""))
        if published_at is not None and published_at < oldest:
            continue
        previous = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        if previous.get("unavailable"):
            continue
        pulled = linkedin_store._parse_slot(str(previous.get("pulledAt") or ""))
        if pulled is not None and pulled > cutoff:
            continue
        try:
            counts = linkedin_api.social_counts(token, urn)
            impressions = None
            organization_id = str(platform.get("organizationId") or "")
            if row.get("channel") == "page" and organization_id:
                impressions = linkedin_api.page_impressions(token, organization_id, urn)
            metrics = {
                "reactions": counts["reactions"],
                "comments": counts["comments"],
                "impressions": impressions,
                "pulledAt": board_store.now_iso(),
                "unavailable": False,
            }
        except LinkedInApiError as exc:
            _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:200])
            metrics = {
                "reactions": int(previous.get("reactions") or 0),
                "comments": int(previous.get("comments") or 0),
                "impressions": previous.get("impressions") if "impressions" in previous else None,
                "pulledAt": board_store.now_iso(),
                "unavailable": exc.status == 403,
                "error": str(exc)[:200],
            }
        linkedin_store.save_post_metrics(table, str(row["postId"]), metrics)
        refreshed += 1
    return refreshed


def handle_publish_due(event: dict[str, Any] | None = None) -> dict[str, Any]:
    """Post due drafts when publishing is on, then remind the owner about the rest."""
    del event
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    table = _table()
    published = 0
    publish = ""
    if linkedin_store.publish_enabled():
        connection = linkedin_store.load_connection(table)
        if not connection:
            publish = "not_connected"
        else:
            publish = "posted"
            for row in linkedin_store.posts_ready_to_publish(table):
                post_id = str(row.get("postId") or "")
                try:
                    publish_one(table, row)
                    published += 1
                except Exception as exc:  # noqa: BLE001 — one failure must not skip the rest of the tick
                    _log_event("warning", tag="linkedin_publish_failed", error=str(exc)[:240])
                    try:
                        linkedin_store.record_publish_failure(
                            table,
                            post_id,
                            str(exc),
                            count_attempt=_counts_attempt(exc),
                        )
                    except LinkedInError:
                        _log_event("warning", tag="linkedin_publish_failed", error="post not found")
            try:
                fresh = linkedin_store.load_connection(table)
                if fresh:
                    _refresh_metrics(table, fresh)
            except Exception as exc:  # noqa: BLE001 — metrics must not fail the reminder
                _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:240])
    settings = linkedin_store.load_settings(table)
    address = str(settings.get("notifyEmail") or "")
    reminded = 0
    now = datetime.now(HKT)
    for row in linkedin_store.due_approved(table):
        post_id = str(row.get("postId") or "")
        attempts = int(row.get("publishAttempts") or 0)
        if attempts >= linkedin_store.PUBLISH_ATTEMPTS:
            continue
        failure = str(row.get("publishError") or "")
        slot = linkedin_store._parse_slot(str(row.get("slotAt") or ""))
        stale = slot is not None and now - slot > linkedin_store.PUBLISH_GRACE
        if (
            linkedin_store.publish_enabled()
            and publish != "not_connected"
            and not failure
            and not stale
            and attempts < linkedin_store.PUBLISH_ATTEMPTS
        ):
            continue
        if address:
            hook = linkedin_store.hook_text(str(row.get("body") or ""))[:120]
            if failure and _reconnect_error(failure):
                notice = (
                    f"Automatic posting failed: {failure}\n\n"
                    "Reconnect LinkedIn in Settings. This post stays approved.\n\n"
                )
                subject = "A LinkedIn post did not publish"
            elif failure:
                notice = (
                    f"Automatic posting failed: {failure}\n\n"
                    "It will be tried again. You can also use the share box and mark it posted.\n\n"
                )
                subject = "A LinkedIn post did not publish"
            elif publish == "not_connected":
                notice = "LinkedIn is not connected, so this post was not published. Connect it, or use the share box.\n\n"
                subject = "A LinkedIn post is due"
            elif linkedin_store.publish_enabled() and stale:
                notice = (
                    "This slot is more than three hours old, so it was not posted automatically. "
                    "Open it, use the share box, then mark it posted.\n\n"
                )
                subject = "A LinkedIn post is due"
            else:
                notice = "This post is due. Open it, use the share box, then mark it posted.\n\n"
                subject = "A LinkedIn post is due"
            send_notice(
                address,
                subject,
                f"{notice}{hook}\n\n{_admin_origin()}/lx-software?tab=linkedin&linkedin-post={post_id}\n",
            )
        linkedin_store.stamp_due_notified(table, post_id)
        reminded += 1
    gave_up = 0
    if linkedin_store.publish_enabled():
        for row in linkedin_store.posts_given_up(table):
            post_id = str(row.get("postId") or "")
            if address:
                hook = linkedin_store.hook_text(str(row.get("body") or ""))[:120]
                failure = str(row.get("publishError") or "")
                send_notice(
                    address,
                    "A LinkedIn post stopped retrying",
                    (
                        "Automatic posting failed three times and will not be tried again. "
                        "Use the share box and mark it posted.\n\n"
                        f"{failure}\n\n{hook}\n\n"
                        f"{_admin_origin()}/lx-software?tab=linkedin&linkedin-post={post_id}\n"
                    ),
                )
            linkedin_store.stamp_gave_up(table, post_id)
            gave_up += 1
    result: dict[str, Any] = {"ok": True, "reminded": reminded, "published": published, "gaveUp": gave_up}
    if publish:
        result["publish"] = publish
    return result
