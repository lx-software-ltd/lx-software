"""Process raw inbound email stored by SES in S3: extract PDF, parse statement.

SES receipt rules deliver mail for configured addresses into
``{INBOUND_RAW_MAIL_PREFIX}/{house_key}/…`` in the inbound bucket. S3 invokes
this Lambda on those prefixes. Every ``application/pdf`` part is copied into
the admin assets bucket; lines are parsed once with **all** of those object
keys attached to each new line (``sourceAssetKeys``), matching multi-PDF
imports in the admin UI.

``house_key`` values are the stable finance identifiers in the repo
(``FINANCE_HOUSE_KEYS``), e.g. ``hillmarton`` for the house labelled
"32 Hillmarton" in the admin UI. The inbox local-part (e.g. ``32-hillmarton``)
is configured separately in CDK and does not have to match the key.

Add more inboxes by extending the CDK ``inboundHouseMailboxes`` list (each row
maps ``localPart@domain`` → a finance ``house_key`` such as ``morrison``).

The Executive Board mailbox (``siutindei-board@…``) lands under
``inbound-raw/<BOARD_MAIL_RAW_SEGMENT>/`` and is indexed by ``board_mail``
instead of being parsed as a statement.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import uuid
from email import policy
from email.parser import BytesParser
from typing import Any

import boto3

import board_mail
from handler import (
    MAX_SOURCE_ASSET_KEYS_PER_LINE,
    FINANCE_HOUSE_KEYS,
    enqueue_parse_statement_async_job,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_s3 = boto3.client("s3")


def raw_mail_segment(*, ses_drop_path: str, raw_mail_prefix: str) -> str | None:
    """The first path segment after ``<raw_mail_prefix>/`` (lower-cased), if any."""
    root = raw_mail_prefix.strip().strip("/")
    if not root:
        return None
    if not ses_drop_path.startswith(f"{root}/"):
        return None
    rest = ses_drop_path[len(root) + 1 :]
    segment = rest.split("/", 1)[0].strip().lower()
    return segment or None


def house_key_from_raw_mail_s3_key(*, ses_drop_path: str, raw_mail_prefix: str) -> str | None:
    """Resolve finance house key from an SES drop key.

    Expected layout: ``<raw_mail_prefix>/<house_key>/…`` where ``house_key`` is
    a member of ``FINANCE_HOUSE_KEYS`` (e.g. ``hillmarton`` for "32 Hillmarton",
    or ``inbound-raw/morrison/…`` for the Morrison house).
    """
    segment = raw_mail_segment(ses_drop_path=ses_drop_path, raw_mail_prefix=raw_mail_prefix)
    if segment is None or segment not in FINANCE_HOUSE_KEYS:
        return None
    return segment


def is_board_mail_s3_key(*, ses_drop_path: str, raw_mail_prefix: str) -> bool:
    segment = raw_mail_segment(ses_drop_path=ses_drop_path, raw_mail_prefix=raw_mail_prefix)
    return segment is not None and segment == board_mail.raw_segment()


def _sanitize_filename(name: str) -> str:
    base = os.path.basename((name or "").strip() or "statement.pdf")
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:180]
    return safe or "statement.pdf"


def extract_pdf_attachments(raw: bytes) -> list[tuple[bytes, str]]:
    """Return ``(pdf_bytes, safe_filename)`` for every PDF part, in walk order."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    out: list[tuple[bytes, str]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() != "application/pdf":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
            continue
        fn = part.get_filename() or "statement.pdf"
        out.append((bytes(payload), _sanitize_filename(fn)))
    return out


