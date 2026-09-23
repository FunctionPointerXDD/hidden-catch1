"""End-to-end pipeline tests with fake S3 / Vision / Gemini (no network)."""

import io
import json

from PIL import Image, ImageDraw
import pytest

from app.core.config import settings
from app.worker import detect, imaging, tasks
from tests.conftest import SCENE_OBJECTS, make_scene


def _fake_detect(image_bytes, width, height, client=None):
    """Return the drawn rectangles as if Vision had found them (in the
    normalized coordinate space, computed from the 1600x1200 scene)."""
    scale = width / 1600
    boxes = []
    for index, (x, y, w, h, _color) in enumerate(SCENE_OBJECTS):
        boxes.append(
            {
                "label": f"object-{index + 1}",
                "score": 0.9 - index * 0.1,
                "x": x * scale,
                "y": y * scale,
                "width": w * scale,
                "height": h * scale,
            }
        )
    return boxes


class FakeEditor:
    """Pretends to be the image model: repaints the first ``edit_count`` regions
    and returns the picture at a *different* resolution (like a 1K model)."""

    def __init__(self, edit_count: int = 2, output_size=(1024, 768)):
        self.edit_count = edit_count
        self.output_size = output_size
        self.calls = 0

    def __call__(
        self,
        original_png,
        prompt,
        *,
        hint_png=None,
        aspect_ratio=None,
        image_size=None,
        models=None,
        client=None,
    ):
        self.calls += 1
        with Image.open(io.BytesIO(original_png)) as opened:
            edited = opened.convert("RGB")
        draw = ImageDraw.Draw(edited)
        scale = edited.size[0] / 1600
        for x, y, w, h, _color in SCENE_OBJECTS[: self.edit_count]:
            draw.rectangle(
                [x * scale, y * scale, (x + w) * scale, (y + h) * scale],
                fill=(255, 255, 0),
            )
        edited = edited.resize(self.output_size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        edited.save(buffer, format="PNG")
        return buffer.getvalue(), "fake-image-model"


@pytest.fixture
def pipeline_fakes(monkeypatch):
    editor = FakeEditor()
    monkeypatch.setattr(detect, "detect_objects", _fake_detect)
    monkeypatch.setattr(detect, "edit_image", editor)
    monkeypatch.setattr(settings, "puzzle_cache_enabled", True)
    monkeypatch.setattr(settings, "image_edit_max_attempts", 2)
    return editor


def test_generate_puzzle_images_end_to_end(pipeline_fakes, fake_s3, scene_bytes):
    timings = {}
    result = tasks.generate_puzzle_images(
        scene_bytes, s3=fake_s3, key_base="uploads/game-1/slot-1", timings=timings
    )

    assert result.cache_hit is False
    assert result.model == "fake-image-model"
    assert (result.width, result.height) == (1024, 768)
    # Only the two regions the "model" actually changed survive verification.
    assert [d["label"] for d in result.differences] == ["object-1", "object-2"]
    assert [d["index"] for d in result.differences] == [1, 2]
    assert all(d["width"] > 0 and d["height"] > 0 for d in result.differences)
    assert result.original_key.startswith(f"{settings.puzzle_cache_prefix}/v1/")
    assert result.original_key.endswith("/original.jpg")
    assert result.modified_key.endswith("/modified.jpg")
    assert {"normalize", "detect", "edit_1", "composite", "upload"} <= set(timings)

    # Three uploads: original, modified, manifest.
    assert len(fake_s3.puts) == 3
    manifest = json.loads(
        fake_s3.objects[result.original_key.replace("original.jpg", "manifest.json")]
    )
    assert manifest["version"] == tasks.CACHE_VERSION
    assert manifest["differences"] == result.differences

    original = imaging.decode_image(fake_s3.objects[result.original_key])
    modified = imaging.decode_image(fake_s3.objects[result.modified_key])
    assert original.size == modified.size == (1024, 768)
    # Edited regions differ strongly, the untouched third object and the
    # background are (JPEG-)identical.
    for difference in result.differences:
        assert imaging.measure_change(original, modified, difference) > 50
    x, y, w, h, _ = SCENE_OBJECTS[2]
    scale = 1024 / 1600
    untouched = {
        "x": int((x + 20) * scale),
        "y": int((y + 20) * scale),
        "width": int((w - 40) * scale),
        "height": int((h - 40) * scale),
    }
    assert imaging.measure_change(original, modified, untouched) < 1.0
    background = {"x": 20, "y": 600, "width": 150, "height": 120}
    assert imaging.measure_change(original, modified, background) < 1.0
    assert result.detected[0]["rect"][0] < result.detected[0]["rect"][2]


def test_second_upload_of_same_image_is_a_cache_hit(
    pipeline_fakes, fake_s3, scene_bytes
):
    first = tasks.generate_puzzle_images(scene_bytes, s3=fake_s3, key_base="k1")
    puts_after_first = len(fake_s3.puts)
    second = tasks.generate_puzzle_images(scene_bytes, s3=fake_s3, key_base="k2")

    assert second.cache_hit is True
    assert second.original_key == first.original_key
    assert second.differences == first.differences
    assert pipeline_fakes.calls == 1  # the model was not called again
    assert len(fake_s3.puts) == puts_after_first  # nothing re-uploaded


def test_cache_disabled_uses_slot_keys(
    pipeline_fakes, fake_s3, scene_bytes, monkeypatch
):
    monkeypatch.setattr(settings, "puzzle_cache_enabled", False)
    result = tasks.generate_puzzle_images(
        scene_bytes, s3=fake_s3, key_base="uploads/game-7/slot-2"
    )
    assert result.original_key == "uploads/game-7/slot-2-original.jpg"
    assert result.modified_key == "uploads/game-7/slot-2-modified.jpg"
    assert len(fake_s3.puts) == 2


def test_no_visible_change_raises_after_retry(pipeline_fakes, fake_s3, scene_bytes):
    pipeline_fakes.edit_count = 0  # the model ignores every instruction
    with pytest.raises(tasks.PuzzleGenerationError, match="no visible differences"):
        tasks.generate_puzzle_images(scene_bytes, s3=fake_s3, key_base="k")
    assert pipeline_fakes.calls == 2  # one bold retry, then give up
    assert fake_s3.puts == []  # nothing half-finished was uploaded


def test_no_detections_raises(pipeline_fakes, fake_s3, scene_bytes, monkeypatch):
    monkeypatch.setattr(detect, "detect_objects", lambda *a, **k: [])
    with pytest.raises(tasks.PuzzleGenerationError, match="No suitable objects"):
        tasks.generate_puzzle_images(scene_bytes, s3=fake_s3, key_base="k")
    assert pipeline_fakes.calls == 0


def test_content_hash_is_stable_for_same_pixels():
    a = make_scene((400, 300))
    b = make_scene((400, 300))
    assert tasks.content_hash(a) == tasks.content_hash(b)
    assert tasks.content_hash(a) != tasks.content_hash(make_scene((401, 300)))
