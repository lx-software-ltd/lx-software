"""Black-and-white comic panels for LinkedIn drafts.

One OpenRouter Image API call per post, then Pillow: grayscale, the saved
format, and the caption in italic serif inside the bottom of that picture.
The owner's photo is used once, to draw a character sheet; later pictures
send that sheet, not the photo. A first picture that is still pending or that
failed does not block publishing. A redraw keeps the previous ready picture
until the new panel is saved.
"""

from __future__ import annotations

import base64
import random
import time
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
# The caption is drawn inside the canvas, so the aspect sent to the model is
# the finished picture. Square is the feed default.
FORMATS: dict[str, dict[str, Any]] = {
    "square": {"aspect": "1:1", "canvas": (1200, 1200)},
    "portrait": {"aspect": "4:5", "canvas": (1080, 1350)},
    "wide": {"aspect": "16:9", "canvas": (1200, 675)},
}
_CAPTION_INSET = 40
_CAPTION_PAD = 24
_CAPTION_SIZE = 44
_LINE_HEIGHT = 52
_FRAME = 2
HEAD_SIZE = (768, 768)
# Held against maxUsdPerMonth before the Image API call, then replaced by the
# real cost. Above the usual Seedream charge so parallel workers cannot all
# pass a check that has not moved yet.
IMAGE_HOLD_USD = 0.05
# Stop starting another 90s call once this much of the 300s Lambda is gone.
DRAW_BUDGET_SECONDS = 240
# Seedream 4.5 rejects 1K: those sizes are under its 3,686,400 pixel minimum.
# 2K is the tier that clears the floor for 1:1, 4:5, and 16:9.
IMAGE_RESOLUTION = "2K"
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
    """Used only when the draft model cannot write a scene for this post."""
    hook = linkedin_store.hook_text(body)[:160]
    if not hook:
        hook = "the problem in the post"
    return (
        "In a lift, the author is wedged in by one absurdly oversized object that stands for "
        f"this: {hook} The doors are trying to close on it."
    )


def build_prompt(settings: dict[str, Any], scene: str, expression: str = "") -> str:
    style = str(settings.get("imageStyle") or "").strip() or linkedin_store.RECOMMENDED_IMAGE_STYLE
    character = str(settings.get("imageCharacter") or "").strip() or linkedin_store.DEFAULT_IMAGE_CHARACTER
    face = (expression or "").strip() or linkedin_store.FALLBACK_IMAGE_EXPRESSION
    return (
        f"{style} The person, drawn the same way each time: {character} "
        f"Expression: {face}. Do not default to a smile. "
        f"Scene: {scene} Keep the lower edge of the picture quiet: floor, shadow, or paper, "
        "nothing that matters there. No second recognisable person. No logos, no brand names."
    )


def character_prompt(settings: dict[str, Any]) -> str:
    style = str(settings.get("imageStyle") or "").strip() or linkedin_store.RECOMMENDED_IMAGE_STYLE
    character = str(settings.get("imageCharacter") or "").strip() or linkedin_store.DEFAULT_IMAGE_CHARACTER
    return (
        f"{style} Convert this photo into a caricature for a gag cartoon. Simplified features, "
        "a slightly oversized head, small simple eyes, a few confident ink lines for hair, bold "
        "outlines, flat white skin with hatching only in shadow. Keep only what makes the person "
        "recognisable: hair shape, face shape, glasses if present. Not a portrait and not "
        "photographic shading. Ignore the expression in the photo. Head and shoulders, facing "
        "the viewer, neutral expression, mouth closed, plain background. No text, no lettering. "
        f"The person: {character}"
    )


def _data_url(content_type: str, data: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}}


def _mark(table: Any, post_id: str, *, clear_held: bool = False, **fields: Any) -> None:
    doc = linkedin_store.get_post(table, post_id, consistent=True)
    if not doc:
        return
    image = dict(doc.get("image") or {}) if isinstance(doc.get("image"), dict) else {}
    image.update(fields)
    if clear_held:
        image.pop("held", None)
    doc["image"] = image
    linkedin_store.put_post(table, doc)


def _fail_picture(table: Any, post_id: str, error: str) -> None:
    """Mark the picture failed without dropping a previous ready panel."""
    _mark(table, post_id, status="failed", error=error[:300])


