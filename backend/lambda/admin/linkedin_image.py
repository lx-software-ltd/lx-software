"""Black-and-white comic panels for LinkedIn drafts.

One OpenRouter Image API call per post, then Pillow: grayscale, a square (or
the saved format) canvas, and the caption in italic serif under the panel.
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
# Panel plus a 200px caption strip. Square is the feed default.
FORMATS: dict[str, dict[str, Any]] = {
    "square": {"aspect": "4:3", "panel": (1200, 1000), "canvas": (1200, 1200)},
    "portrait": {"aspect": "1:1", "panel": (1080, 1150), "canvas": (1080, 1350)},
    "wide": {"aspect": "16:9", "panel": (1200, 675), "canvas": (1200, 875)},
}
_STRIP = 200
HEAD_SIZE = (768, 768)
# Held against maxUsdPerMonth before the Image API call, then replaced by the
# real cost. Above the usual Seedream charge so parallel workers cannot all
# pass a check that has not moved yet.
IMAGE_HOLD_USD = 0.05
# Stop starting another 90s call once this much of the 300s Lambda is gone.
DRAW_BUDGET_SECONDS = 240
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
    held = _held_picture(current)
    doc["image"] = {
        "status": "pending",
        "scene": scene_text[: linkedin_store.IMAGE_SCENE_MAX],
        "caption": caption_text[: linkedin_store.IMAGE_CAPTION_MAX],
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
            "contentType": str(previous.get("contentType") or ""),
            "bytes": int(previous.get("bytes") or 0),
            "model": str(previous.get("model") or ""),
        }
    return None


def render_post(table: Any, post_id: str, *, generate: Generate | None = None) -> dict[str, Any]:
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
    scene = str(image.get("scene") or "") or fallback_scene(str(doc.get("body") or ""))
    caption = str(image.get("caption") or "") or linkedin_store.FALLBACK_IMAGE_CAPTION
    prompt = build_prompt(settings, scene)
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
            except OpenRouterError:
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


def compose(data: bytes, caption: str, fmt: str) -> bytes:
    """Grayscale panel, white caption strip, italic serif, single quotes."""
    spec = FORMATS.get(fmt) or FORMATS["square"]
    panel = _to_ink(data, tuple(spec["panel"]))
    canvas_size = tuple(spec["canvas"])
    from PIL import Image, ImageDraw

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
        resolution="1K",
        n=n,
        output_format="png",
        seed=seed,
        input_references=references,
        service=SERVICE,
        owner="image",
    )
