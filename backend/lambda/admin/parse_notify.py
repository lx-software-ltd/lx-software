"""Email the operator when a statement parse job succeeds or fails.

Uses SES v2. Empty ``STATEMENT_PARSE_NOTIFY_EMAIL`` disables sending.
SES failures must never change the job outcome.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from http_common import _log_event

_OWNER_LABELS = {
    "hillmarton": "32 Hillmarton",
    "morrison": "The Morrison",
    "lxSoftware": "LX Software",
    "siuTinDei": "Siu Tin Dei",
}

_SOURCE_LABELS = {
    "inbound_mail": "inbound email",
    "api": "admin upload",
}

_sesv2: Any = None


def _ses_client() -> Any:
    global _sesv2
    if _sesv2 is None:
        _sesv2 = boto3.client("sesv2")
    return _sesv2


def reset_ses_client_for_tests() -> None:
    global _sesv2
    _sesv2 = None


def notify_recipients() -> list[str]:
    raw = (os.environ.get("STATEMENT_PARSE_NOTIFY_EMAIL") or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        addr = part.strip()
        if addr.count("@") != 1 or addr.startswith("@") or addr.endswith("@"):
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def notify_from_address() -> str:
    explicit = (os.environ.get("STATEMENT_PARSE_NOTIFY_FROM") or "").strip()
    if explicit and "@" in explicit:
        return explicit
    domain = (
        os.environ.get("INBOUND_MAIL_DOMAIN") or "inbound.lx-software.com"
    ).strip()
    return f"statements@{domain}"


def owner_display_label(house: str) -> str:
    key = (house or "").strip()
    return _OWNER_LABELS.get(key, key or "Unknown")


def source_display_label(source: str) -> str:
    key = (source or "").strip()
    return _SOURCE_LABELS.get(key, key or "unknown")


def _file_names(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("s3Keys")
    keys: list[str] = []
    if isinstance(raw, list):
        keys = [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]
    if not keys:
        sk = doc.get("s3Key")
        if isinstance(sk, str) and sk.strip():
            keys = [sk.strip()]
    names: list[str] = []
    for key in keys:
        base = key.rsplit("/", 1)[-1]
        if base.startswith("00_") or (
            len(base) > 3 and base[2] == "_" and base[:2].isdigit()
        ):
            names.append(base[3:])
        else:
            names.append(base)
    return names


def build_parse_notify_message(doc: dict[str, Any]) -> tuple[str, str] | None:
    """Return ``(subject, body)`` for a terminal parse job, or ``None``."""
    status = str(doc.get("status") or "").strip()
    if status not in ("succeeded", "failed"):
        return None
    house = str(doc.get("house") or "").strip()
    label = owner_display_label(house)
    job_id = str(doc.get("jobId") or "").strip() or "unknown"
    source = source_display_label(str(doc.get("source") or ""))
    files = _file_names(doc)
    origin = (os.environ.get("ADMIN_WEB_ORIGIN") or "https://admin.lx-software.com").rstrip(
        "/"
    )
    outcome = "succeeded" if status == "succeeded" else "failed"
    subject = f"[{label}] Statement parse {outcome}"
    lines = [
        f"A statement parse job {outcome}.",
        "",
        f"Entity: {label}",
        f"Job: {job_id}",
        f"Source: {source}",
    ]
    if files:
        lines.append("Files:")
        for name in files:
            lines.append(f"  - {name}")
    else:
        lines.append("Files: (none recorded)")
    if status == "succeeded":
        try:
            added = int(doc.get("addedLines") or 0)
        except (TypeError, ValueError):
            added = 0
        lines.append(f"Lines added: {added}")
    else:
        err = str(doc.get("errorMessage") or "Statement parse failed").strip()
        lines.append(f"Error: {err}")
    lines.extend(["", f"Open admin: {origin}"])
    return subject, "\n".join(lines) + "\n"


def notify_parse_job_outcome(doc: dict[str, Any]) -> bool:
    """Send a success/failure email when notify is configured. Never raises."""
    recipients = notify_recipients()
    if not recipients:
        return False
    built = build_parse_notify_message(doc)
    if built is None:
        return False
    subject, body = built
    from_addr = notify_from_address()
    job_id = str(doc.get("jobId") or "")[:64]
    try:
        _ses_client().send_email(
            FromEmailAddress=from_addr,
            Destination={"ToAddresses": recipients},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )
    except Exception as exc:  # noqa: BLE001 — notify must not fail the job
        _log_event(
            "warning",
            tag="parse_job_notify_send_failed",
            job_id=job_id,
            error=str(exc)[:300],
        )
        return False
    _log_event(
        "info",
        tag="parse_job_notify_sent",
        job_id=job_id,
        status=str(doc.get("status") or ""),
        recipients=len(recipients),
    )
    return True