def queue_for_post(
    table: Any,
    post_id: str,
    *,
    scene: str = "",
    caption: str = "",
    expression: str = "",
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
    # Blank fields stay blank here; the worker writes them from the post.
    scene_text = (scene or str(current.get("scene") or "")).strip()
    caption_text = linkedin_store.finish_caption(caption or str(current.get("caption") or ""))
    expression_text = (expression or str(current.get("expression") or "")).strip()
    held = _held_picture(current)
    doc["image"] = {
        "status": "pending",
        "scene": scene_text[: linkedin_store.IMAGE_SCENE_MAX],
        "caption": caption_text[: linkedin_store.IMAGE_CAPTION_MAX],
        "expression": expression_text[: linkedin_store.IMAGE_EXPRESSION_MAX],
        "requestedAt": board_store.now_iso(),
        "contentType": str(held.get("contentType") or "") if held else "",
        "bytes": int(held.get("bytes") or 0) if held else 0,
        "error": "",
        "model": str((held or {}).get("model") or ""),
    }
    if held:
        doc["image"]["held"] = held
    linkedin_store.put_post(table, doc)
    accepted = False
    try:
        accepted = board_async.try_invoke_event({"internal": "linkedin_image", "postId": post_id})
    except Exception as exc:  # noqa: BLE001 — a failed enqueue must not fail the draft save
        _log_event("warning", tag="linkedin_image_enqueue_failed", error=str(exc)[:300])
        accepted = False
    if not accepted:
        _fail_picture(table, post_id, "Could not queue the picture.")
    stored = linkedin_store.get_post(table, post_id, consistent=True) or doc
    return stored


def _held_picture(current: dict[str, Any]) -> dict[str, Any] | None:
    """The ready panel a redraw must keep until the new one is saved."""
    if str(current.get("status") or "") == "ready" and current.get("contentType"):
        return {
            "status": "ready",
            "scene": str(current.get("scene") or ""),
            "caption": str(current.get("caption") or ""),
            "expression": str(current.get("expression") or ""),
            "contentType": str(current.get("contentType") or ""),
            "bytes": int(current.get("bytes") or 0),
            "model": str(current.get("model") or ""),
        }
    previous = current.get("held")
    if isinstance(previous, dict) and previous.get("contentType"):
        return {
            "status": "ready",
            "scene": str(previous.get("scene") or ""),
            "caption": str(previous.get("caption") or ""),
            "expression": str(previous.get("expression") or ""),
            "contentType": str(previous.get("contentType") or ""),
            "bytes": int(previous.get("bytes") or 0),
            "model": str(previous.get("model") or ""),
        }
    return None


def picture_text(
    table: Any,
    settings: dict[str, Any],
    *,
    body: str,
    scene: str = "",
    expression: str = "",
    caption: str = "",
    brief: Callable[..., dict[str, str]] | None = None,
) -> tuple[str, str, str]:
    """Scene, expression, and caption for a post.

    Fields the owner or the draft already set are kept. Blank ones are written
    from the post by the draft model, so an owner-written post gets a picture
    about its own problem. When that call fails, a plain fallback stands in.
    """
    scene = scene.strip()
    expression = expression.strip()
    caption = linkedin_store.finish_caption(caption)
    if not (scene and expression and caption):
        import linkedin_draft

        writer = brief or linkedin_draft.picture_brief
        try:
            written, cost = writer(table=table, settings=settings, body=body)
        except Exception as exc:  # noqa: BLE001 — a missing brief falls back; the picture still draws
            _log_event("warning", tag="linkedin_picture_brief_failed", error=str(exc)[:300])
            written, cost = {}, 0.0
        if cost:
            try:
                linkedin_store.add_spend(table, cost)
            except Exception as exc:  # noqa: BLE001 — accounting must not drop the picture
                _log_event("warning", tag="linkedin_image_usage_failed", error=str(exc)[:200])
        scene = scene or str(written.get("imageScene") or "").strip() or fallback_scene(body)
        expression = (
            expression
            or str(written.get("imageExpression") or "").strip()
            or linkedin_store.FALLBACK_IMAGE_EXPRESSION
        )
        caption = caption or linkedin_store.finish_caption(
            str(written.get("imageCaption") or "") or linkedin_store.FALLBACK_IMAGE_CAPTION
        )
    return (
        scene[: linkedin_store.IMAGE_SCENE_MAX],
        expression[: linkedin_store.IMAGE_EXPRESSION_MAX],
        caption[: linkedin_store.IMAGE_CAPTION_MAX],
    )


def render_post(
    table: Any,
    post_id: str,
    *,
    generate: Generate | None = None,
    brief: Callable[..., dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Draw one panel for a pending post. A failure leaves the draft and marks the picture failed."""
    doc = linkedin_store.get_post(table, post_id, consistent=True)
    if not doc:
        return {"ok": False, "error": "post not found"}
    settings = linkedin_store.load_settings(table)
    image = doc.get("image") if isinstance(doc.get("image"), dict) else {}
    if not settings.get("imagesEnabled"):
        _fail_picture(table, post_id, "Pictures are turned off.")
        return {"ok": False, "error": "disabled"}
    if str(image.get("status") or "") == "ready" and image.get("contentType"):
        return {"ok": True, "skipped": "ready"}
    scene, expression, caption = picture_text(
        table,
        settings,
        body=str(doc.get("body") or ""),
        scene=str(image.get("scene") or ""),
        expression=str(image.get("expression") or ""),
        caption=str(image.get("caption") or ""),
        brief=brief,
    )
    if (scene, expression, caption) != (
        str(image.get("scene") or ""),
        str(image.get("expression") or ""),
        str(image.get("caption") or ""),
    ):
        _mark(table, post_id, scene=scene, expression=expression, caption=caption)
    prompt = build_prompt(settings, scene, expression)
    term = blocked_term(prompt, settings)
    if term:
        _fail_picture(table, post_id, f"Remove “{term}” from the picture.")
        return {"ok": False, "error": "blocked"}
    fmt = str(settings.get("imageFormat") or "square")
    if fmt not in FORMATS:
        fmt = "square"
    sheet = linkedin_store.load_character_sheet()
    references = [_data_url(sheet[0], sheet[1])] if sheet else None
    seed = random.SystemRandom().randrange(1, 2**31)
    caller = generate or _live_generate
    held_usd = 0.0
    try:
        if not linkedin_store.try_reserve_spend(table, IMAGE_HOLD_USD, float(settings["maxUsdPerMonth"])):
            _fail_picture(table, post_id, "The monthly draft budget is used up.")
            return {"ok": False, "error": "budget"}
        held_usd = IMAGE_HOLD_USD
        try:
            result = caller(prompt, FORMATS[fmt]["aspect"], seed, references, settings, n=1)
        except OpenRouterError as exc:
            _log_event("warning", tag="linkedin_image_failed", error=str(exc)[:300])
            _fail_picture(table, post_id, str(exc)[:300])
            return {"ok": False, "error": str(exc)[:300]}
        if not result.images:
            _fail_picture(table, post_id, "OpenRouter returned no image.")
            return {"ok": False, "error": "empty"}
        try:
            png = compose(result.images[0].data, caption, fmt)
            linkedin_store.save_post_image(table, post_id, "image/png", png)
        except LinkedInError as exc:
            _fail_picture(table, post_id, str(exc))
            return {"ok": False, "error": str(exc)}
        _book(table, result)
        _mark(
            table,
            post_id,
            clear_held=True,
            status="ready",
            scene=scene[: linkedin_store.IMAGE_SCENE_MAX],
            caption=caption[: linkedin_store.IMAGE_CAPTION_MAX],
            expression=expression[: linkedin_store.IMAGE_EXPRESSION_MAX],
            model=result.model or image_model(settings),
            seed=seed,
            cost=round(result.cost_usd, 6),
            error="",
        )
        return {"ok": True, "postId": post_id}
    except Exception as exc:  # noqa: BLE001 — S3 or Pillow must not leave the picture pending
        _log_event("error", tag="linkedin_image_failed", error=str(exc)[:300])
        _fail_picture(table, post_id, "The picture could not be saved.")
        return {"ok": False, "error": "save"}
    finally:
        if held_usd:
            _release(table, held_usd)


def draw_character(
    table: Any,
    *,
    generate: Generate | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Four black-and-white headshots from the stored photo. The owner picks one.

    Stops before another call could run past the Lambda timeout. Each image is
    reserved against the monthly cap before it is requested.
    """
    photo = linkedin_store.load_character_photo(table)
    if not photo:
        return {"ok": False, "error": "Upload a photo first."}
    settings = linkedin_store.load_settings(table)
    prompt = character_prompt(settings)
    term = blocked_term(prompt, settings)
    if term:
        return {"ok": False, "error": f"Remove “{term}” from the picture."}
    seed = random.SystemRandom().randrange(1, 2**31)
    references = [_data_url(photo[0], photo[1])]
    caller = generate or _live_generate
    tick = clock or time.monotonic
    started = tick()
    timeout = _image_timeout()
    holds = 0
    try:
        cap = float(settings["maxUsdPerMonth"])
        for _slot in range(4):
            if not linkedin_store.try_reserve_spend(table, IMAGE_HOLD_USD, cap):
                break
            holds += 1
        if holds < 1:
            return {"ok": False, "error": "The monthly draft budget is used up."}
        images: list[Any] = []
        model = ""

        def room() -> bool:
            return (tick() - started) + timeout <= DRAW_BUDGET_SECONDS

        if room():
            try:
                result = caller(prompt, "1:1", seed, references, settings, n=holds)
                images = list(result.images)[:holds]
                model = result.model
                _book(table, result)
            except OpenRouterError as exc:
                _log_event("warning", tag="linkedin_character_failed", error=str(exc)[:300])
                images = []
        offset = 0
        while len(images) < holds and room():
            offset += 1
            try:
                one = caller(prompt, "1:1", seed + offset, references, settings, n=1)
            except OpenRouterError as exc:
                _log_event("warning", tag="linkedin_character_failed", error=str(exc)[:300])
                break
            images.extend(one.images)
            model = model or one.model
            _book(table, one)
        linkedin_store.clear_character_candidates(table)
        saved: list[str] = []
        for index, image in enumerate(images[:holds]):
            try:
                png = _png_under_limit(_to_ink(image.data, HEAD_SIZE), linkedin_store.IMAGE_BYTE_MAX)
            except LinkedInError:
                continue
            candidate_id = f"c{index + 1}"
            linkedin_store.save_character_candidate(table, candidate_id, "image/png", png)
            saved.append(candidate_id)
        if not saved:
            if not room():
                return {"ok": False, "error": "The character sheet timed out. Draw it again."}
            return {"ok": False, "error": "The picture could not be read."}
        return {"ok": True, "candidates": saved, "model": model}
    finally:
        if holds:
            _release(table, IMAGE_HOLD_USD * holds)


def caption_lines(caption: str, *, width: int, font) -> list[str]:
    """The spoken line as drawn: wrapping quotes removed, at most two lines."""
    text = linkedin_store.caption_alt(caption)
    if not text:
        return []
    from PIL import Image, ImageDraw

    scratch = Image.new("L", (max(width, 1), 8), 255)
    return _wrap(ImageDraw.Draw(scratch), text, font, max(width, 1))


def compose(data: bytes, caption: str, fmt: str) -> bytes:
    """Grayscale picture with the caption in a box at the bottom of the same frame."""
    spec = FORMATS.get(fmt) or FORMATS["square"]
    canvas_size = tuple(spec["canvas"])
    from PIL import ImageDraw

    canvas = _to_ink(data, canvas_size)
    draw = ImageDraw.Draw(canvas)
    for offset in range(_FRAME):
        draw.rectangle(
            (offset, offset, canvas_size[0] - 1 - offset, canvas_size[1] - 1 - offset),
            outline=0,
        )
    font = _font(_CAPTION_SIZE)
    inner = canvas_size[0] - 2 * _CAPTION_INSET - 2 * _CAPTION_PAD
    lines = caption_lines(caption, width=inner, font=font)
    if lines:
        block = _LINE_HEIGHT * len(lines)
        box_h = block + 2 * _CAPTION_PAD
        left = _CAPTION_INSET
        right = canvas_size[0] - _CAPTION_INSET
        bottom = canvas_size[1] - _CAPTION_INSET
        top = max(_CAPTION_INSET, bottom - box_h)
        draw.rectangle((left, top, right - 1, bottom - 1), fill=255, outline=0, width=2)
        text_top = top + _CAPTION_PAD
        for line in lines:
            width = draw.textlength(line, font=font)
            draw.text(((canvas_size[0] - width) / 2, text_top), line, fill=0, font=font)
            text_top += _LINE_HEIGHT
    return _png_under_limit(canvas, linkedin_store.IMAGE_BYTE_MAX)


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


def _png_under_limit(image, limit: int) -> bytes:
    """PNG bytes, posterized when dense hatching would pass the save cap."""
    data = _png_bytes(image)
    if len(data) <= limit:
        return data
    from PIL import ImageOps

    reduced = data
    for bits in (4, 3, 2, 1):
        reduced = _png_bytes(ImageOps.posterize(image, bits))
        if len(reduced) <= limit:
            return reduced
    return reduced


def _book(table: Any, result: ImageGeneration) -> None:
    if result.cost_usd:
        try:
            linkedin_store.add_spend(table, result.cost_usd)
        except Exception as exc:  # noqa: BLE001 — accounting must not drop the picture
            _log_event("warning", tag="linkedin_image_usage_failed", error=str(exc)[:200])
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


def _release(table: Any, usd: float) -> None:
    try:
        linkedin_store.adjust_spend(table, -usd)
    except Exception as exc:  # noqa: BLE001 — releasing a hold must not hide the picture result
        _log_event("warning", tag="linkedin_image_usage_failed", error=str(exc)[:200])


def _image_timeout() -> int:
    import os

    try:
        return max(1, int(os.environ.get("LINKEDIN_IMAGE_TIMEOUT_SECONDS") or "90"))
    except (TypeError, ValueError):
        return 90


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
        resolution=IMAGE_RESOLUTION,
        n=n,
        output_format="png",
        seed=seed,
        input_references=references,
        service=SERVICE,
        owner="image",
    )
