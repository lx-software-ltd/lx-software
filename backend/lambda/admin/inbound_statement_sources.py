"""Choose the files an inbound statement message should be parsed from.

Every finance inbox uses this module. A PDF, including a ``.pdf`` file
whose content type is not ``application/pdf``, is the only source when
the message has one. Otherwise an itemised text, CSV, or HTML attachment,
or a receipt image that is not inline or decorative, is the source. The
body is used only when the subject or body names an amount and no
statement attachment was found. A date, a version, or a bare discount is
not an amount.
"""

from __future__ import annotations

import hashlib
import os
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import NamedTuple

from board_mail import html_to_text

BODY_FILENAME_PREFIX = "email-body-"
MIN_STATEMENT_IMAGE_BYTES = 8 * 1024
_BODY_MAX_CHARS = 100_000

_IMAGE_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
    "image/gif": "image/gif",
}
_TEXT_TYPES = frozenset({"text/plain", "text/csv", "text/html", "application/xhtml+xml"})
_OCTET_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})
_EXT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
}
_IMAGE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_PDF_TYPES = frozenset({"application/pdf", "application/x-pdf"})
_CURRENCIES = "usd|eur|gbp|hkd|cny|sgd|aed"
# A currency code, an explicit HK$/US$ amount, a symbol with cents, or a
# total/amount/balance/charged label beside a number. A bare decimal matches
# dates (09.11.2026) and versions (2.10); a bare "$10" matches discounts.
_MONEY_RE = re.compile(
    rf"(?i)(?:"
    rf"\b(?:{_CURRENCIES})\s*\d"
    rf"|\d[\d.,]*\s*(?:{_CURRENCIES})\b"
    rf"|(?:hk\$|us\$)\s*\d"
    rf"|[$£€¥]\s*\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})\b"
    rf"|\b(?:total|amount|balance|charged)\b[^\d\n]{{0,24}}\d"
    rf")"
)
_DECORATIVE_IMAGE_NAME = re.compile(
    r"(?i)(?:^|[^a-z])(?:logo|icon|banner|pixel|spacer|signature|header|footer|"
    r"facebook|twitter|linkedin|instagram)(?:[^a-z]|$)"
)


class StatementSource(NamedTuple):
    """One object to copy into the assets bucket and parse."""

    data: bytes
    filename: str
    content_type: str
    kind: str


def _sanitize_pdf_filename(name: str) -> str:
    base = os.path.basename((name or "").strip() or "statement.pdf")
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:180]
    return safe or "statement.pdf"


def _is_pdf_part(part: EmailMessage, payload: bytes) -> bool:
    """True for a PDF content type, a ``.pdf`` name, or PDF bytes on an octet-stream."""
    ctype = part.get_content_type()
    name = (part.get_filename() or "").lower()
    if ctype in _PDF_TYPES or name.endswith(".pdf"):
        return True
    return payload.startswith(b"%PDF") and ctype in _OCTET_TYPES


