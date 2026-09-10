"""Pillow template cards for the Executive Board content calendar (WP7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

TEMPLATES = ("spotlight", "guide", "seasonal", "quote", "news")
CARD_SIZE = (1080, 1080)
STORY_SIZE = (1080, 1920)
CJK_NO_START = "，。！？」）"
ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
BRAND_DIR = ROOT / "brand"

_brand_cache: dict[str, Any] | None = None


def load_brand() -> dict[str, Any]:
    global _brand_cache
    if _brand_cache is not None:
        return _brand_cache
    path = BRAND_DIR / "brand.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    _brand_cache = {
        "primary": str(raw.get("primary") or "#FF6B35"),
        "accent": str(raw.get("accent") or "#2EC4B6"),
        "text": str(raw.get("text") or "#1A1A1A"),
        "background": str(raw.get("background") or "#FFF8F0"),
        "logoPath": str(raw.get("logoPath") or "brand/logo.png"),
    }
    return _brand_cache


def _hex(color: str) -> tuple[int, int, int]:
    text = color.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"


def _font(path: Path, size: int, *, weight: int = 400) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size=size)
    setter = getattr(font, "set_variation_by_axes", None)
    if callable(setter):
        try:
            setter([100.0, float(weight)])
        except Exception:
            try:
                setter([float(weight)])
            except Exception:
                pass
    return font


def _pick_font(*, lang: str, bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "NotoSansTC-Regular.otf" if lang.startswith("zh") else "NotoSans-Regular.ttf"
    path = FONTS / name
    return _font(path, size, weight=700 if bold else 400)


def _text_width(font: ImageFont.ImageFont, text: str) -> int:
    if not text:
        return 0
    bbox = font.getbbox(text)
    return max(0, int(bbox[2] - bbox[0]))


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, *, max_lines: int = 6) -> list[str]:
    raw = " ".join(str(text or "").split())
    if not raw:
        return [""]
    lines: list[str] = []
    if any(_is_cjk(ch) for ch in raw):
        buf = ""
        for ch in raw:
            trial = buf + ch
            if buf and _text_width(font, trial) > max_width:
                if ch in CJK_NO_START and buf:
                    buf = buf + ch
                    lines.append(buf)
                    buf = ""
                    continue
                lines.append(buf)
                buf = ch
            else:
                buf = trial
        if buf:
            lines.append(buf)
    else:
        words = raw.split(" ")
        buf = ""
        for word in words:
            trial = word if not buf else f"{buf} {word}"
            if buf and _text_width(font, trial) > max_width:
                lines.append(buf)
                buf = word
            else:
                buf = trial
        if buf:
            lines.append(buf)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip()
        while last and _text_width(font, last + "…") > max_width:
            last = last[:-1]
        lines[-1] = (last or "").rstrip() + "…"
    return lines or [""]


def _fit_lines(text: str, *, lang: str, bold: bool, max_width: int, start_size: int) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    size = start_size
    while size >= 28:
        font = _pick_font(lang=lang, bold=bold, size=size)
        lines = wrap_text(text, font, max_width, max_lines=6)
        if not lines[-1].endswith("…") or size == 28:
            return font, lines, size
        size -= 4
    font = _pick_font(lang=lang, bold=bold, size=28)
    return font, wrap_text(text, font, max_width, max_lines=6), 28


def _paste_logo(im: Image.Image, *, box: tuple[int, int]) -> None:
    brand = load_brand()
    logo_path = ROOT / brand["logoPath"]
    if not logo_path.is_file():
        return
    logo = Image.open(logo_path).convert("RGBA")
    logo.thumbnail((120, 120))
    im.paste(logo, box, logo)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.ImageFont,
    *,
    xy: tuple[int, int],
    fill: tuple[int, int, int],
    line_gap: int = 12,
) -> int:
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = font.getbbox(line or " ")
        y += max(int(bbox[3] - bbox[1]), 28) + line_gap
    return y


def _base(size: tuple[int, int], template: str) -> Image.Image:
    brand = load_brand()
    bg = _hex(brand["background"])
    primary = _hex(brand["primary"])
    accent = _hex(brand["accent"])
    im = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(im)
    w, h = size
    if template == "spotlight":
        draw.rectangle((0, 0, w, 160), fill=primary)
        draw.rectangle((0, h - 80, w, h), fill=primary)
    elif template == "guide":
        draw.rectangle((0, 0, 48, h), fill=accent)
        draw.rectangle((w - 48, 0, w, h), fill=accent)
    elif template == "seasonal":
        draw.ellipse((-200, -200, 400, 400), fill=primary)
        draw.ellipse((w - 360, h - 360, w + 80, h + 80), fill=accent)
    elif template == "quote":
        draw.rectangle((80, 80, w - 80, h - 80), outline=primary, width=8)
    else:  # news
        draw.rectangle((0, 0, w, 28), fill=accent)
        draw.rectangle((0, h - 28, w, h), fill=primary)
    return im


def render_card(template: str, fields: dict[str, Any], *, lang: str = "en") -> bytes:
    return _render(CARD_SIZE, template, fields, lang=lang)


def render_story(template: str, fields: dict[str, Any], *, lang: str = "en") -> bytes:
    return _render(STORY_SIZE, template, fields, lang=lang)


def _render(size: tuple[int, int], template: str, fields: dict[str, Any], *, lang: str) -> bytes:
    name = str(template or "spotlight").strip().lower()
    if name not in TEMPLATES:
        name = "spotlight"
    lang = "zh-HK" if str(lang).startswith("zh") else "en"
    brand = load_brand()
    text_color = _hex(brand["text"])
    im = _base(size, name)
    draw = ImageDraw.Draw(im)
    w, h = size
    margin = 80 if h > 1200 else 72
    max_width = w - margin * 2
    kicker = str(fields.get("kicker") or fields.get("pillar") or name).upper()
    title = str(fields.get("title") or fields.get("headline") or fields.get("quote") or "Siu Tin Dei")
    body = str(fields.get("body") or fields.get("subtitle") or fields.get("credit") or "")
    kicker_font = _pick_font(lang="en", bold=True, size=28)
    draw.text((margin, 48 if h == 1080 else 80), kicker[:40], font=kicker_font, fill=_hex(brand["primary"]))
    title_font, title_lines, _ = _fit_lines(title, lang=lang, bold=True, max_width=max_width, start_size=72 if h == 1080 else 84)
    y = _draw_lines(draw, title_lines, title_font, xy=(margin, 200 if h == 1080 else 320), fill=text_color)
    if body:
        body_font, body_lines, _ = _fit_lines(body, lang=lang, bold=False, max_width=max_width, start_size=36)
        _draw_lines(draw, body_lines, body_font, xy=(margin, y + 24), fill=text_color)
    _paste_logo(im, box=(w - 160, h - 160))
    from io import BytesIO

    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
