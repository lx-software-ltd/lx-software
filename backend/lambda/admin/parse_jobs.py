"""Admin API: parse jobs."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from botocore.exceptions import ClientError

import runtime
from admin_runtime import _get_lambda_client
from contract_constants import (
    PARSE_JOB_STALE_SECONDS_DEFAULT,
    PARSE_JOB_STUCK_SECONDS_DEFAULT,
    PARSE_JOB_TTL_SECONDS_DEFAULT,
)
from ddb_convert import _from_ddb_nested, _to_ddb_nested
from http_common import _log_event, _utc_iso_z
from runtime import PARSE_JOB_PK_PREFIX, logger


def _parse_job_key(job_id: str) -> dict[str, str]:
    return {"pk": f"{PARSE_JOB_PK_PREFIX}{job_id}", "sk": "META"}


def _job_expires_at_epoch() -> int:
    ttl = int(os.environ.get("PARSE_JOB_TTL_SECONDS", PARSE_JOB_TTL_SECONDS_DEFAULT))
    return int(time.time()) + ttl


def _parse_job_stale_cutoff_iso() -> str:
    sec = int(os.environ.get("PARSE_JOB_STALE_SECONDS", PARSE_JOB_STALE_SECONDS_DEFAULT))
    dt = datetime.now(timezone.utc) - timedelta(seconds=sec)
    return _utc_iso_z(dt)


def _parse_job_stuck_seconds() -> float:
    return float(os.environ.get("PARSE_JOB_STUCK_SECONDS", PARSE_JOB_STUCK_SECONDS_DEFAULT))


def _iso_to_utc_time(s: Any) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        return datetime.fromisoformat(t).astimezone(timezone.utc)
    except ValueError:
        return None


def _finalize_stuck_processing_job(
    table: Any, key: dict[str, str], doc: dict[str, Any]
) -> dict[str, Any]:
    """If processing exceeded the stuck threshold, mark failed (terminal for pollers)."""
    if doc.get("status") != "processing":
        return doc
    updated_at = _iso_to_utc_time(doc.get("updatedAt"))
    if updated_at is None:
        return doc
    age_sec = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_sec <= _parse_job_stuck_seconds():
        return doc
    fail_doc = {
        **doc,
        "status": "failed",
        "errorMessage": (
            "Statement parse did not complete in time. Reload the finance page "
            "and check whether lines were added, or try uploading again."
        ),
        "errorStatus": 504,
        "updatedAt": _utc_iso_z(datetime.now(timezone.utc)),
    }
    try:
        table.put_item(Item=_to_ddb_nested(fail_doc))
    except ClientError:
        return fail_doc
    _notify_parse_job_quietly(fail_doc)
    return fail_doc


def enqueue_parse_statement_async_job(
    *,
    house: str,
    s3_keys: list[str],
    owner_sub: str,
    api_request_id: str | None,
    source: str = "api",
    mortgage_only: bool = False,
    line_type_only: str | None = None,
) -> str:
    """Persist a pending PARSE_JOB and invoke the worker Lambda (async)."""
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    job_id = uuid.uuid4().hex
    created = _utc_iso_z(datetime.now(timezone.utc))
    job_item: dict[str, Any] = {
        **_parse_job_key(job_id),
        "jobId": job_id,
        "status": "pending",
        "house": house,
        "ownerSub": owner_sub,
        "s3Keys": s3_keys,
        "createdAt": created,
        "updatedAt": created,
        "expiresAt": _job_expires_at_epoch(),
        "apiRequestId": (api_request_id or "")[:256],
        "source": source[:64],
        "mortgageOnly": mortgage_only,
    }
    if isinstance(line_type_only, str) and line_type_only.strip():
        job_item["lineTypeOnly"] = line_type_only.strip().lower()
    table.put_item(Item=_to_ddb_nested(job_item))
    payload = {
        "internal": "parse_statement_async",
        "jobId": job_id,
        "house": house,
        "s3Keys": s3_keys,
        "ownerSub": owner_sub,
        "apiRequestId": api_request_id or "",
        "mortgageOnly": mortgage_only,
    }
    if "lineTypeOnly" in job_item:
        payload["lineTypeOnly"] = job_item["lineTypeOnly"]
    try:
        _invoke_parse_statement_worker(payload)
    except Exception:
        try:
            table.delete_item(Key=_parse_job_key(job_id))
        except ClientError:
            pass
        raise
    return job_id


def _path_finance_parse_job(
    event: dict[str, Any], path: str
) -> tuple[str | None, str | None]:
    """House + job id from ``/finance/{house}/parse-statement/jobs/{jobId}``."""
    pp = event.get("pathParameters") or {}
    house_raw = pp.get("house")
    job_raw = pp.get("jobId")
    if (
        isinstance(house_raw, str)
        and house_raw.strip()
        and isinstance(job_raw, str)
        and job_raw.strip()
    ):
        return house_raw.strip().lower(), job_raw.strip()
    parts = [p for p in path.split("/") if p]
    if (
        len(parts) == 5
        and parts[0] == "finance"
        and parts[2] == "parse-statement"
        and parts[3] == "jobs"
    ):
        return parts[1].lower(), parts[4]
    return None, None


def _path_statement_book_parse_job(
    event: dict[str, Any], path: str, slug: str
) -> str | None:
    """Job id from ``/{slug}/parse-statement/jobs/{jobId}``."""
    pp = event.get("pathParameters") or {}
    job_raw = pp.get("jobId")
    if isinstance(job_raw, str) and job_raw.strip():
        return job_raw.strip()
    parts = [p for p in path.split("/") if p]
    if (
        len(parts) == 4
        and parts[0] == slug
        and parts[1] == "parse-statement"
        and parts[2] == "jobs"
    ):
        return parts[3]
    return None


def _path_siu_tin_dei_parse_job(
    event: dict[str, Any], path: str
) -> str | None:
    """Job id from ``/siu-tin-dei/parse-statement/jobs/{jobId}``."""
    return _path_statement_book_parse_job(event, path, "siu-tin-dei")


def _notify_parse_job_quietly(doc: dict[str, Any]) -> None:
    """Best-effort operator email; never raise into the parse worker."""
    try:
        from parse_notify import notify_parse_job_outcome

        notify_parse_job_outcome(doc)
    except Exception as exc:  # noqa: BLE001
        _log_event(
            "warning",
            tag="parse_job_notify_failed",
            job_id=str(doc.get("jobId") or "")[:64],
            error=str(exc)[:300],
        )


def _invoke_parse_statement_worker(payload: dict[str, Any]) -> None:
    """Fire-and-forget async invocation to PARSE_WORKER_FUNCTION_NAME (AdminApiFn)."""
    fn_name = (
        (os.environ.get("PARSE_WORKER_FUNCTION_NAME") or "").strip()
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    )
    if not fn_name:
        _handle_parse_statement_async_worker(payload)
        return
    _get_lambda_client().invoke(
        FunctionName=fn_name,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def _parse_job_public_doc(doc: dict[str, Any]) -> dict[str, Any]:
    st = doc.get("status")
    if st in ("pending", "processing"):
        return {"status": st}
    if st == "succeeded":
        keys = doc.get("sourceAssetKeys") or []
        if not isinstance(keys, list):
            keys = []
        out: dict[str, Any] = {
            "status": "succeeded",
            "addedLines": int(doc.get("addedLines") or 0),
            "sourceAssetKeys": keys,
        }
        sk = doc.get("sourceAssetKey")
        if sk:
            out["sourceAssetKey"] = sk
        usage = doc.get("usage")
        if isinstance(usage, dict):
            out["usage"] = usage
        return out
    if st == "failed":
        return {
            "status": "failed",
            "message": str(doc.get("errorMessage") or "Statement parse failed"),
        }
    return {"status": "unknown"}


def _handle_parse_statement_async_worker(payload: dict[str, Any]) -> None:
    job_id = payload.get("jobId")
    house = payload.get("house")
    owner_sub = payload.get("ownerSub")
    raw_keys = payload.get("s3Keys")
    s3_keys: list[str] = []
    if isinstance(raw_keys, list):
        s3_keys = [str(x).strip() for x in raw_keys if isinstance(x, str) and str(x).strip()]
    if not s3_keys:
        sk = payload.get("s3Key")
        if isinstance(sk, str) and sk.strip():
            s3_keys = [sk.strip()]
    if (
        not isinstance(job_id, str)
        or not job_id.strip()
        or not isinstance(house, str)
        or not isinstance(owner_sub, str)
        or not s3_keys
    ):
        _log_event("warning", tag="parse_job_worker_bad_payload")
        return

    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    key = _parse_job_key(job_id.strip())
    now = _utc_iso_z(datetime.now(timezone.utc))
    stale_cutoff = _parse_job_stale_cutoff_iso()
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET #st = :proc, updatedAt = :u",
            ConditionExpression=(
                "#st = :pend OR (#st = :proc AND updatedAt < :stale)"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":proc": "processing",
                ":pend": "pending",
                ":u": now,
                ":stale": stale_cutoff,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            _log_event(
                "info",
                tag="parse_job_skip_duplicate_worker",
                job_id=job_id[:64],
            )
            return
        raise

    api_rid = str(payload.get("apiRequestId") or "").strip()
    req_token = api_rid if api_rid else f"async-parse-{job_id}"
    synthetic_event: dict[str, Any] = {
        "requestContext": {
            "requestId": req_token,
            "http": {"requestId": req_token},
        }
    }
    mortgage_only = payload.get("mortgageOnly") is True
    raw_type = payload.get("lineTypeOnly")
    line_type_only = (
        raw_type.strip().lower()
        if isinstance(raw_type, str) and raw_type.strip()
        else None
    )
    from parse_statement import _ParseStatementError, execute_parse_statement

    try:
        result = execute_parse_statement(
            house=house,
            s3_keys=s3_keys,
            user_sub=owner_sub,
            request_id=req_token,
            event=synthetic_event,
            mortgage_only=mortgage_only,
            line_type_only=line_type_only,
        )
    except _ParseStatementError as exc:
        raw_old = table.get_item(Key=key).get("Item") or {}
        base_doc = _from_ddb_nested(raw_old)
        fail_doc = {
            **base_doc,
            "status": "failed",
            "errorMessage": exc.message,
            "errorStatus": exc.status,
            "updatedAt": _utc_iso_z(datetime.now(timezone.utc)),
        }
        table.put_item(Item=_to_ddb_nested(fail_doc))
        _log_event(
            "warning",
            tag="parse_job_failed",
            job_id=job_id[:64],
            house=house,
            error=exc.message[:300],
        )
        _notify_parse_job_quietly(fail_doc)
        return
    except Exception as exc:
        logger.exception("parse_statement_async worker failed")
        raw_old = table.get_item(Key=key).get("Item") or {}
        base_doc = _from_ddb_nested(raw_old)
        fail_doc = {
            **base_doc,
            "status": "failed",
            "errorMessage": "Statement parse failed unexpectedly",
            "errorStatus": 500,
            "updatedAt": _utc_iso_z(datetime.now(timezone.utc)),
        }
        table.put_item(Item=_to_ddb_nested(fail_doc))
        _log_event(
            "error",
            tag="parse_job_worker_exception",
            job_id=job_id[:64],
            error=str(exc)[:500],
        )
        _notify_parse_job_quietly(fail_doc)
        return

    raw_old = table.get_item(Key=key).get("Item") or {}
    base_doc = _from_ddb_nested(raw_old)
    ok_doc = {
        **base_doc,
        "status": "succeeded",
        "addedLines": result.get("addedLines", 0),
        "sourceAssetKeys": result.get("sourceAssetKeys") or [],
        "updatedAt": _utc_iso_z(datetime.now(timezone.utc)),
    }
    sk = result.get("sourceAssetKey")
    if sk:
        ok_doc["sourceAssetKey"] = sk
    elif "sourceAssetKey" in ok_doc:
        del ok_doc["sourceAssetKey"]
    usage = result.get("usage")
    if isinstance(usage, dict):
        ok_doc["usage"] = usage
    table.put_item(Item=_to_ddb_nested(ok_doc))
    _notify_parse_job_quietly(ok_doc)


