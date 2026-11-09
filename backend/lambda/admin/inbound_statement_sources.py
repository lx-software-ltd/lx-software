"""Choose the files an inbound statement message should be parsed from.

Every finance inbox uses this module. A PDF attachment stays the only
source when the message has one. Otherwise a receipt image, or a text,
CSV, or HTML file, is used when the body does not itself name an amount.
The body is used when the subject or the text names an amount, and also
when that text is long enough to be a prose bill and nothing else is
attached. A date header on its own is not an amount.
"""

from __future__ import annotations

import os
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import NamedTuple

from board_mail import html_to_text

BODY_FILENAME = "email-body.txt"
MIN_STATEMENT_IMAGE_BYTES = 8 * 1024
_PROSE_MIN_CHARS = 40
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
_MONEY_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:usd|eur|gbp|hkd|cny|sgd|aed)\s*\d"
    r"|\d[\d.,]*\s*(?:usd|eur|gbp|hkd|cny|sgd|aed)\b"
    r"|(?:hk\$|us\$|[$£€¥])\s*\d"
    r"|\d+[.,]\d{2}\b"
    r"|\b(?:total|amount|balance|charged)\b[^\d\n]{0,24}\d"
    r")"
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
        out.append((bytes(payload), _sanitize_pdf_filename(fn)))
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


def _worth_reading(text: str) -> bool:
    if _has_money(text):
        return True
    return len(text.strip()) >= _PROSE_MIN_CHARS and re.search(r"\d", text) is not None


def _attachment_sources(msg: EmailMessage, body_ids: set[int]) -> list[StatementSource]:
    out: list[StatementSource] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or id(part) in body_ids:
            continue
        if part.get_content_type() == "application/pdf":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
            continue
        filename = part.get_filename() or ""
        mapped = _mapped_type(part.get_content_type(), filename)
        if mapped is None:
            continue
        blob = bytes(payload)
        if mapped.startswith("image/"):
            if len(blob) < MIN_STATEMENT_IMAGE_BYTES:
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
        if not _worth_reading(text):
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


def extract_statement_sources(raw: bytes) -> list[StatementSource]:
    """PDF parts, or a non-PDF attachment, or the body, for any statement inbox."""
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
    if _has_money(signal):
        return [
            StatementSource(
                data=_body_document(msg, body),
                filename=BODY_FILENAME,
                content_type="text/plain",
                kind="body",
            )
        ]
    attachments = _attachment_sources(msg, body_ids)
    if attachments:
        return attachments
    if _worth_reading(signal):
        return [
            StatementSource(
                data=_body_document(msg, body),
                filename=BODY_FILENAME,
                content_type="text/plain",
                kind="body",
            )
        ]
    return []
