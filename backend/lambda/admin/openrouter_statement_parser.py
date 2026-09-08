"""OpenRouter statement parser.

Calls the OpenRouter Chat Completions API to extract finance statement
transactions from a PDF (or image / text) attachment stored in S3.

Mirrors the design used in github.com/lcacchiani/evolvesprouts'
``openrouter_expense_parser.py`` but is purpose-built for the LX Software
admin "House statement" feature: each parsed line maps directly onto the
``HouseStatementLine`` shape stored against a house in DynamoDB (line types:
``income``, ``expenditure``, ``mortgage``).
"""

from __future__ import annotations

import base64
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

import openrouter_client
from contract_constants import FINANCE_LINE_TYPES, SUPPORTED_FINANCE_CURRENCIES

_PDF_PLUGIN_ID = "file-parser"
_DEFAULT_PDF_ENGINE = "mistral-ocr"
_DEFAULT_MODEL = "mistralai/mistral-medium-3"
_DEFAULT_MAX_FILE_BYTES = 15 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 60

_SUPPORTED_CURRENCIES = tuple(sorted(SUPPORTED_FINANCE_CURRENCIES))
_FINANCE_LINE_TYPES = tuple(sorted(FINANCE_LINE_TYPES))
_DISCARD_DESCRIPTION_NORMALIZED = "payment to landlord"
_MTG_IN_DESCRIPTION = re.compile(r"(?i)\bmtg\b")


def parse_statement_from_asset(
    *,
    s3_client: Any,
    secrets_client: Any,
    bucket: str,
    s3_key: str,
    file_name: str | None,
    content_type: str | None,
    default_currency: str,
    owner: str | None = None,
) -> dict[str, Any]:
    """Download a single asset from S3 and ask OpenRouter to extract lines.

    Returns ``{"lines": [...], "raw": <openrouter response>}`` where each
    line follows the ``HouseStatementLine`` JSON shape but without an
    ``id`` (the caller assigns one).
    """
    model = os.getenv("OPENROUTER_MODEL", "").strip() or _DEFAULT_MODEL

    asset_payload = _download_attachment(
        s3_client=s3_client,
        bucket=bucket,
        s3_key=s3_key,
        file_name=file_name,
        content_type=content_type,
    )

    user_content: list[dict[str, Any]] = [
        {"type": "text", "text": _schema_prompt(default_currency)},
        asset_payload["content"],
    ]

    messages = [
        {
            "role": "system",
            "content": (
                "You extract finance statement lines from documents and "
                "return strict JSON only."
            ),
        },
        {"role": "user", "content": user_content},
    ]
    plugins = None
    if asset_payload["is_pdf"]:
        plugins = [
            {
                "id": _PDF_PLUGIN_ID,
                "pdf": {"engine": _pdf_parser_engine()},
            }
        ]

    completion = openrouter_client.chat_completion(
        messages=messages,
        model=model,
        secrets_client=secrets_client,
        timeout=_timeout_seconds(),
        json_mode=True,
        temperature=0,
        plugins=plugins,
        include_usage=True,
        deny_data_collection=False,
        max_retries=0,
        service=openrouter_client.SERVICE_STATEMENT_PARSER,
        owner=owner,
    )

    parsed = openrouter_client.parse_json_object_text(completion.text)
    parsed["__raw_response__"] = completion.raw
    result = _normalize_result(parsed, default_currency=default_currency)
    result["usage"] = completion.usage
    return result


def _download_attachment(
    *,
    s3_client: Any,
    bucket: str,
    s3_key: str,
    file_name: str | None,
    content_type: str | None,
) -> dict[str, Any]:
    if not s3_key.strip():
        raise RuntimeError("Attachment is missing s3_key")
    response = s3_client.get_object(Bucket=bucket, Key=s3_key)
    body = response["Body"].read()
    max_bytes = _max_file_bytes()
    if len(body) > max_bytes:
        raise RuntimeError(
            f"Attachment exceeds parser size limit ({len(body)} > {max_bytes} bytes)"
        )

    normalized_type = _normalize_content_type(content_type, file_name)
    name = file_name or "statement"
    is_pdf = normalized_type == "application/pdf"

    if normalized_type.startswith("image/"):
        encoded = base64.b64encode(body).decode("utf-8")
        return {
            "is_pdf": False,
            "content": {
                "type": "image_url",
                "image_url": {"url": f"data:{normalized_type};base64,{encoded}"},
            },
        }

    mime_primary = normalized_type.split(";", 1)[0].strip()
    if mime_primary == "text/plain":
        return {
            "is_pdf": False,
            "content": {"type": "text", "text": body.decode("utf-8", errors="replace")},
        }

    encoded = base64.b64encode(body).decode("utf-8")
    return {
        "is_pdf": is_pdf,
        "content": {
            "type": "file",
            "file": {
                "filename": name,
                "file_data": f"data:{normalized_type};base64,{encoded}",
            },
        },
    }


def _normalize_content_type(content_type: str | None, file_name: str | None) -> str:
    ct = (content_type or "").strip().lower()
    if ct:
        return ct
    lowered = (file_name or "").lower()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"


