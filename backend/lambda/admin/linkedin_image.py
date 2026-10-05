"""Black-and-white comic panels for LinkedIn drafts.

One OpenRouter Image API call per post, then Pillow: grayscale, a square (or
the saved format) canvas, and the caption in italic serif under the panel.
The owner's photo is used once, to draw a character sheet; later pictures
send that sheet, not the photo. A picture that is still pending or that
failed does not block publishing: the post goes out as text.
"""

from __future__ import annotations

import base64
import random
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import board_async
import board_store
import linkedin_store
import openrouter_client
import openrouter_usage
from http_common import _log_event
from linkedin_store import LinkedInError
from openrouter_client import ImageGeneration, OpenRouterError

SERVICE = "linkedin"
_FONT = Path(__file__).resolve().parent / "fonts" / "NotoSerif-Italic.ttf"
# Panel plus a 200px caption strip. Square is the feed default.
FORMATS: dict[str, dict[str, Any]] = {
    "square": {"aspect": "4:3", "panel": (1200, 1000), "canvas": (1200, 1200)},
    "portrait": {"aspect": "1:1", "panel": (1080, 1150), "canvas": (1080, 1350)},
    "wide": {"aspect": "16:9", "panel": (1200, 675), "canvas": (1200, 875)},
}
_STRIP = 200
HEAD_SIZE = (768, 768)
Generate = Callable[..., ImageGeneration]


def image_model(settings: dict[str, Any]) -> str:
    return str(settings.get("imageModel") or "").strip() or linkedin_store.DEFAULT_IMAGE_MODEL


def blocked_term(text: str, settings: dict[str, Any]) -> str:
    """A forbidden or product phrase in the picture prompt. Empty when it is clean."""
    haystack = (text or "").lower()
    for term in linkedin_store.forbidden_terms(settings):
        if linkedin_store.contains_term(haystack, term):
            return term
    if not settings.get("allowProductMentions"):
        for term in linkedin_store.PRODUCT_PHRASES:
            if linkedin_store.contains_term(haystack, term):
                return term
    return ""


def fallback_scene(body: str) -> str:
    hook = linkedin_store.hook_text(body)[:160]
    if not hook:
        hook = "the problem in the post"
    return f"The author at a desk, physically wrestling with this problem: {hook}"


def build_prompt(settings: dict[str, Any], scene: str) -> str:
    style = str(settings.get("imageStyle") or "").strip() or linkedin_store.RECOMMENDED_IMAGE_STYLE
    character = str(settings.get("imageCharacter") or "").strip() or linkedin_store.DEFAULT_IMAGE_CHARACTER
    return (
        f"{style} The person, drawn the same way each time: {character} "
        f"Scene: {scene} No second recognisable person. No logos, no brand names."
    )


def character_prompt(settings: dict[str, Any]) -> str:
    style = str(settings.get("imageStyle") or "").strip() or linkedin_store.RECOMMENDED_IMAGE_STYLE
    character = str(settings.get("imageCharacter") or "").strip() or linkedin_store.DEFAULT_IMAGE_CHARACTER
    return (
        f"{style} Head-and-shoulders portrait of this person, facing the viewer, a slight smile, "
        f"plain background. No text, no lettering. The person: {character}"
    )


def _data_url(content_type: str, data: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}}


def _mark(table: Any, post_id: str, **fields: Any) -> None:
    doc = linkedin_store.get_post(table, post_id)
    if not doc:
        return
    image = dict(doc.get("image") or {}) if isinstance(doc.get("image"), dict) else {}
    image.update(fields)
    doc["image"] = image
    linkedin_store.put_post(table, doc)


