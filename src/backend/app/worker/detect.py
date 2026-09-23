"""External AI calls: object detection (Cloud Vision) and image editing (Gemini).

Clients are created lazily once per worker process. The old pipeline built a
new Vision/boto3/genai client for every task, paying credential loading and
channel setup (hundreds of ms) each time.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
from typing import Any

from google import genai
from google.cloud import vision
from google.genai import types

from app.core.config import settings
from app.worker.imaging import position_hint

logger = logging.getLogger(__name__)

if settings.google_application_credentials:
    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS", settings.google_application_credentials
    )

_lock = threading.Lock()
_vision_client: Any = None
_genai_client: Any = None


def get_vision_client() -> Any:
    global _vision_client
    with _lock:
        if _vision_client is None:
            _vision_client = vision.ImageAnnotatorClient()
        return _vision_client


def get_genai_client() -> Any:
    global _genai_client
    with _lock:
        if _genai_client is None:
            if settings.google_api_key:
                _genai_client = genai.Client(api_key=settings.google_api_key)
            else:
                _genai_client = genai.Client(
                    vertexai=True,
                    project=settings.gcp_project_id or None,
                    location=settings.gcp_location,
                )
        return _genai_client


class ImageEditError(RuntimeError):
    """Raised when no configured image model returned an edited image."""


# --------------------------------------------------------------------------
# Object detection
# --------------------------------------------------------------------------
def detect_objects(
    image_bytes: bytes, image_width: int, image_height: int, client: Any = None
) -> list[dict[str, Any]]:
    """Run Cloud Vision object localization and return pixel boxes.

    ``image_bytes`` should be the *normalized* (<= ~1024px) image: Vision does
    not get more accurate above ~640x480 but every extra megabyte costs
    upload time.
    """
    client = client or get_vision_client()
    response = client.object_localization(image=vision.Image(content=image_bytes))
    boxes: list[dict[str, Any]] = []
    for annotation in response.localized_object_annotations:
        vertices = annotation.bounding_poly.normalized_vertices
        if not vertices:
            continue
        xs = [min(1.0, max(0.0, v.x)) for v in vertices]
        ys = [min(1.0, max(0.0, v.y)) for v in vertices]
        x0, x1 = min(xs) * image_width, max(xs) * image_width
        y0, y1 = min(ys) * image_height, max(ys) * image_height
        boxes.append(
            {
                "label": annotation.name,
                "score": float(annotation.score),
                "x": x0,
                "y": y0,
                "width": x1 - x0,
                "height": y1 - y0,
            }
        )
    return boxes


# --------------------------------------------------------------------------
# Image editing
# --------------------------------------------------------------------------
EDIT_IDEAS: tuple[str, ...] = (
    "change its color to a clearly different, natural-looking color",
    "remove it completely and fill the area with matching background",
    "replace it with a different object of about the same size",
    "change its texture, pattern or material so it looks clearly different",
)


def edit_idea_for(index: int, label: str) -> str:
    """Deterministic per-region instruction so one puzzle mixes edit types."""
    return EDIT_IDEAS[index % len(EDIT_IDEAS)]


def build_edit_prompt(
    regions: list[dict[str, Any]],
    image_width: int,
    image_height: int,
    *,
    bold: bool = False,
    with_hint_image: bool = True,
) -> str:
    lines = [
        'You are editing a photo for a "spot the difference" game.',
        f"Make exactly {len(regions)} clearly visible changes, one in each region "
        "listed below, and keep EVERYTHING else pixel-identical: same framing, "
        "same lighting, same colors, same background, same image size.",
    ]
    if with_hint_image:
        lines.append(
            "The second image is the same photo with numbered red boxes that only "
            "show where each region is. Never draw boxes or numbers in your output."
        )
    lines.append("Regions:")
    for number, region in enumerate(regions, start=1):
        label = region.get("label") or "object"
        where = position_hint(region, image_width, image_height)
        idea = edit_idea_for(number - 1, label)
        lines.append(f"{number}. the {label} at the {where}: {idea}.")
    strength = (
        "Each change must be BOLD and impossible to miss even in a small thumbnail."
        if bold
        else "Each change must be obvious at a glance yet photorealistic and "
        "blended naturally."
    )
    lines.append(
        f"Rules: {strength} Do not add text, borders or watermarks. Do not change "
        "anything outside the listed regions."
    )
    return "\n".join(lines)


def extract_image_bytes(response: Any) -> bytes | None:
    """Return the first inline image from a generate_content response."""
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            blob = getattr(part, "inline_data", None)
            data = getattr(blob, "data", None) if blob is not None else None
            if not data:
                continue
            if isinstance(data, str):
                data = base64.b64decode(data)
            return bytes(data)
    return None


def edit_image(
    original_png: bytes,
    prompt: str,
    *,
    hint_png: bytes | None = None,
    aspect_ratio: str | None = None,
    image_size: str | None = None,
    models: list[str] | None = None,
    client: Any = None,
) -> tuple[bytes, str]:
    """Ask a Gemini image model for the edited picture.

    Tries ``models`` in order (primary first, then fallbacks) so a retired or
    regionally unavailable model degrades gracefully instead of failing the
    puzzle. Returns ``(image_bytes, model_name)``.
    """
    client = client or get_genai_client()
    models = models or [settings.image_edit_model, *settings.image_edit_fallback_models]

    parts: list[Any] = [types.Part.from_bytes(data=original_png, mime_type="image/png")]
    if hint_png:
        parts.append(types.Part.from_bytes(data=hint_png, mime_type="image/png"))
    parts.append(types.Part.from_text(text=prompt))

    image_config = (
        types.ImageConfig(aspect_ratio=aspect_ratio, image_size=image_size)
        if (aspect_ratio or image_size)
        else None
    )
    errors: list[str] = []
    for model in models:
        configs = [image_config, None] if image_config is not None else [None]
        for config_variant in configs:
            config = types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=config_variant,
            )
            try:
                response = client.models.generate_content(
                    model=model, contents=parts, config=config
                )
            except Exception as exc:  # noqa: BLE001 - we want to fall through
                errors.append(f"{model}: {exc}")
                logger.warning(
                    "image edit failed model=%s config=%s: %s",
                    model,
                    "image_config" if config_variant else "default",
                    exc,
                )
                continue
            data = extract_image_bytes(response)
            if data:
                return data, model
            errors.append(f"{model}: response contained no image")
            logger.warning("image edit returned no image model=%s", model)
            break  # the model answered; a different config will not help
    raise ImageEditError("; ".join(errors) or "no image model configured")