def extract_first_pdf_attachment(raw: bytes) -> tuple[bytes, str] | None:
    """Return ``(pdf_bytes, safe_filename)`` for the first PDF part, if any."""
    parts = extract_pdf_attachments(raw)
    return parts[0] if parts else None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    inbound_bucket = os.environ.get("INBOUND_MAIL_BUCKET_NAME", "").strip()
    assets_bucket = os.environ.get("ASSETS_BUCKET_NAME", "").strip()
    raw_mail_prefix = os.environ.get("INBOUND_RAW_MAIL_PREFIX", "inbound-raw").strip()
    user_sub = os.environ.get("INBOUND_AUDIT_USER_SUB", "inbound-email").strip()
    max_pdf = int(os.environ.get("ASSET_MAX_BYTES", str(20 * 1024 * 1024)))

    if not inbound_bucket or not assets_bucket:
        logger.error(
            json.dumps(
                {"tag": "inbound_mail_misconfigured", "reason": "missing_bucket_env"}
            )
        )
        return {"ok": False, "reason": "misconfigured"}

    request_id = getattr(context, "aws_request_id", None) or "unknown"

    for record in event.get("Records") or []:
        if record.get("eventSource") != "aws:s3":
            continue
        raw_key = urllib.parse.unquote_plus(
            record.get("s3", {}).get("object", {}).get("key", "")
        )
        src_bucket = record.get("s3", {}).get("bucket", {}).get("name", "")
        if src_bucket == inbound_bucket and is_board_mail_s3_key(
            ses_drop_path=raw_key, raw_mail_prefix=raw_mail_prefix
        ):
            try:
                remaining_ms = getattr(context, "get_remaining_time_in_millis", lambda: 0)()
                deadline = time.monotonic() + max(0, remaining_ms) / 1000 if remaining_ms else None
                result = board_mail.ingest_raw_object(inbound_bucket, raw_key, s3=_s3, deadline=deadline)
            except Exception as exc:  # noqa: BLE001 — one bad message must not block the batch
                logger.error(
                    json.dumps(
                        {
                            "tag": "board_mail_ingest_failed",
                            "key": raw_key[:512],
                            "error": str(exc)[:500],
                        }
                    )
                )
                continue
            logger.info(
                json.dumps(
                    {
                        "tag": "board_mail_ingested",
                        "key": raw_key[:512],
                        "threadId": result.get("threadId"),
                        "duplicate": bool(result.get("duplicate")),
                    }
                )
            )
            continue

        house_key = house_key_from_raw_mail_s3_key(
            ses_drop_path=raw_key, raw_mail_prefix=raw_mail_prefix
        )
        if src_bucket != inbound_bucket or house_key is None:
            logger.info(
                json.dumps(
                    {
                        "tag": "inbound_mail_skip",
                        "reason": "wrong_bucket_or_unknown_prefix",
                        "key": raw_key[:512],
                    }
                )
            )
            continue

        try:
            obj = _s3.get_object(Bucket=inbound_bucket, Key=raw_key)
            body = obj["Body"].read()
        except Exception as exc:  # noqa: BLE001 — log any S3 read failure
            logger.error(
                json.dumps(
                    {
                        "tag": "inbound_mail_read_failed",
                        "key": raw_key[:512],
                        "error": str(exc)[:500],
                    }
                )
            )
            continue

        pdf_parts = extract_pdf_attachments(body)
        if not pdf_parts:
            logger.warning(
                json.dumps(
                    {
                        "tag": "inbound_mail_no_pdf",
                        "key": raw_key[:512],
                        "size": len(body),
                    }
                )
            )
            continue

        if len(pdf_parts) > MAX_SOURCE_ASSET_KEYS_PER_LINE:
            logger.warning(
                json.dumps(
                    {
                        "tag": "inbound_mail_pdf_count_capped",
                        "key": raw_key[:512],
                        "count": len(pdf_parts),
                        "max": MAX_SOURCE_ASSET_KEYS_PER_LINE,
                    }
                )
            )
            pdf_parts = pdf_parts[:MAX_SOURCE_ASSET_KEYS_PER_LINE]

        oversize_idx = next(
            (i for i, (blob, _) in enumerate(pdf_parts) if len(blob) > max_pdf),
            None,
        )
        if oversize_idx is not None:
            logger.warning(
                json.dumps(
                    {
                        "tag": "inbound_mail_pdf_too_large",
                        "key": raw_key[:512],
                        "index": oversize_idx,
                        "bytes": len(pdf_parts[oversize_idx][0]),
                        "max": max_pdf,
                    }
                )
            )
            continue

        batch_id = uuid.uuid4().hex
        dest_keys: list[str] = []
        for idx, (pdf_bytes, safe_name) in enumerate(pdf_parts):
            dest_key = f"inbound/{house_key}/{batch_id}/{idx:02d}_{safe_name}"
            try:
                _s3.put_object(
                    Bucket=assets_bucket,
                    Key=dest_key,
                    Body=pdf_bytes,
                    ContentType="application/pdf",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    json.dumps(
                        {
                            "tag": "inbound_mail_put_asset_failed",
                            "dest": dest_key[:512],
                            "error": str(exc)[:500],
                        }
                    )
                )
                dest_keys = []
                break
            dest_keys.append(dest_key)

        if not dest_keys:
            continue

        try:
            job_id = enqueue_parse_statement_async_job(
                house=house_key,
                s3_keys=dest_keys,
                owner_sub=user_sub,
                api_request_id=request_id,
                source="inbound_mail",
            )
        except Exception as exc:
            logger.warning(
                json.dumps(
                    {
                        "tag": "inbound_mail_enqueue_parse_failed",
                        "houseKey": house_key,
                        "destKeys": [k[:256] for k in dest_keys],
                        "error": str(exc)[:500],
                    }
                )
            )
            continue

        try:
            _s3.delete_object(Bucket=inbound_bucket, Key=raw_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                json.dumps(
                    {
                        "tag": "inbound_mail_raw_delete_failed",
                        "key": raw_key[:512],
                        "error": str(exc)[:300],
                    }
                )
            )

        logger.info(
            json.dumps(
                {
                    "tag": "inbound_mail_parse_enqueued",
                    "houseKey": house_key,
                    "pdfCount": len(dest_keys),
                    "jobId": job_id,
                }
            )
        )
        continue

    return {"ok": True}