def queue_for_post(
    table: Any,
    post_id: str,
    *,
    scene: str = "",
    caption: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Mark the picture pending and enqueue the worker. Raises when one is already running."""
    doc = linkedin_store.get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    if str(doc.get("status") or "") in ("published", "archived"):
        raise LinkedInError("That post can no longer be edited.")
    current = doc.get("image") if isinstance(doc.get("image"), dict) else {}
    if (
        not force
        and str(current.get("status") or "") == "pending"
        and not linkedin_store.image_pending_stale(current)
    ):
        raise LinkedInError("A picture is already being drawn.")
    scene_text = (scene or str(current.get("scene") or "") or fallback_scene(str(doc.get("body") or ""))).strip()
    caption_text = (caption or str(current.get("caption") or "") or linkedin_store.FALLBACK_IMAGE_CAPTION).strip()
    doc["image"] = {
        "status": "pending",
        "scene": scene_text[: linkedin_store.IMAGE_SCENE_MAX],
        "caption": caption_text[: linkedin_store.IMAGE_CAPTION_MAX],
        "requestedAt": board_store.now_iso(),
        "contentType": str(current.get("contentType") or ""),
        "bytes": int(current.get("bytes") or 0),
        "error": "",
        "model": str(current.get("model") or ""),
    }
    linkedin_store.put_post(table, doc)
    accepted = board_async.try_invoke_event({"internal": "linkedin_image", "postId": post_id})
    if not accepted:
        _mark(table, post_id, status="failed", error="Could not queue the picture.")
    stored = linkedin_store.get_post(table, post_id) or doc
    return stored


def render_post(table: Any, post_id: str, *, generate: Generate | None = None) -> dict[str, Any]:
    """Draw one panel for a pending post. A failure leaves the draft and marks the picture failed."""
    doc = linkedin_store.get_post(table, post_id)
    if not doc:
        return {"ok": False, "error": "post not found"}
    settings = linkedin_store.load_settings(table)
    image = doc.get("image") if isinstance(doc.get("image"), dict) else {}
    if not settings.get("imagesEnabled"):
        _mark(table, post_id, status="failed", error="Pictures are turned off.")
        return {"ok": False, "error": "disabled"}
    if str(image.get("status") or "") == "ready" and image.get("contentType"):
        return {"ok": True, "skipped": "ready"}
    scene = str(image.get("scene") or "") or fallback_scene(str(doc.get("body") or ""))
    caption = str(image.get("caption") or "") or linkedin_store.FALLBACK_IMAGE_CAPTION
    prompt = build_prompt(settings, scene)
    term = blocked_term(prompt, settings)
    if term:
        _mark(table, post_id, status="failed", error=f"Remove “{term}” from the picture.")
        return {"ok": False, "error": "blocked"}
    if linkedin_store.month_spend(table) >= float(settings["maxUsdPerMonth"]):
        _mark(table, post_id, status="failed", error="The monthly draft budget is used up.")
        return {"ok": False, "error": "budget"}
    fmt = str(settings.get("imageFormat") or "square")
    if fmt not in FORMATS:
        fmt = "square"
    sheet = linkedin_store.load_character_sheet()
    references = [_data_url(sheet[0], sheet[1])] if sheet else None
    seed = random.SystemRandom().randrange(1, 2**31)
    caller = generate or _live_generate
    try:
        result = caller(prompt, FORMATS[fmt]["aspect"], seed, references, settings, n=1)
    except OpenRouterError as exc:
        _log_event("warning", tag="linkedin_image_failed", error=str(exc)[:300])
        _mark(table, post_id, status="failed", error=str(exc)[:300])
        return {"ok": False, "error": str(exc)[:300]}
    if not result.images:
        _mark(table, post_id, status="failed", error="OpenRouter returned no image.")
        return {"ok": False, "error": "empty"}
    try:
        png = compose(result.images[0].data, caption, fmt)
    except LinkedInError as exc:
        _mark(table, post_id, status="failed", error=str(exc))
        return {"ok": False, "error": str(exc)}
    _book(table, result)
    linkedin_store.save_post_image(table, post_id, "image/png", png)
    _mark(
        table,
        post_id,
        status="ready",
        scene=scene[: linkedin_store.IMAGE_SCENE_MAX],
        caption=caption[: linkedin_store.IMAGE_CAPTION_MAX],
        model=result.model or image_model(settings),
        seed=seed,
        cost=round(result.cost_usd, 6),
        error="",
    )
    return {"ok": True, "postId": post_id}


def draw_character(table: Any, *, generate: Generate | None = None) -> dict[str, Any]:
    """Four black-and-white headshots from the stored photo. The owner picks one."""
    photo = linkedin_store.load_character_photo(table)
    if not photo:
        return {"ok": False, "error": "Upload a photo first."}
    settings = linkedin_store.load_settings(table)
    prompt = character_prompt(settings)
    term = blocked_term(prompt, settings)
    if term:
        return {"ok": False, "error": f"Remove “{term}” from the picture."}
    if linkedin_store.month_spend(table) >= float(settings["maxUsdPerMonth"]):
        return {"ok": False, "error": "The monthly draft budget is used up."}
    seed = random.SystemRandom().randrange(1, 2**31)
    references = [_data_url(photo[0], photo[1])]
    caller = generate or _live_generate
    images: list[Any] = []
    model = ""
    try:
        result = caller(prompt, "1:1", seed, references, settings, n=4)
        images = list(result.images)
        model = result.model
        _book(table, result)
    except OpenRouterError:
        images = []
    if len(images) < 4:
        for offset in range(4 - len(images)):
            try:
                one = caller(prompt, "1:1", seed + offset + 1, references, settings, n=1)
            except OpenRouterError as exc:
                _log_event("warning", tag="linkedin_character_failed", error=str(exc)[:300])
                break
            images.extend(one.images)
            model = model or one.model
            _book(table, one)
    linkedin_store.clear_character_candidates(table)
    saved: list[str] = []
    for index, image in enumerate(images[:4]):
        try:
            png = _png_bytes(_to_ink(image.data, HEAD_SIZE))
        except LinkedInError:
            continue
        candidate_id = f"c{index + 1}"
        linkedin_store.save_character_candidate(table, candidate_id, "image/png", png)
        saved.append(candidate_id)
    if not saved:
        return {"ok": False, "error": "The picture could not be read."}
    return {"ok": True, "candidates": saved, "model": model}


def compose(data: bytes, caption: str, fmt: str) -> bytes:
    """Grayscale panel, white caption strip, italic serif, single quotes."""
    spec = FORMATS.get(fmt) or FORMATS["square"]
    panel = _to_ink(data, tuple(spec["panel"]))
    canvas_size = tuple(spec["canvas"])
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("L", canvas_size, 255)
    canvas.paste(panel, (0, 0))
    quoted = "'" + linkedin_store.caption_alt(caption) + "'"
    draw = ImageDraw.Draw(canvas)
    font = _font(44)
    lines = _wrap(draw, quoted, font, canvas_size[0] - 80)[:2]
    line_height = 52
    block = line_height * len(lines)
    top = spec["panel"][1] + max(8, (_STRIP - block) // 2)
    for line in lines:
        width = draw.textlength(line, font=font)
        draw.text(((canvas_size[0] - width) / 2, top), line, fill=0, font=font)
        top += line_height
    return _png_bytes(canvas)


def _to_ink(data: bytes, size: tuple[int, int]):
    from PIL import Image, ImageOps

    try:
        opened = Image.open(BytesIO(data))
        opened.load()
    except Exception as exc:  # noqa: BLE001 — any unreadable file is a failed picture
        raise LinkedInError("The picture could not be read.") from exc
    grey = ImageOps.autocontrast(opened.convert("L"))
    return ImageOps.fit(grey, size, method=Image.Resampling.LANCZOS)


def _png_bytes(image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _font(size: int):
    from PIL import ImageFont

    if _FONT.is_file():
        return ImageFont.truetype(str(_FONT), size=size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    if len(lines) > 2:
        lines = lines[:2]
        if not lines[1].endswith("…"):
            lines[1] = lines[1].rstrip(".") + "…"
    return lines


def _book(table: Any, result: ImageGeneration) -> None:
    if result.cost_usd:
        linkedin_store.add_spend(table, result.cost_usd)
    try:
        openrouter_usage.add_usage_day(
            table,
            service=SERVICE,
            owner="image",
            usage=result.usage,
            calls=1,
        )
    except Exception as exc:  # noqa: BLE001 — accounting must not drop the picture
        _log_event("warning", tag="linkedin_image_usage_failed", error=str(exc)[:200])


def _live_generate(
    prompt: str,
    aspect: str,
    seed: int,
    references: list[dict[str, Any]] | None,
    settings: dict[str, Any],
    n: int = 1,
) -> ImageGeneration:
    import os

    import boto3

    return openrouter_client.generate_image(
        model=image_model(settings),
        prompt=prompt,
        secrets_client=boto3.client("secretsmanager"),
        timeout=int(os.environ.get("LINKEDIN_IMAGE_TIMEOUT_SECONDS") or "90"),
        aspect_ratio=aspect,
        resolution="1K",
        n=n,
        output_format="png",
        seed=seed,
        input_references=references,
        service=SERVICE,
        owner="image",
    )
