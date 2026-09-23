"""Image helpers for the puzzle pipeline (Pillow only, no network).

The pipeline works on one *normalized* image: EXIF orientation applied, RGB,
long edge <= ``max_edge`` and (optionally) center-cropped to an aspect ratio
the image model supports. Because the generated image is later resized to the
normalized size and composited with our own mask, every pixel outside the
edited regions is guaranteed to be identical to the original.
"""

from __future__ import annotations

import io
import math

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageFilter,
    ImageFont,
    ImageOps,
    ImageStat,
)

# Aspect ratios accepted by the Gemini image models (image_config.aspect_ratio).
SUPPORTED_ASPECT_RATIOS: dict[str, float] = {
    "1:1": 1.0,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "9:16": 9 / 16,
    "16:9": 16 / 9,
    "21:9": 21 / 9,
}

Rect = dict[str, int]


def nearest_aspect_ratio(width: int, height: int) -> tuple[str, float]:
    """Return the supported aspect ratio label/value closest to width:height."""
    ratio = width / height
    label = min(
        SUPPORTED_ASPECT_RATIOS,
        key=lambda key: abs(math.log(SUPPORTED_ASPECT_RATIOS[key] / ratio)),
    )
    return label, SUPPORTED_ASPECT_RATIOS[label]


def center_crop_to_ratio(image: Image.Image, target_ratio: float) -> Image.Image:
    """Center-crop ``image`` so that width/height == ``target_ratio``."""
    width, height = image.size
    current = width / height
    if abs(current - target_ratio) < 1e-3:
        return image
    if current > target_ratio:
        new_width = max(1, int(round(height * target_ratio)))
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = max(1, int(round(width / target_ratio)))
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def normalize_image(
    image_bytes: bytes, max_edge: int, fit_aspect_ratio: bool = True
) -> Image.Image:
    """Decode, fix orientation, convert to RGB, downscale and (optionally) crop."""
    with Image.open(io.BytesIO(image_bytes)) as opened:
        transposed = ImageOps.exif_transpose(opened)
        image = (transposed if transposed is not None else opened).convert("RGB")

    width, height = image.size
    longest = max(width, height)
    if longest > max_edge:
        scale = max_edge / longest
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    if fit_aspect_ratio:
        _label, ratio = nearest_aspect_ratio(*image.size)
        image = center_crop_to_ratio(image, ratio)
    return image


def encode_jpeg(image: Image.Image, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def decode_image(image_bytes: bytes) -> Image.Image:
    with Image.open(io.BytesIO(image_bytes)) as opened:
        return opened.convert("RGB")


def feather_radius_for(width: int, height: int) -> int:
    """Blur radius (px) used to soften mask edges: ~1% of the short edge."""
    return max(2, round(min(width, height) * 0.01))


def pad_rect(
    rect: dict,
    image_width: int,
    image_height: int,
    *,
    pad_ratio: float = 0.06,
    min_pad: int = 4,
) -> Rect:
    """Grow a rect a little (so the whole object is inside the edit region)
    and clamp it to the image."""
    pad = max(min_pad, int(round(min(rect["width"], rect["height"]) * pad_ratio)))
    x1 = max(0, int(round(rect["x"])) - pad)
    y1 = max(0, int(round(rect["y"])) - pad)
    x2 = min(image_width, int(round(rect["x"] + rect["width"])) + pad)
    y2 = min(image_height, int(round(rect["y"] + rect["height"])) + pad)
    return {"x": x1, "y": y1, "width": max(0, x2 - x1), "height": max(0, y2 - y1)}


def build_mask(
    size: tuple[int, int], rects: list[Rect], feather_radius: int = 0
) -> Image.Image:
    """White rectangles on black ("L" mode), optionally feathered for blending."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for rect in rects:
        if rect["width"] <= 0 or rect["height"] <= 0:
            continue
        draw.rectangle(
            [
                rect["x"],
                rect["y"],
                rect["x"] + rect["width"] - 1,
                rect["y"] + rect["height"] - 1,
            ],
            fill=255,
        )
    if feather_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather_radius))
    return mask


def composite_edit(
    original: Image.Image, edited: Image.Image, mask: Image.Image
) -> Image.Image:
    """Take the edited pixels inside ``mask`` and the original pixels elsewhere.

    The generated image is resized to the original size first, so a model
    that returns a different resolution (e.g. 1024px "1K") still lines up.
    """
    if edited.mode != "RGB":
        edited = edited.convert("RGB")
    if edited.size != original.size:
        edited = edited.resize(original.size, Image.Resampling.LANCZOS)
    if mask.size != original.size:
        mask = mask.resize(original.size, Image.Resampling.BILINEAR)
    return Image.composite(edited, original, mask)


def measure_change(original: Image.Image, modified: Image.Image, rect: Rect) -> float:
    """Mean absolute RGB difference (0-255) inside ``rect``."""
    if rect["width"] <= 0 or rect["height"] <= 0:
        return 0.0
    box = (rect["x"], rect["y"], rect["x"] + rect["width"], rect["y"] + rect["height"])
    diff = ImageChops.difference(original.crop(box), modified.crop(box))
    means = ImageStat.Stat(diff).mean
    return float(sum(means) / len(means)) if means else 0.0


def position_hint(rect: Rect, image_width: int, image_height: int) -> str:
    """Describe where a rect sits, e.g. 'top left', 'center', 'bottom right'."""
    cx = (rect["x"] + rect["width"] / 2) / max(1, image_width)
    cy = (rect["y"] + rect["height"] / 2) / max(1, image_height)
    column = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    row = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    if row == "middle" and column == "center":
        return "center"
    if row == "middle":
        return f"middle {column}"
    if column == "center":
        return f"{row} center"
    return f"{row} {column}"


def draw_region_hints(
    original: Image.Image, rects: list[Rect], *, offset: int = 0
) -> Image.Image:
    """Copy of the image with numbered red boxes drawn ``offset`` px outside
    each rect. Sent to the model as a visual pointer; the boxes are drawn
    outside the mask so they can never leak into the composited result."""
    hinted = original.copy()
    draw = ImageDraw.Draw(hinted)
    width, height = hinted.size
    stroke = max(2, min(width, height) // 250)
    font = ImageFont.load_default(size=max(14, min(width, height) // 36))
    for number, rect in enumerate(rects, start=1):
        x1 = max(0, rect["x"] - offset)
        y1 = max(0, rect["y"] - offset)
        x2 = min(width - 1, rect["x"] + rect["width"] - 1 + offset)
        y2 = min(height - 1, rect["y"] + rect["height"] - 1 + offset)
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=stroke)
        label = str(number)
        text_box = draw.textbbox((0, 0), label, font=font)
        text_w = text_box[2] - text_box[0]
        text_h = text_box[3] - text_box[1]
        tx = min(max(0, x1), width - text_w - 6)
        ty = y1 - text_h - 8 if y1 - text_h - 8 >= 0 else y1 + 2
        draw.rectangle([tx, ty, tx + text_w + 6, ty + text_h + 6], fill=(255, 0, 0))
        draw.text((tx + 3, ty + 1), label, fill=(255, 255, 255), font=font)
    return hinted


def to_normalized_rect(rect: Rect, image_width: int, image_height: int) -> list[int]:
    """[ymin, xmin, ymax, xmax] on a 0-1000 scale (legacy detected_objects format)."""
    return [
        int(rect["y"] / image_height * 1000),
        int(rect["x"] / image_width * 1000),
        int((rect["y"] + rect["height"]) / image_height * 1000),
        int((rect["x"] + rect["width"]) / image_width * 1000),
    ]
