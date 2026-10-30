"""Resume rows, settings, jobs, and file bytes for the LX Software Resume tab.

Rows use the ``RESUME#`` prefix and stay out of ``/records``. File bytes live in
the assets bucket (``resume/resumes/{id}/…``) or in memory when no bucket is set.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import board_store
from botocore.exceptions import ClientError
from ddb_convert import _from_ddb_nested, _to_ddb_nested

HKT = ZoneInfo("Asia/Hong_Kong")
PK_PREFIX = "RESUME#"
BYTE_MAX = 4 * 1024 * 1024
AD_TEXT_MAX = 20_000
MODEL_MAX = 120
INSTRUCTIONS_MAX = 4_000
TITLE_MAX = 200
JOB_TTL_SECONDS = 7 * 86400
ESTIMATE_USD = 0.05

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_TYPE = "application/pdf"
MD_TYPE = "text/markdown"
TEXT_TYPE = "text/plain"
FORMATS = {
    DOCX_TYPE: "docx",
    PDF_TYPE: "pdf",
    MD_TYPE: "md",
    TEXT_TYPE: "md",
}
APPLICATION_STATUSES = (
    "saved",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
)
OUTPUT_LENGTHS = ("concise", "standard", "detailed")
REWRITE_SCOPE = ("headline", "summary", "bullets", "skills")
BULLET_POLICIES = ("keep", "flex")
PAGE_SIZES = ("A4", "Letter")

_MEMORY: dict[str, tuple[str, bytes]] = {}


class ResumeError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class _SpendConflict(Exception):
    pass


def feature_enabled() -> bool:
    return os.environ.get("RESUME_ENABLED", "").strip().lower() == "true"


def default_settings() -> dict[str, Any]:
    return {
        "model": "",
        "maxUsdPerMonth": 5.0,
        "temperature": 0.4,
        "outputLength": "standard",
        "rewriteScope": list(REWRITE_SCOPE),
        "bulletPolicy": "keep",
        "allowNewSkills": False,
        "pageSize": "A4",
        "instructions": "",
    }


def model_name(settings: dict[str, Any]) -> str:
    chosen = str(settings.get("model") or "").strip()
    if chosen:
        return chosen
    return (os.environ.get("OPENROUTER_MODEL") or "").strip()


def tailor_timeout() -> int:
    raw = os.environ.get("RESUME_TAILOR_TIMEOUT_SECONDS", "200").strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 200
    return max(5, parsed)


def _now() -> str:
    return board_store.now_iso()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _state_key(sk: str) -> dict[str, str]:
    return {"pk": f"{PK_PREFIX}state", "sk": sk}


def _put(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(Item=_to_ddb_nested(doc))


def _get(table: Any, pk: str, sk: str) -> dict[str, Any] | None:
    item = table.get_item(Key={"pk": pk, "sk": sk}).get("Item")
    if not item:
        return None
    loaded = _from_ddb_nested(item)
    return loaded if isinstance(loaded, dict) else None


def _query(table: Any, gsi1pk: str) -> list[dict[str, Any]]:
    result = table.query(
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :pk",
        ExpressionAttributeValues={":pk": gsi1pk},
        ScanIndexForward=False,
    )
    rows: list[dict[str, Any]] = []
    for item in result.get("Items") or []:
        loaded = _from_ddb_nested(item)
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def _load_sk(table: Any, sk: str) -> dict[str, Any]:
    return _get(table, f"{PK_PREFIX}state", sk) or {}


def load_settings(table: Any) -> dict[str, Any]:
    stored = _load_sk(table, "SETTINGS")
    merged = default_settings()
    for key in merged:
        if key in stored:
            merged[key] = stored[key]
    if not isinstance(merged["rewriteScope"], list):
        merged["rewriteScope"] = list(REWRITE_SCOPE)
    return merged


def validate_settings(body: dict[str, Any]) -> dict[str, Any]:
    current = default_settings()
    model = str(body.get("model") if "model" in body else current["model"]).strip()
    if len(model) > MODEL_MAX:
        raise ResumeError(f"Model is over {MODEL_MAX} characters.")
    try:
        cap = float(body.get("maxUsdPerMonth", current["maxUsdPerMonth"]))
    except (TypeError, ValueError) as exc:
        raise ResumeError("Monthly spend cap must be a number.") from exc
    if cap < 0 or cap > 1000:
        raise ResumeError("Monthly spend cap must be between 0 and 1000.")
    try:
        temperature = float(body.get("temperature", current["temperature"]))
    except (TypeError, ValueError) as exc:
        raise ResumeError("Temperature must be a number.") from exc
    if temperature < 0 or temperature > 1:
        raise ResumeError("Temperature must be between 0 and 1.")
    length = str(body.get("outputLength") or current["outputLength"])
    if length not in OUTPUT_LENGTHS:
        raise ResumeError("Output length must be concise, standard, or detailed.")
    scope_raw = body.get("rewriteScope", current["rewriteScope"])
    if not isinstance(scope_raw, list) or any(item not in REWRITE_SCOPE for item in scope_raw):
        raise ResumeError("Rewrite scope is not valid.")
    policy = str(body.get("bulletPolicy") or current["bulletPolicy"])
    if policy not in BULLET_POLICIES:
        raise ResumeError("Bullet policy must be keep or flex.")
    page = str(body.get("pageSize") or current["pageSize"])
    if page not in PAGE_SIZES:
        raise ResumeError("Page size must be A4 or Letter.")
    instructions = str(body.get("instructions") if "instructions" in body else current["instructions"])
    if len(instructions) > INSTRUCTIONS_MAX:
        raise ResumeError(f"Instructions are over {INSTRUCTIONS_MAX} characters.")
    allow = body.get("allowNewSkills", current["allowNewSkills"])
    if not isinstance(allow, bool):
        raise ResumeError("Allow new skills must be true or false.")
    return {
        "model": model,
        "maxUsdPerMonth": cap,
        "temperature": temperature,
        "outputLength": length,
        "rewriteScope": [item for item in REWRITE_SCOPE if item in scope_raw],
        "bulletPolicy": policy,
        "allowNewSkills": allow,
        "pageSize": page,
        "instructions": instructions.strip(),
    }


def save_settings(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    settings = validate_settings(body)
    _put(table, {**_state_key("SETTINGS"), **settings, "updatedAt": _now()})
    return settings


def month_spend(table: Any, now: datetime | None = None) -> float:
    from resume_spend import month_spend as impl

    return impl(table, now)


def adjust_spend(table: Any, usd: float, now: datetime | None = None) -> float:
    from resume_spend import adjust_spend as impl

    return impl(table, usd, now)


def try_reserve_spend(table: Any, usd: float, cap: float, now: datetime | None = None) -> bool:
    from resume_spend import try_reserve_spend as impl

    return impl(table, usd, cap, now)


def template_id(table: Any) -> str:
    return str(_load_sk(table, "TEMPLATE").get("templateResumeId") or "")


def set_template(table: Any, resume_id: str) -> str:
    row = get_resume(table, resume_id)
    if not row:
        raise ResumeError("Resume not found.", 404)
    if row.get("format") != "docx" or (row.get("extract") or {}).get("status") != "ready":
        raise ResumeError("Only a ready Word document can be the template.", 409)
    previous = template_id(table)
    if previous and previous != resume_id:
        old = get_resume(table, previous)
        if old and old.get("kind") == "template":
            old["kind"] = "archive"
            old["updatedAt"] = _now()
            _put_resume(table, old)
    if row.get("kind") != "tailored":
        row["kind"] = "template"
        row["updatedAt"] = _now()
        _put_resume(table, row)
    _put(table, {**_state_key("TEMPLATE"), "templateResumeId": resume_id, "setAt": _now()})
    return resume_id


def clear_memory() -> None:
    _MEMORY.clear()


def put_bytes(key: str, content_type: str, data: bytes) -> None:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if bucket:
        import boto3

        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        return
    _MEMORY[key] = (content_type, data)


def load_bytes(key: str) -> tuple[str, bytes] | None:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        return _MEMORY.get(key)
    import boto3

    try:
        response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise
    body = response["Body"].read()
    return str(response.get("ContentType") or "application/octet-stream"), body


def delete_bytes(key: str) -> None:
    _MEMORY.pop(key, None)
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        return
    import boto3

    boto3.client("s3").delete_object(Bucket=bucket, Key=key)


def _resume_key(resume_id: str) -> dict[str, str]:
    return {"pk": f"{PK_PREFIX}resume#{resume_id}", "sk": "RESUME"}


def _put_resume(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    _put(table, {**_resume_key(str(doc["resumeId"])), **doc})
    return doc


def get_resume(table: Any, resume_id: str) -> dict[str, Any] | None:
    return _get(table, f"{PK_PREFIX}resume#{resume_id}", "RESUME")


def list_resumes(table: Any) -> list[dict[str, Any]]:
    return _query(table, f"{PK_PREFIX}resumes")


def create_resume(
    table: Any,
    *,
    title: str,
    content_type: str,
    data: bytes,
    make_template: bool,
) -> dict[str, Any]:
    cleaned = title.strip()
    if not cleaned or len(cleaned) > TITLE_MAX:
        raise ResumeError(f"Title is required and must be under {TITLE_MAX} characters.")
    if len(data) > BYTE_MAX:
        raise ResumeError("The file is over 4 MB.")
    if not data:
        raise ResumeError("The file is empty.")
    fmt = FORMATS.get(content_type)
    if not fmt:
        raise ResumeError("Upload a Word document, PDF, Markdown, or text file.")
    if make_template and fmt != "docx":
        raise ResumeError("Only a Word document can be the template.")
    resume_id = _new_id()
    ext = "docx" if fmt == "docx" else "pdf" if fmt == "pdf" else "md"
    key = f"resume/resumes/{resume_id}/source.{ext}"
    put_bytes(key, content_type, data)
    now = _now()
    doc = {
        "resumeId": resume_id,
        "title": cleaned,
        "kind": "archive",
        "format": fmt,
        "source": "upload",
        "file": {
            "contentType": content_type,
            "size": len(data),
            "key": key,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "extract": {"status": "pending", "error": ""},
        "paragraphs": [],
        "layout": {"paragraphs": [], "roles": [], "overrides": {}},
        "derivedFrom": None,
        "generation": None,
        "pdfKey": "",
        "createdAt": now,
        "updatedAt": now,
        "gsi1pk": f"{PK_PREFIX}resumes",
        "gsi1sk": f"{now}#{resume_id}",
    }
    _put_resume(table, doc)
    if make_template:
        # The pointer is set after extract marks the row ready.
        doc["makeTemplate"] = True
        _put_resume(table, doc)
    return doc


def save_resume(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    doc["updatedAt"] = _now()
    return _put_resume(table, doc)


def patch_resume(table: Any, resume_id: str, body: dict[str, Any]) -> dict[str, Any]:
    doc = get_resume(table, resume_id)
    if not doc:
        raise ResumeError("Resume not found.", 404)
    if "title" in body:
        title = str(body.get("title") or "").strip()
        if not title or len(title) > TITLE_MAX:
            raise ResumeError(f"Title is required and must be under {TITLE_MAX} characters.")
        doc["title"] = title
        doc["pdfKey"] = ""
    overrides = body.get("overrides")
    if isinstance(overrides, dict):
        layout = dict(doc.get("layout") or {})
        known = {item.get("id") for item in layout.get("paragraphs") or []}
        cleaned: dict[str, str] = {}
        for key, value in overrides.items():
            if key not in known or value not in {"locked", "rewritable"}:
                raise ResumeError("A paragraph lock does not match this resume.")
            cleaned[str(key)] = str(value)
        layout["overrides"] = cleaned
        doc["layout"] = layout
    return save_resume(table, doc)


def resume_referenced(table: Any, resume_id: str) -> bool:
    rows = _query(table, f"{PK_PREFIX}applications")
    return any(str(row.get("resumeId") or "") == resume_id for row in rows)


def delete_resume(table: Any, resume_id: str) -> None:
    doc = get_resume(table, resume_id)
    if not doc:
        raise ResumeError("Resume not found.", 404)
    if template_id(table) == resume_id:
        raise ResumeError("The template resume cannot be deleted.", 409)
    if resume_referenced(table, resume_id):
        raise ResumeError("This resume is used by a job application.", 409)
    table.delete_item(Key=_resume_key(resume_id))
    file_key = str((doc.get("file") or {}).get("key") or "")
    if file_key:
        delete_bytes(file_key)
    if doc.get("pdfKey"):
        delete_bytes(str(doc["pdfKey"]))


def public_resume(doc: dict[str, Any], *, detail: bool) -> dict[str, Any]:
    item = {
        "id": doc.get("resumeId"),
        "title": doc.get("title") or "",
        "kind": doc.get("kind") or "archive",
        "format": doc.get("format") or "",
        "source": doc.get("source") or "upload",
        "file": {
            "contentType": (doc.get("file") or {}).get("contentType") or "",
            "size": (doc.get("file") or {}).get("size") or 0,
        },
        "extract": doc.get("extract") or {"status": "pending", "error": ""},
        "derivedFrom": doc.get("derivedFrom"),
        "createdAt": doc.get("createdAt") or "",
        "updatedAt": doc.get("updatedAt") or "",
    }
    if detail:
        item["paragraphs"] = list(doc.get("paragraphs") or [])
        item["layout"] = doc.get("layout") or {"paragraphs": [], "roles": [], "overrides": {}}
        item["generation"] = doc.get("generation")
    return item


def new_job(table: Any, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = _new_id()
    doc = {
        "jobId": job_id,
        "kind": kind,
        "status": "queued",
        "payload": payload,
        "resumeIds": [],
        "error": "",
        "findings": [],
        "createdAt": _now(),
    }
    return put_job(table, doc)


def put_job(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    job_id = str(doc["jobId"])
    _put(
        table,
        {
            "pk": f"{PK_PREFIX}job#{job_id}",
            "sk": "RESUME",
            "expiresAt": int(time.time()) + JOB_TTL_SECONDS,
            **doc,
        },
    )
    return doc


def get_job(table: Any, job_id: str) -> dict[str, Any] | None:
    return _get(table, f"{PK_PREFIX}job#{job_id}", "RESUME")


def public_job(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": doc.get("jobId"),
        "status": doc.get("status"),
        "resumeIds": list(doc.get("resumeIds") or []),
        "error": doc.get("error") or "",
        "findings": list(doc.get("findings") or []),
    }


def counts(table: Any) -> dict[str, int]:
    return {
        "resumes": len(list_resumes(table)),
        "postings": len(_query(table, f"{PK_PREFIX}postings")),
        "applications": len(_query(table, f"{PK_PREFIX}applications")),
    }
