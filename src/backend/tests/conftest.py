"""Test bootstrap: offline settings before any ``app`` import, shared fakes."""

from __future__ import annotations

import io
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="hidden-catch-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["AWS_S3_BUCKET_NAME"] = "test-bucket"
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
os.environ["GOOGLE_API_KEY"] = "offline-test-key"
os.environ["PUZZLE_CACHE_ENABLED"] = "true"
os.environ["PUZZLE_MAX_EDGE"] = "1024"

from botocore.exceptions import ClientError  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
import pytest  # noqa: E402


class FakeS3:
    """Minimal in-memory stand-in for the boto3 S3 client."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.gets: list[str] = []

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        self.gets.append(Key)
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject"
            )
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **_: object):  # noqa: N803
        self.objects[Key] = bytes(Body)
        self.puts.append(Key)
        return {}

    def head_object(self, Bucket: str, Key: str):  # noqa: N803
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "missing"}}, "HeadObject"
            )
        return {"ContentType": "image/jpeg"}

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn):  # noqa: N803
        return f"https://s3.test/{Params['Key']}?method={ClientMethod}&ttl={ExpiresIn}"


# Objects drawn on the synthetic photo: (x, y, w, h, color) in a 1600x1200 frame.
SCENE_OBJECTS = [
    (200, 200, 260, 200, (220, 40, 40)),
    (900, 250, 240, 240, (40, 160, 60)),
    (500, 800, 300, 220, (40, 80, 220)),
]


def make_scene(size: tuple[int, int] = (1600, 1200)) -> Image.Image:
    image = Image.new("RGB", size, (235, 235, 225))
    draw = ImageDraw.Draw(image)
    for x, y, w, h, color in SCENE_OBJECTS:
        draw.rectangle([x, y, x + w, y + h], fill=color)
    return image


@pytest.fixture
def fake_s3() -> FakeS3:
    return FakeS3()


@pytest.fixture
def scene_bytes() -> bytes:
    buffer = io.BytesIO()
    make_scene().save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


@pytest.fixture
def db_session():
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.models import game, puzzle, upload_slot  # noqa: F401 - register tables

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
