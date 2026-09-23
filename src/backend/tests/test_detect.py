from types import SimpleNamespace

import pytest

from app.worker import detect


def _image_response(data: bytes):
    part = SimpleNamespace(
        inline_data=SimpleNamespace(data=data, mime_type="image/png")
    )
    text_part = SimpleNamespace(inline_data=None, text="done")
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[text_part, part]))]
    )


class FakeModels:
    def __init__(self, behaviours):
        self.behaviours = behaviours
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, config.image_config is not None))
        behaviour = self.behaviours[model]
        if callable(behaviour):
            return behaviour(config)
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour


def test_build_edit_prompt_lists_every_region():
    regions = [
        {"x": 0, "y": 0, "width": 50, "height": 50, "label": "Dog"},
        {"x": 500, "y": 400, "width": 50, "height": 50, "label": "Car"},
    ]
    prompt = detect.build_edit_prompt(regions, 600, 450, with_hint_image=True)
    assert "exactly 2" in prompt
    assert "1. the Dog at the top left" in prompt
    assert "2. the Car at the bottom right" in prompt
    assert "second image" in prompt
    bold = detect.build_edit_prompt(regions, 600, 450, bold=True, with_hint_image=False)
    assert "BOLD" in bold and "second image" not in bold


def test_extract_image_bytes_handles_bytes_and_base64():
    assert detect.extract_image_bytes(_image_response(b"\x89PNG")) == b"\x89PNG"
    assert detect.extract_image_bytes(_image_response("iVBORw0K")) == b"\x89PNG\r\n"
    assert detect.extract_image_bytes(SimpleNamespace(candidates=[])) is None


def test_edit_image_falls_back_to_next_model():
    models = FakeModels(
        {
            "model-a": RuntimeError("404 model not found"),
            "model-b": _image_response(b"IMG"),
        }
    )
    client = SimpleNamespace(models=models)
    data, used = detect.edit_image(
        b"png",
        "prompt",
        aspect_ratio="4:3",
        image_size="1K",
        models=["model-a", "model-b"],
        client=client,
    )
    assert (data, used) == (b"IMG", "model-b")
    # model-a: with image_config, then without; model-b: with image_config
    assert models.calls == [("model-a", True), ("model-a", False), ("model-b", True)]


def test_edit_image_retries_without_image_config():
    def only_default_config(config):
        if config.image_config is not None:
            raise RuntimeError("400 image_config not supported")
        return _image_response(b"IMG")

    models = FakeModels({"model-a": only_default_config})
    data, used = detect.edit_image(
        b"png",
        "prompt",
        aspect_ratio="1:1",
        models=["model-a"],
        client=SimpleNamespace(models=models),
    )
    assert (data, used) == (b"IMG", "model-a")
    assert models.calls == [("model-a", True), ("model-a", False)]


def test_edit_image_raises_when_everything_fails():
    models = FakeModels(
        {
            "model-a": RuntimeError("boom"),
            "model-b": SimpleNamespace(candidates=[]),  # answered without an image
        }
    )
    with pytest.raises(detect.ImageEditError) as excinfo:
        detect.edit_image(
            b"png",
            "prompt",
            models=["model-a", "model-b"],
            client=SimpleNamespace(models=models),
        )
    assert "model-a: boom" in str(excinfo.value)
    assert "model-b: response contained no image" in str(excinfo.value)
    assert models.calls == [("model-a", False), ("model-b", False)]


def test_detect_objects_converts_normalized_vertices():
    vertex = lambda x, y: SimpleNamespace(x=x, y=y)  # noqa: E731
    annotation = SimpleNamespace(
        name="Cat",
        score=0.87,
        bounding_poly=SimpleNamespace(
            normalized_vertices=[
                vertex(0.1, 0.2),
                vertex(0.5, 0.2),
                vertex(0.5, 0.6),
                vertex(0.1, 0.6),
            ]
        ),
    )
    client = SimpleNamespace(
        object_localization=lambda image: SimpleNamespace(
            localized_object_annotations=[annotation]
        )
    )
    boxes = detect.detect_objects(b"jpeg", 1000, 500, client=client)
    assert boxes == [
        {
            "label": "Cat",
            "score": 0.87,
            "x": 100.0,
            "y": 100.0,
            "width": 400.0,
            "height": 200.0,
        }
    ]
