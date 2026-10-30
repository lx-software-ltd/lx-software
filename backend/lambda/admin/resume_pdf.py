"""Render a resume PDF from the paragraph map.

The variable Noto files already in ``fonts/`` cannot be subset by fpdf2
(``avar`` without a usable ``fvar`` after subset). Regular and bold here are
static instances of that family. The Traditional Chinese file is a static
instance of ``NotoSansTC-Regular.otf``, loaded only when the text needs it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from resume_store import ResumeError

_FONTS = Path(__file__).resolve().parent / "fonts"
_REGULAR = _FONTS / "NotoSans-Text-Regular.ttf"
_BOLD = _FONTS / "NotoSans-Bold.ttf"
_ITALIC = _FONTS / "NotoSans-Italic.ttf"
_CJK = _FONTS / "NotoSansTC-Regular.ttf"
_CJK_OK: bool | None = None


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def cjk_supported() -> bool:
    """True when the static Traditional Chinese font embeds. Cached per process."""
    global _CJK_OK
    if _CJK_OK is not None:
        return _CJK_OK
    if not _CJK.is_file():
        _CJK_OK = False
        return False
    try:
        pdf = FPDF(format="A4")
        pdf.set_margin(15)
        pdf.add_font("TC", "", str(_CJK))
        pdf.add_page()
        pdf.set_font("TC", size=12)
        pdf.multi_cell(pdf.epw, 8, "中")
        pdf.output()
    except Exception:
        _CJK_OK = False
        return False
    _CJK_OK = True
    return True


def _family(text: str) -> tuple[str, str]:
    if _has_cjk(text):
        if not cjk_supported():
            raise ResumeError("PDF export is Latin-only for now.")
        return "TC", ""
    return "Noto", ""


def render(
    paragraphs: list[dict[str, Any]],
    layout: dict[str, Any],
    *,
    page_size: str = "A4",
) -> bytes:
    if not _REGULAR.is_file() or not _BOLD.is_file() or not _ITALIC.is_file():
        raise ResumeError("PDF fonts are not installed.")
    pdf = FPDF(format="Letter" if page_size == "Letter" else "A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margin(15)
    pdf.add_font("Noto", "", str(_REGULAR))
    pdf.add_font("Noto", "B", str(_BOLD))
    pdf.add_font("Noto", "I", str(_ITALIC))
    if cjk_supported():
        pdf.add_font("TC", "", str(_CJK))
    pdf.add_page()
    roles = {str(item.get("id")): str(item.get("role") or "other") for item in layout.get("paragraphs") or []}
    for paragraph in paragraphs:
        text = str(paragraph.get("text") or "").strip()
        if not text:
            continue
        role = roles.get(str(paragraph.get("id")), "other")
        family, _style = _family(text)
        if role == "name":
            _write(pdf, text, family, "B" if family == "Noto" else "", 20, 10)
        elif role == "contact":
            _write(pdf, text, family, "", 9, 5)
        elif role == "section_heading":
            pdf.ln(2)
            _write(pdf, text, family, "B" if family == "Noto" else "", 11, 6)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(1)
        elif role == "headline":
            _write(pdf, text, family, "B" if family == "Noto" else "", 12, 6)
        elif role == "role_header":
            pdf.ln(1)
            _write(pdf, text, family, "B" if family == "Noto" else "", 11, 6)
        elif role == "role_meta":
            _write(pdf, text, family, "I" if family == "Noto" else "", 10, 5)
        elif role == "bullet":
            _bullet(pdf, text, family)
        else:
            _write(pdf, text, family, "", 11, 6)
    return bytes(pdf.output())


def _write(pdf: FPDF, text: str, family: str, style: str, size: int, leading: int) -> None:
    pdf.set_font(family, style, size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, leading, text)


def _bullet(pdf: FPDF, text: str, family: str) -> None:
    pdf.set_font(family, "", 11)
    pdf.set_x(pdf.l_margin)
    pdf.cell(6, 6, "•", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.multi_cell(pdf.epw - 6, 6, text)
