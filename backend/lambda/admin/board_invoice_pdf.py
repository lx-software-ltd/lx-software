"""Minimal PDF renderer for listing invoices (no third-party PDF library).

The page uses the base-14 Helvetica font with WinAnsiEncoding, so only
cp1252 text can be drawn. Anything else (Chinese names, emoji) is dropped
after NFKD folding and the caller is told via :attr:`InvoicePdf.notes` so
the tool result can say so instead of shipping ``???``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date

from contract_constants import BOARD_KEY

PDF_ENCODING = "cp1252"
NON_LATIN_NOTE = "Some characters could not be printed in the PDF (Latin text only)."


@dataclass(frozen=True)
class InvoicePdf:
    data: bytes
    notes: tuple[str, ...] = ()


def winansi(text: str) -> tuple[str, bool]:
    """Fold ``text`` to cp1252; returns ``(printable, lossy)``."""
    out: list[str] = []
    lossy = False
    for ch in unicodedata.normalize("NFKD", str(text or "")):
        if unicodedata.combining(ch):
            continue
        try:
            ch.encode(PDF_ENCODING)
        except UnicodeEncodeError:
            lossy = True
            continue
        out.append(ch)
    return "".join(out), lossy


def render_invoice(
    *,
    number: str,
    amount_hkd: float,
    fps_reference: str,
    issued_on: str,
    due_on: str,
    payer_contact: str = "",
) -> InvoicePdf:
    """One-page PDF the payer can print or forward to their bank."""
    lines = [
        "Siu Tin Dei - listing invoice",
        f"Invoice {number}",
        f"Issued {issued_on}   Due {due_on}",
        f"Amount  HK$ {amount_hkd:.2f}",
        f"Pay by FPS quoting {fps_reference}",
    ]
    if payer_contact:
        lines.append(f"Billed to {payer_contact}")
    lines.extend(["", "The siutindei team"])
    printable: list[str] = []
    lossy = False
    for line in lines:
        text, dropped = winansi(line)
        lossy = lossy or dropped
        printable.append(text)
    return InvoicePdf(data=_simple_pdf(printable), notes=(NON_LATIN_NOTE,) if lossy else ())


def render_invoice_pdf(**kwargs: object) -> bytes:
    return render_invoice(**kwargs).data  # type: ignore[arg-type]


def render_text_pdf(
    lines: list[str], *, font_size: int = 11, leading: int = 14
) -> bytes:
    """One-page Helvetica PDF from already-WinAnsi lines."""
    printable: list[str] = []
    for line in lines:
        text, _dropped = winansi(line)
        printable.append(text)
    return _simple_pdf(printable, font_size=font_size, leading=leading)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _simple_pdf(
    lines: list[str], *, font_size: int = 12, leading: int = 18
) -> bytes:
    content_lines = ["BT", f"/F1 {int(font_size)} Tf", "50 780 Td"]
    for i, line in enumerate(lines):
        if i:
            content_lines.append(f"0 -{int(leading)} Td")
        content_lines.append(f"({_escape(line[:110])}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode(PDF_ENCODING)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_at = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    )
    return bytes(out)


def invoice_s3_key(invoice_id: str, issued_on: str | None = None) -> str:
    year = (issued_on or date.today().isoformat())[:4]
    safe = "".join(ch for ch in invoice_id if ch.isalnum() or ch in "-_")[:64]
    return f"board/{BOARD_KEY}/invoices/{year}/{safe}.pdf"