def _normalize_result(parsed: dict[str, Any], *, default_currency: str) -> dict[str, Any]:
    fallback_cur = _coerce_currency(default_currency, fallback="HKD")
    raw_lines = parsed.get("lines")
    if not isinstance(raw_lines, list):
        raw_lines = parsed.get("transactions") if isinstance(parsed.get("transactions"), list) else []
    out: list[dict[str, Any]] = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        date_iso = _coerce_date_utc(raw.get("dateUtc") or raw.get("date"))
        if date_iso is None:
            continue
        line_type = _coerce_line_type(raw.get("type"))
        if line_type is None:
            continue
        description = _optional_text(raw.get("description"), max_length=2000)
        if not description:
            continue
        if _MTG_IN_DESCRIPTION.search(description):
            line_type = "mortgage"
        if description.strip().casefold() == _DISCARD_DESCRIPTION_NORMALIZED:
            continue
        currency = _coerce_currency(raw.get("currency"), fallback=fallback_cur)
        gross = _coerce_money(raw.get("grossAmount") or raw.get("amount"))
        net = _coerce_money(raw.get("netAmount"))
        vat = _coerce_money(raw.get("vat"))
        if gross is None and net is not None and vat is not None:
            gross = round(net + vat, 2)
        if net is None and gross is not None:
            net = round((gross - (vat or 0.0)), 2)
        if vat is None:
            vat = 0.0
        if gross is None:
            continue
        if net is None:
            net = round(gross - vat, 2)
        out.append(
            {
                "dateUtc": date_iso,
                "type": line_type,
                "description": description,
                "netAmount": float(net),
                "vat": float(vat),
                "grossAmount": float(gross),
                "currency": currency,
            }
        )
    return {"lines": out, "raw": parsed.get("__raw_response__", parsed)}


def _coerce_line_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if s in _FINANCE_LINE_TYPES:
        return s
    if s in {"credit", "in", "deposit", "incoming", "money_in"}:
        return "income"
    if s in {"debit", "out", "withdrawal", "expense", "outgoing", "money_out"}:
        return "expenditure"
    if s in {"home_loan", "mortgage_payment"}:
        return "mortgage"
    return None


def _coerce_currency(value: Any, *, fallback: str) -> str:
    if isinstance(value, str):
        s = value.strip().upper()
        if len(s) >= 3:
            s = s[:3]
            if s in _SUPPORTED_CURRENCIES:
                return s
    fb = (fallback or "").strip().upper()[:3]
    if fb in _SUPPORTED_CURRENCIES:
        return fb
    return "HKD"


def _coerce_date_utc(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
    except ValueError:
        return None
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return iso


def _coerce_money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return abs(float(value))
    return _parse_money_string(str(value))


def _optional_text(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_length]


def _parse_money_string(raw: str) -> float | None:
    s = raw.strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        neg = True
        s = s[1:].strip()
    s = re.sub(
        r"\s*(USD|EUR|GBP|HKD|CNY|SGD|AED|[A-Z]{3})\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()
    for sym in ("$", "\u00a3", "\u20ac", "\u00a5", "\u20b9"):
        s = s.replace(sym, "")
    s = s.replace("\u00a0", " ").strip()
    compact = s.replace(" ", "")
    m = re.search(r"[+-]?(?:\d[\d.,]*\d|\d+\.\d+|\.\d+|\d+)", compact)
    if not m:
        return None
    numeric = m.group(0)
    try:
        normalized = _normalize_decimal_grouping(numeric)
        out = float(normalized)
    except ValueError:
        return None
    out = abs(out)
    return -out if neg else out


def _normalize_decimal_grouping(s: str) -> str:
    negative = s.startswith("-")
    s = s.lstrip("+").lstrip("-")
    if not s:
        raise ValueError
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2 and parts[1].isdigit():
            lead = parts[0].replace(".", "")
            s = f"{lead}.{parts[1]}"
        else:
            s = s.replace(",", "")
    prefix = "-" if negative else ""
    return prefix + s


def _max_file_bytes() -> int:
    raw = os.getenv("OPENROUTER_MAX_FILE_BYTES", "").strip()
    if not raw:
        return _DEFAULT_MAX_FILE_BYTES
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_MAX_FILE_BYTES
    return max(1, parsed)


def _timeout_seconds() -> int:
    raw = os.getenv("OPENROUTER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS
    return max(5, parsed)


def _pdf_parser_engine() -> str:
    configured = os.getenv("OPENROUTER_PDF_ENGINE", "").strip().lower()
    if configured in {"pdf-text", "mistral-ocr", "native"}:
        return configured
    return _DEFAULT_PDF_ENGINE


def _schema_prompt(default_currency: str) -> str:
    fb = _coerce_currency(default_currency, fallback="HKD")
    allowed = ", ".join(_SUPPORTED_CURRENCIES)
    return (
        "Extract every transaction from the attached finance / bank statement "
        "and return strict JSON only matching this shape: "
        '{"lines": [{"dateUtc":"YYYY-MM-DDTHH:MM:SS.000Z", '
        '"type":"income|expenditure|mortgage", "description":"string", '
        '"netAmount":number, "vat":number, "grossAmount":number, '
        '"currency":"3-letter ISO"}]}.'
        " Rules: "
        "(1) dateUtc must be an ISO-8601 UTC instant — if only a date is "
        "shown use 00:00:00.000Z time. "
        "(2) type is 'income' for credits / money in, 'expenditure' for "
        "debits / money out that are not mortgage payments, and 'mortgage' "
        "for any line whose payee, reference, or description is labeled "
        "MTG or clearly indicates a mortgage payment (typically a debit). "
        "(3) Amounts are positive numbers in major currency units. "
        "grossAmount is the absolute value of the transaction. "
        "If VAT is not shown, set vat to 0 and netAmount equal to "
        "grossAmount. Otherwise netAmount + vat must equal grossAmount. "
        f"(4) currency is one of: {allowed}. Use the document's currency "
        f"when shown, otherwise default to {fb}. "
        "(5) Do not invent transactions. If the document is empty return "
        '{"lines": []}. '
        "(6) No markdown, no prose, no comments — JSON only."
    )


def reset_api_key_cache_for_tests() -> None:
    """Test helper: clear the shared client's API key cache."""
    openrouter_client.reset_api_key_cache_for_tests()