def extract_pdf_attachments(raw: bytes) -> list[tuple[bytes, str]]:
    """Return ``(pdf_bytes, safe_filename)`` for every PDF part, in walk order."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    out: list[tuple[bytes, str]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
            continue
        blob = bytes(payload)
        if not _is_pdf_part(part, blob):
            continue
        out.append((blob, _sanitize_pdf_filename(part.get_filename() or "statement.pdf")))
    return out


def extract_first_pdf_attachment(raw: bytes) -> tuple[bytes, str] | None:
    """Return ``(pdf_bytes, safe_filename)`` for the first PDF part, if any."""
    parts = extract_pdf_attachments(raw)
    return parts[0] if parts else None


def _has_money(text: str) -> bool:
    return _MONEY_RE.search(text or "") is not None


def _collapse(value: object) -> str:
    return " ".join(str(value or "").split())


def _part_text(part: EmailMessage | None) -> str:
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)):
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            content = bytes(payload).decode(charset, "replace")
        except LookupError:
            content = bytes(payload).decode("utf-8", "replace")
    if not isinstance(content, str):
        return ""
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return content.replace("\r\n", "\n").strip()


def _body_part(msg: EmailMessage, preference: tuple[str, ...]) -> EmailMessage | None:
    try:
        return msg.get_body(preferencelist=preference)
    except Exception:
        return None


def _choose_body(plain: str, html: str) -> str:
    plain_money = _has_money(plain)
    html_money = _has_money(html)
    if html_money and not plain_money:
        return html
    if plain.strip():
        return plain
    return html


def _signal_text(subject: str, body: str) -> str:
    """Subject plus body. The date header is omitted so a timestamp is not an amount."""
    return f"{subject}\n{body}".strip()


def _body_filename(msg: EmailMessage, body: str) -> str:
    """A stable name that differs when the subject or body differs."""
    subject = _collapse(msg.get("Subject"))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", subject).strip("-").lower()[:32] or "message"
    stamp = _collapse(msg.get("Message-ID")) or _collapse(msg.get("Date")) or ""
    digest = hashlib.sha256(f"{stamp}\n{subject}\n{body}".encode()).hexdigest()[:8]
    return f"{BODY_FILENAME_PREFIX}{slug}-{digest}.txt"[:180]


def _body_document(msg: EmailMessage, body: str) -> bytes:
    subject = _collapse(msg.get("Subject"))
    sender = _collapse(msg.get("From"))
    when = _collapse(msg.get("Date"))
    lines: list[str] = []
    if subject:
        lines.append(f"Subject: {subject}")
    if sender:
        lines.append(f"From: {sender}")
    if when:
        lines.append(f"Date: {when}")
    if lines:
        lines.append("")
    lines.append(body.strip())
    return "\n".join(lines).strip()[:_BODY_MAX_CHARS].encode("utf-8")


def _safe_token(name: str, default: str) -> str:
    base = os.path.basename((name or "").strip() or default)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:180]
    return safe or default


def _mapped_type(content_type: str, filename: str) -> str | None:
    if content_type in _IMAGE_TYPES:
        return _IMAGE_TYPES[content_type]
    if content_type in _TEXT_TYPES:
        return content_type
    if content_type in _OCTET_TYPES or not content_type:
        return _EXT_TYPES.get(os.path.splitext(filename)[1].lower())
    return None


def _image_filename(filename: str, mapped: str) -> str:
    ext = _IMAGE_EXT[mapped]
    safe = _safe_token(filename, f"receipt{ext}")
    lowered = safe.lower()
    if lowered.endswith(ext) or (mapped == "image/jpeg" and lowered.endswith(".jpeg")):
        return safe
    stem = os.path.splitext(safe)[0] or "receipt"
    return f"{stem}{ext}"[:180]


def _text_filename(filename: str) -> str:
    safe = _safe_token(filename, "attachment.txt")
    stem = os.path.splitext(safe)[0] or "attachment"
    return f"{stem}.txt"[:180]


def _decode_text(part: EmailMessage, payload: bytes, mapped: str) -> str:
    charset = part.get_content_charset() or "utf-8"
    try:
        text = payload.decode(charset, "replace")
    except LookupError:
        text = payload.decode("utf-8", "replace")
    if mapped in {"text/html", "application/xhtml+xml"}:
        text = html_to_text(text)
    return text.replace("\r\n", "\n").strip()


def _skip_image(part: EmailMessage, filename: str, size: int) -> bool:
    """Inline, tiny, and decorative images are not receipts."""
    if size < MIN_STATEMENT_IMAGE_BYTES:
        return True
    if _DECORATIVE_IMAGE_NAME.search(filename or ""):
        return True
    if (part.get_content_disposition() or "").lower() == "inline":
        return True
    return bool(part.get("Content-ID"))


def _attachment_sources(msg: EmailMessage, body_ids: set[int]) -> list[StatementSource]:
    out: list[StatementSource] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or id(part) in body_ids:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
            continue
        blob = bytes(payload)
        if _is_pdf_part(part, blob):
            continue
        filename = part.get_filename() or ""
        mapped = _mapped_type(part.get_content_type(), filename)
        if mapped is None:
            continue
        if mapped.startswith("image/"):
            if _skip_image(part, filename, len(blob)):
                continue
            out.append(
                StatementSource(
                    data=blob,
                    filename=_image_filename(filename, mapped),
                    content_type=mapped,
                    kind="attachment",
                )
            )
            continue
        text = _decode_text(part, blob, mapped)
        if not _has_money(text):
            continue
        out.append(
            StatementSource(
                data=text[:_BODY_MAX_CHARS].encode("utf-8"),
                filename=_text_filename(filename),
                content_type="text/plain",
                kind="attachment",
            )
        )
    return out


def _body_source(msg: EmailMessage, body: str) -> StatementSource:
    return StatementSource(
        data=_body_document(msg, body),
        filename=_body_filename(msg, body),
        content_type="text/plain",
        kind="body",
    )


def extract_statement_sources(raw: bytes) -> list[StatementSource]:
    """PDF parts, else statement attachments, else a body that names an amount."""
    pdfs = extract_pdf_attachments(raw)
    if pdfs:
        return [
            StatementSource(data=data, filename=name, content_type="application/pdf", kind="pdf") for data, name in pdfs
        ]

    msg = BytesParser(policy=policy.default).parsebytes(raw)
    plain_part = _body_part(msg, ("plain",))
    html_part = _body_part(msg, ("html",))
    body = _choose_body(_part_text(plain_part), _part_text(html_part))
    signal = _signal_text(_collapse(msg.get("Subject")), body)
    body_ids = {id(part) for part in (plain_part, html_part) if part is not None}
    attachments = _attachment_sources(msg, body_ids)
    if attachments:
        return attachments
    if _has_money(signal):
        return [_body_source(msg, body)]
    return []
