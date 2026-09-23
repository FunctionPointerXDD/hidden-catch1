import io

from PIL import Image, ImageDraw

from app.worker import imaging


def _jpeg_with_orientation(image: Image.Image, orientation: int) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes(), quality=95)
    return buffer.getvalue()


def test_nearest_aspect_ratio_picks_closest_supported():
    assert imaging.nearest_aspect_ratio(1600, 1200)[0] == "4:3"
    assert imaging.nearest_aspect_ratio(1200, 1600)[0] == "3:4"
    assert imaging.nearest_aspect_ratio(1920, 1080)[0] == "16:9"
    assert imaging.nearest_aspect_ratio(1000, 1000)[0] == "1:1"
    assert imaging.nearest_aspect_ratio(1500, 1000)[0] == "3:2"


def test_normalize_downscales_fixes_orientation_and_crops():
    # Landscape photo stored rotated with EXIF orientation 6 (needs 90 degree turn).
    source = Image.new("RGB", (3000, 2000), (10, 200, 10))
    ImageDraw.Draw(source).rectangle([0, 0, 1500, 2000], fill=(200, 10, 10))
    stored = source.transpose(Image.Transpose.ROTATE_90)  # what the sensor wrote
    data = _jpeg_with_orientation(stored, 6)

    normalized = imaging.normalize_image(data, max_edge=1024, fit_aspect_ratio=True)
    assert max(normalized.size) == 1024
    assert normalized.size[0] > normalized.size[1]  # landscape again
    ratio = normalized.size[0] / normalized.size[1]
    assert abs(ratio - 3 / 2) < 0.01  # 3000x2000 -> "3:2"
    # Left half red, right half green after orientation fix.
    assert normalized.getpixel((10, 10))[0] > 150
    assert normalized.getpixel((normalized.size[0] - 10, 10))[1] > 150


def test_normalize_does_not_upscale_small_images():
    small = Image.new("RGB", (400, 300), (1, 2, 3))
    buffer = io.BytesIO()
    small.save(buffer, format="PNG")
    normalized = imaging.normalize_image(
        buffer.getvalue(), 1024, fit_aspect_ratio=False
    )
    assert normalized.size == (400, 300)


def test_center_crop_to_ratio():
    wide = Image.new("RGB", (1000, 500))
    cropped = imaging.center_crop_to_ratio(wide, 1.0)
    assert cropped.size == (500, 500)
    tall = Image.new("RGB", (500, 1000))
    cropped = imaging.center_crop_to_ratio(tall, 1.0)
    assert cropped.size == (500, 500)


def test_pad_rect_grows_and_clamps():
    rect = {"x": 5, "y": 5, "width": 100, "height": 50}
    padded = imaging.pad_rect(rect, 200, 40, pad_ratio=0.1, min_pad=4)
    assert padded == {"x": 0, "y": 0, "width": 110, "height": 40}


def test_mask_composite_and_change_measurement():
    size = (400, 300)
    original = Image.new("RGB", size, (100, 100, 100))
    edited = Image.new("RGB", (200, 150), (250, 20, 20))  # different resolution
    rect = {"x": 100, "y": 100, "width": 80, "height": 60}

    hard_mask = imaging.build_mask(size, [rect], feather_radius=0)
    assert hard_mask.getpixel((120, 120)) == 255
    assert hard_mask.getpixel((10, 10)) == 0

    result = imaging.composite_edit(original, edited, hard_mask)
    assert result.size == size
    assert result.getpixel((120, 120)) == (250, 20, 20)
    assert result.getpixel((10, 10)) == (100, 100, 100)
    assert result.getpixel((300, 250)) == (100, 100, 100)

    assert imaging.measure_change(original, original, rect) == 0.0
    assert imaging.measure_change(original, result, rect) > 100
    outside = {"x": 0, "y": 0, "width": 50, "height": 50}
    assert imaging.measure_change(original, result, outside) == 0.0

    soft_mask = imaging.build_mask(size, [rect], feather_radius=6)
    assert 0 < soft_mask.getpixel((100, 130)) < 255  # feathered edge
    assert soft_mask.getpixel((140, 130)) == 255  # solid center
    assert soft_mask.getpixel((10, 10)) == 0


def test_position_hint_grid():
    assert (
        imaging.position_hint({"x": 0, "y": 0, "width": 10, "height": 10}, 300, 300)
        == "top left"
    )
    assert (
        imaging.position_hint({"x": 145, "y": 145, "width": 10, "height": 10}, 300, 300)
        == "center"
    )
    assert (
        imaging.position_hint({"x": 280, "y": 145, "width": 10, "height": 10}, 300, 300)
        == "middle right"
    )
    assert (
        imaging.position_hint({"x": 145, "y": 280, "width": 10, "height": 10}, 300, 300)
        == "bottom center"
    )


def test_draw_region_hints_and_normalized_rect():
    image = Image.new("RGB", (400, 300), (0, 0, 0))
    rect = {"x": 100, "y": 100, "width": 80, "height": 60}
    hinted = imaging.draw_region_hints(image, [rect], offset=10)
    assert hinted.size == image.size
    assert hinted.getpixel((90, 130))[0] > 200  # red box drawn 10px outside the rect
    assert hinted.getpixel((140, 130)) == (0, 0, 0)  # interior untouched
    assert imaging.to_normalized_rect(rect, 400, 300) == [333, 250, 533, 450]


def test_jpeg_and_png_roundtrip():
    image = Image.new("RGB", (64, 48), (12, 34, 56))
    assert imaging.decode_image(imaging.encode_jpeg(image, 90)).size == (64, 48)
    assert imaging.decode_image(imaging.encode_png(image)).getpixel((1, 1)) == (
        12,
        34,
        56,
    )
