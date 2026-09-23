"""Puzzle generation pipeline (one Celery task per uploaded image).

v1 ran two chained tasks and shipped the full-resolution PNG through Redis
between them (base64, once into the result backend and once into the next
task's message). v2 does everything for a slot in one process:

    download -> normalize (EXIF, RGB, <=1024px, aspect fit)
             -> cache lookup (sha256 of pixels)
             -> detect objects (Vision, on the small JPEG)
             -> select regions -> build mask + hint image
             -> edit (Gemini image model, with fallbacks)
             -> composite with our mask -> verify each region changed
             -> upload original/modified JPEGs (+ cache manifest)
             -> persist puzzle, differences, stage/game status

Only the slot id travels through the broker.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.db.utils import get_session
from app.models.game import Game, GameStage
from app.models.puzzle import Difference, Puzzle
from app.models.upload_slot import GameUploadSlot
from app.worker import detect, imaging
from app.worker.celery_app import celery_app
from app.worker.geometry import select_difference_rects

logger = logging.getLogger(__name__)

CACHE_VERSION = "v1"
ACTIVE_STAGE_STATUSES = ("waiting_upload", "waiting_puzzle", "playing")

_s3_client: Any = None


def get_s3_client() -> Any:
    """boto3 client shared by all tasks in this worker process (thread-safe)."""
    global _s3_client
    if _s3_client is None:
        kwargs: dict[str, str] = {}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        _s3_client = boto3.client("s3", region_name=settings.aws_region, **kwargs)
    return _s3_client


class PuzzleGenerationError(RuntimeError):
    """The image cannot be turned into a playable puzzle."""


@dataclass
class PuzzleResult:
    original_key: str
    modified_key: str
    width: int
    height: int
    differences: list[dict[str, Any]]
    detected: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    cache_hit: bool = False


@contextlib.contextmanager
def _timed(timings: dict[str, float] | None, name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        if timings is not None:
            timings[name] = round(time.perf_counter() - start, 3)


def content_hash(image) -> str:
    """Stable id of the normalized pixels (same picture -> same puzzle)."""
    digest = hashlib.sha256()
    digest.update(f"{image.size[0]}x{image.size[1]}:{image.mode}:".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def _cache_prefix(digest: str) -> str:
    prefix = settings.puzzle_cache_prefix.strip("/")
    return f"{prefix}/{CACHE_VERSION}/{digest}"


def _load_cached_puzzle(s3: Any, digest: str) -> PuzzleResult | None:
    key = f"{_cache_prefix(digest)}/manifest.json"
    try:
        body = s3.get_object(Bucket=settings.aws_s3_bucket_name, Key=key)["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        logger.warning("puzzle cache lookup failed key=%s: %s", key, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - cache must never break generation
        logger.warning("puzzle cache lookup failed key=%s: %s", key, exc)
        return None
    try:
        manifest = json.loads(body)
        if manifest.get("version") != CACHE_VERSION or not manifest.get("differences"):
            return None
        return PuzzleResult(
            original_key=manifest["original_key"],
            modified_key=manifest["modified_key"],
            width=int(manifest["width"]),
            height=int(manifest["height"]),
            differences=list(manifest["differences"]),
            detected=list(manifest.get("detected") or []),
            model=manifest.get("model"),
            cache_hit=True,
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("ignoring corrupt puzzle cache manifest key=%s: %s", key, exc)
        return None


def _put_objects(s3: Any, objects: list[tuple[str, bytes, str]]) -> None:
    """Upload several small objects concurrently."""

    def _put(item: tuple[str, bytes, str]) -> None:
        key, body, content_type = item
        s3.put_object(
            Bucket=settings.aws_s3_bucket_name,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    if len(objects) == 1:
        _put(objects[0])
        return
    with ThreadPoolExecutor(max_workers=min(4, len(objects))) as pool:
        list(pool.map(_put, objects))


def _edit_until_visible(
    normalized: Any,
    padded: list[dict[str, Any]],
    *,
    original_png: bytes,
    hint_png: bytes | None,
    aspect_label: str | None,
    feather: int,
    timings: dict[str, float] | None,
) -> tuple[Any, list[dict[str, Any]], str | None]:
    """Call the image model until at least one region visibly changed.

    Returns ``(edited_image, kept_regions, model_name)``; ``kept_regions`` is
    empty when every attempt came back unchanged.
    """
    width, height = normalized.size
    preview_mask = imaging.build_mask((width, height), padded, feather)
    attempts = max(1, settings.image_edit_max_attempts)
    edited = None
    model_used: str | None = None
    kept: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        prompt = detect.build_edit_prompt(
            padded,
            width,
            height,
            bold=attempt > 1,
            with_hint_image=hint_png is not None,
        )
        with _timed(timings, f"edit_{attempt}"):
            edited_bytes, model_used = detect.edit_image(
                original_png,
                prompt,
                hint_png=hint_png,
                aspect_ratio=aspect_label,
                image_size=settings.image_edit_image_size,
            )
        edited = imaging.decode_image(edited_bytes)
        preview = imaging.composite_edit(normalized, edited, preview_mask)
        kept = []
        for region in padded:
            change = imaging.measure_change(normalized, preview, region)
            if change >= settings.puzzle_min_change_score:
                kept.append({**region, "change": round(change, 2)})
        if kept:
            break
        logger.warning(
            "edit attempt %d/%d produced no visible change (model=%s)",
            attempt,
            attempts,
            model_used,
        )
    return edited, kept, model_used


def _output_keys(digest: str, key_base: str) -> tuple[str, str, str | None]:
    """S3 keys for (original, modified, manifest-or-None)."""
    if settings.puzzle_cache_enabled:
        prefix = _cache_prefix(digest)
        return (
            f"{prefix}/original.jpg",
            f"{prefix}/modified.jpg",
            f"{prefix}/manifest.json",
        )
    return f"{key_base}-original.jpg", f"{key_base}-modified.jpg", None


def _build_result(
    kept: list[dict[str, Any]],
    width: int,
    height: int,
    model_used: str | None,
    original_key: str,
    modified_key: str,
) -> PuzzleResult:
    differences = [
        {
            "index": index,
            "x": r["x"],
            "y": r["y"],
            "width": r["width"],
            "height": r["height"],
            "label": r["label"],
        }
        for index, r in enumerate(kept, start=1)
    ]
    detected = [
        {
            "label": r["label"],
            "rect": imaging.to_normalized_rect(r, width, height),
            "score": round(r["score"], 3),
            "change": r["change"],
        }
        for r in kept
    ]
    return PuzzleResult(
        original_key=original_key,
        modified_key=modified_key,
        width=width,
        height=height,
        differences=differences,
        detected=detected,
        model=model_used,
    )


def generate_puzzle_images(
    image_bytes: bytes,
    *,
    s3: Any,
    key_base: str,
    timings: dict[str, float] | None = None,
) -> PuzzleResult:
    """Pure pipeline: bytes in, S3 keys + answer rects out. No database access."""
    with _timed(timings, "normalize"):
        normalized = imaging.normalize_image(
            image_bytes, settings.puzzle_max_edge, settings.puzzle_fit_aspect_ratio
        )
    width, height = normalized.size
    digest = content_hash(normalized)

    if settings.puzzle_cache_enabled:
        with _timed(timings, "cache_lookup"):
            cached = _load_cached_puzzle(s3, digest)
        if cached is not None:
            return cached

    with _timed(timings, "detect"):
        boxes = detect.detect_objects(
            imaging.encode_jpeg(normalized, 85), width, height
        )
    regions = select_difference_rects(
        boxes,
        width,
        height,
        max_count=settings.puzzle_max_differences,
        min_area_ratio=settings.puzzle_min_area_ratio,
    )
    if not regions:
        raise PuzzleGenerationError(
            f"No suitable objects were detected ({len(boxes)} raw detections)."
        )

    feather = imaging.feather_radius_for(width, height)
    padded = [
        {
            **imaging.pad_rect(r, width, height, min_pad=feather + 2),
            "label": r["label"],
            "score": r["score"],
        }
        for r in regions
    ]
    hint_png = None
    if settings.image_edit_send_region_hint:
        hint = imaging.draw_region_hints(normalized, padded, offset=2 * feather + 2)
        hint_png = imaging.encode_png(hint)
    aspect_label = None
    if settings.puzzle_fit_aspect_ratio:
        aspect_label = imaging.nearest_aspect_ratio(width, height)[0]

    edited, kept, model_used = _edit_until_visible(
        normalized,
        padded,
        original_png=imaging.encode_png(normalized),
        hint_png=hint_png,
        aspect_label=aspect_label,
        feather=feather,
        timings=timings,
    )
    if not kept or edited is None:
        raise PuzzleGenerationError("The edited image shows no visible differences.")

    # Composite again with only the verified regions so nothing else differs.
    with _timed(timings, "composite"):
        final_mask = imaging.build_mask((width, height), kept, feather)
        modified = imaging.composite_edit(normalized, edited, final_mask)
        original_jpg = imaging.encode_jpeg(normalized, settings.puzzle_jpeg_quality)
        modified_jpg = imaging.encode_jpeg(modified, settings.puzzle_jpeg_quality)

    original_key, modified_key, manifest_key = _output_keys(digest, key_base)
    result = _build_result(kept, width, height, model_used, original_key, modified_key)
    uploads: list[tuple[str, bytes, str]] = [
        (original_key, original_jpg, "image/jpeg"),
        (modified_key, modified_jpg, "image/jpeg"),
    ]
    if manifest_key is not None:
        manifest = {
            "version": CACHE_VERSION,
            "created_at": datetime.now().isoformat(),
            **{k: v for k, v in asdict(result).items() if k != "cache_hit"},
        }
        uploads.append(
            (manifest_key, json.dumps(manifest).encode(), "application/json")
        )
    with _timed(timings, "upload"):
        _put_objects(s3, uploads)
    return result


# --------------------------------------------------------------------------
# Database side
# --------------------------------------------------------------------------
def _ensure_stage(session, game: Game, slot: GameUploadSlot) -> GameStage:
    stage = session.get(GameStage, slot.stage_id) if slot.stage_id else None
    if stage is None:
        stage = next(
            (s for s in game.stages if s.stage_number == slot.slot_number), None
        )
    if stage is None:
        stage = GameStage(
            game_id=game.id,
            stage_number=slot.slot_number,
            status="waiting_puzzle",
            started_at=datetime.now(),
        )
        session.add(stage)
        session.flush()
    slot.stage_id = stage.id
    return stage


def refresh_game_status(game: Game) -> None:
    """Derive the game-level status from its stages.

    - every stage failed            -> "failed"
    - the first unfinished stage is
      playable                      -> "playing"
    - otherwise leave the status the API set (waiting_*, finished).
    """
    stages = sorted(game.stages, key=lambda s: s.stage_number)
    if not stages or game.status == "finished":
        return
    if all(stage.status == "failed" for stage in stages):
        game.status = "failed"
        return
    active = [s for s in stages if s.status in ACTIVE_STAGE_STATUSES]
    if active and active[0].status == "playing":
        game.status = "playing"


def _persist_result(
    session, slot_id: int, stage_id: int, game_id: int, result: PuzzleResult
) -> None:
    slot = session.get(GameUploadSlot, slot_id)
    stage = session.get(GameStage, stage_id)
    game = session.get(Game, game_id)
    if slot is None or stage is None or game is None:
        logger.warning(
            "persist skipped: slot/stage/game vanished (%s/%s/%s)",
            slot_id,
            stage_id,
            game_id,
        )
        return

    puzzle = stage.puzzle
    if puzzle is None:
        puzzle = Puzzle(
            difficulty=game.difficulty or "normal",
            original_image_url=result.original_key,
            modified_image_url=result.modified_key,
            width=result.width,
            height=result.height,
        )
        session.add(puzzle)
        session.flush()
        stage.puzzle_id = puzzle.id
        stage.puzzle = puzzle
    puzzle.original_image_url = result.original_key
    puzzle.modified_image_url = result.modified_key
    puzzle.width = result.width
    puzzle.height = result.height
    puzzle.is_completed = True
    puzzle.differences = [
        Difference(
            index=int(d["index"]),
            x=float(d["x"]),
            y=float(d["y"]),
            width=float(d["width"]),
            height=float(d["height"]),
            label=(d.get("label") or None),
        )
        for d in result.differences
    ]

    now = datetime.now()
    stage.total_difference_count = len(result.differences)
    stage.status = "playing"
    stage.started_at = stage.started_at or now

    slot.detected_objects = result.detected
    slot.analysis_status = "completed"
    slot.analysis_error = None
    slot.last_analyzed_at = now

    refresh_game_status(game)


def _mark_failed(
    session, slot_id: int, stage_id: int | None, game_id: int, message: str
) -> None:
    now = datetime.now()
    slot = session.get(GameUploadSlot, slot_id)
    if slot is not None:
        slot.analysis_status = "failed"
        slot.analysis_error = message[:500]
        slot.last_analyzed_at = now
    stage = session.get(GameStage, stage_id) if stage_id else None
    if stage is not None:
        stage.status = "failed"
        stage.completed_at = now
    game = session.get(Game, game_id)
    if game is not None:
        refresh_game_status(game)


# --------------------------------------------------------------------------
# Celery tasks
# --------------------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.generate_puzzle_for_slot", ignore_result=True)
def generate_puzzle_for_slot(slot_id: int) -> None:
    started = time.perf_counter()
    timings: dict[str, float] = {}

    with get_session() as session:
        slot = session.get(GameUploadSlot, slot_id)
        if slot is None or not slot.s3_object_key:
            logger.warning("slot %s missing or has no object key; skipping", slot_id)
            return
        game = session.get(Game, slot.game_id)
        if game is None:
            slot.analysis_status = "failed"
            slot.analysis_error = "Game not found."
            slot.last_analyzed_at = datetime.now()
            return
        stage = _ensure_stage(session, game, slot)
        if stage.status == "waiting_upload":
            stage.status = "waiting_puzzle"
        slot.analysis_status = "processing"
        slot.analysis_error = None
        object_key = slot.s3_object_key
        game_id, stage_id = game.id, stage.id

    try:
        s3 = get_s3_client()
        with _timed(timings, "download"):
            body = s3.get_object(Bucket=settings.aws_s3_bucket_name, Key=object_key)
            image_bytes = body["Body"].read()
        result = generate_puzzle_images(
            image_bytes,
            s3=s3,
            key_base=object_key.rsplit(".", 1)[0],
            timings=timings,
        )
    except Exception as exc:  # noqa: BLE001 - surface every failure to the user
        logger.exception("puzzle generation failed slot=%s game=%s", slot_id, game_id)
        with get_session() as session:
            _mark_failed(
                session, slot_id, stage_id, game_id, f"{type(exc).__name__}: {exc}"
            )
        return

    with get_session() as session:
        _persist_result(session, slot_id, stage_id, game_id, result)

    timings["total"] = round(time.perf_counter() - started, 3)
    logger.info(
        "puzzle ready slot=%s game=%s stage=%s cache_hit=%s model=%s "
        "differences=%d size=%dx%d timings=%s",
        slot_id,
        game_id,
        stage_id,
        result.cache_hit,
        result.model,
        len(result.differences),
        result.width,
        result.height,
        timings,
    )


@celery_app.task(name="app.worker.tasks.run_imagen_pipeline", ignore_result=True)
def run_imagen_pipeline(slot_id: int) -> None:
    """Backward-compatible alias for messages queued by pre-v2 API servers."""
    generate_puzzle_for_slot(slot_id)
