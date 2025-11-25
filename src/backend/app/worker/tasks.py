from datetime import datetime
import io
import os
import tempfile
import time

import boto3
from celery import chain
from google import genai
from google.cloud import vision
from google.genai import types
from PIL import Image, ImageDraw
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.utils import get_session
from app.models.game import Game, GameStage
from app.models.puzzle import Difference, Puzzle
from app.models.upload_slot import GameUploadSlot
from app.worker.celery_app import celery_app
from app.worker.detect import (
    find_game_objects_normalized,
    modify_image_with_imagen,
    modify_image_with_imagen2,
)


@celery_app.task
def long_running_task(param: int) -> str:
    time.sleep(10)
    return f"Proceed {param} successfully!"


@celery_app.task
def detect_objects_for_slot(slot_id: int):
    """
    1. GameUploadSlot에서 슬롯 가져오기
    2. s3에서 이미지 가져오기
    3. Vision API로 오브젝트 탐지
    4. 탐지한 오브젝트를 Difference로 저장 후 DB 저장
    5. GameUploadSlot 슬롯 업데이트
    """
    with get_session() as session:
        slot = session.get(GameUploadSlot, slot_id)
        if slot is None:
            return

        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )

        s3_response = s3_client.get_object(
            Bucket=settings.aws_s3_bucket_name, Key=slot.s3_object_key
        )

        image_bytes = s3_response["Body"].read()

        with Image.open(io.BytesIO(image_bytes)) as img:
            image_width, image_height = img.size

        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)

        objects = client.object_localization(image=image).localized_object_annotations  # type: ignore
        if not objects:
            slot.analysis_error = "No objects detected."
            slot.analysis_status = "failed"
            slot.last_analyzed_at = datetime.now()
            return

        game = session.get(Game, slot.game_id)
        if game is None:
            slot.analysis_status = "failed"
            slot.analysis_error = "Game not found."
            slot.last_analyzed_at = datetime.now()
            return

        existing_stage = (
            session.get(GameStage, slot.stage_id) if slot.stage_id else None
        )
        puzzle = (
            existing_stage.puzzle if existing_stage and existing_stage.puzzle else None
        )

        if puzzle is None:
            puzzle = Puzzle(
                difficulty=game.difficulty,
                original_image_url=slot.s3_object_key,
                modified_image_url=slot.s3_object_key,
                width=image_width,
                height=image_height,
            )
            session.add(puzzle)
            session.flush()

            if existing_stage is not None:
                existing_stage.puzzle_id = puzzle.id
            else:
                existing_stage = GameStage(
                    game_id=game.id,
                    puzzle_id=puzzle.id,
                    stage_number=slot.slot_number,
                    status="waiting_puzzle",
                    started_at=datetime.now(),
                )
                session.add(existing_stage)
                session.flush()
                slot.stage_id = existing_stage.id
                game.status = "waiting_puzzle"

        detected = []
        index = 0

        stmt = delete(Difference).where(Difference.puzzle_id == puzzle.id)
        session.execute(stmt)
        for object_ in objects:
            index += 1
            label = object_.name
            vertices = object_.bounding_poly.normalized_vertices

            v_min, v_max = vertices[0], vertices[2]

            x = v_min.x * image_width
            y = v_min.y * image_height
            width = (v_max.x - v_min.x) * image_width
            height = (v_max.y - v_min.y) * image_height

            normalized_rect = [
                int(v_min.y * 1000),
                int(v_min.x * 1000),
                int(v_max.y * 1000),
                int(v_max.x * 1000),
            ]

            detected.append(
                {
                    "label": label,
                    "rect": normalized_rect,
                }
            )

            difference = Difference(
                puzzle_id=puzzle.id, index=index, x=x, y=y, width=width, height=height
            )

            session.add(difference)
            session.flush()

        debug_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        draw = ImageDraw.Draw(debug_image)
        for rect in detected:
            ymin, xmin, ymax, xmax = rect["rect"]
            x1 = int(xmin / 1000 * image_width)
            y1 = int(ymin / 1000 * image_height)
            x2 = int(xmax / 1000 * image_width)
            y2 = int(ymax / 1000 * image_height)
            draw.rectangle(
                [
                    (x1, y1),
                    (x2, y2),
                ],
                outline="red",
                width=3,
            )
        debug_image.show(title=f"slot-{slot_id}-detections")

        slot.detected_objects = detected
        slot.analysis_status = "completed"
        slot.analysis_error = None
        slot.last_analyzed_at = datetime.now()
        if existing_stage:
            existing_stage.total_difference_count = len(detected)
            existing_stage.status = "waiting_puzzle"

    return {"slot_id": slot.id, "detected": detected}


@celery_app.task
def edit_image_with_nano_banana(payload: dict):
    slot_id = payload["slot_id"]
    detected = payload["detected"]
    with get_session() as session:
        slot = session.get(GameUploadSlot, slot_id)
        if slot is None or not slot.s3_object_key:
            return

        s3_object_key = slot.s3_object_key

        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        try:
            s3_response = s3_client.get_object(
                Bucket=settings.aws_s3_bucket_name, Key=s3_object_key
            )
            image_bytes = s3_response["Body"].read()
        except Exception as e:
            slot.analysis_status = "failed"
            slot.analysis_error = f"S3 download failed: {e}"
            slot.last_analyzed_at = datetime.now()
            return

        prompt = _build_prompt(detected)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        client = genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location="us-central1",
        )

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[prompt, image_part],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
        except Exception as e:
            slot.analysis_status = "failed"
            slot.analysis_error = f"Gemini call failed: {e}"
            slot.last_analyzed_at = datetime.now()
            return

        candidates = getattr(response, "candidates", None)
        if not candidates:
            slot.analysis_status = "failed"
            slot.analysis_error = "Gemini returned nothing."
            slot.last_analyzed_at = datetime.now()
            return

        content = getattr(candidates[0], "content", None)
        if not content or not getattr(content, "parts", None):
            slot.analysis_status = "failed"
            slot.analysis_error = "Gemini returned nothing."
            slot.last_analyzed_at = datetime.now()
            return

        game = session.get(Game, slot.game_id)
        if game is None:
            slot.analysis_status = "failed"
            slot.analysis_error = "Game not found."
            slot.last_analyzed_at = datetime.now()
            return

        stage = session.get(GameStage, slot.stage_id) if slot.stage_id else None
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
        if not stage or not stage.puzzle:
            slot.analysis_status = "failed"
            slot.analysis_error = "Puzzle not found"
            slot.last_analyzed_at = datetime.now()
            return

        processed = False

        for part in content.parts:
            inline = getattr(part, "inline_data", None)
            if not inline:
                continue

            image_bytes = inline.data
            if image_bytes is None:
                slot.analysis_status = "failed"
                slot.analysis_error = "Gemini returned nothing."
                slot.last_analyzed_at = datetime.now()
                return

            output_key = s3_object_key.replace(".png", "-modified.png")

            s3_client.put_object(
                Bucket=settings.aws_s3_bucket_name,
                Key=output_key,
                Body=image_bytes,
                ContentType="image/png",
            )

            stage.puzzle.modified_image_url = output_key
            stage.status = "playing"
            game.status = "playing"

            slot.analysis_status = "completed"
            slot.analysis_error = None
            slot.last_analyzed_at = datetime.now()


@celery_app.task
def edit_image_with_imagen(payload: dict):
    slot_id = payload["slot_id"]
    detected = payload["detected"]
    with get_session() as session:
        slot = session.get(GameUploadSlot, slot_id)
        if slot is None or not slot.s3_object_key:
            return

        s3_object_key = slot.s3_object_key
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        try:
            response = s3_client.get_object(
                Bucket=settings.aws_s3_bucket_name, Key=s3_object_key
            )
            image_bytes = response["Body"].read()
        except Exception as exc:
            slot.analysis_status = "failed"
            slot.analysis_error = f"S3 download failed: {exc}"
            slot.last_analyzed_at = datetime.now()
            return

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                image_width, image_height = img.size
        except Exception as exc:
            slot.analysis_status = "failed"
            slot.analysis_error = f"Invalid image: {exc}"
            slot.last_analyzed_at = datetime.now()
            return

        detection_results: list[dict] = []
        for item in detected:
            rect = item.get("rect")
            if not rect or len(rect) != 4:
                continue
            ymin, xmin, ymax, xmax = rect
            pixel_box = {
                "xmin": int(xmin / 1000 * image_width),
                "ymin": int(ymin / 1000 * image_height),
                "xmax": int(xmax / 1000 * image_width),
                "ymax": int(ymax / 1000 * image_height),
            }
            detection_results.append(
                {
                    "name": item.get("label") or "object",
                    "pixel_box": pixel_box,
                    "prompt": item.get("prompt")
                    or f"Modify {item.get('label') or 'object'} to create a difference.",
                }
            )

        if not detection_results:
            slot.analysis_status = "failed"
            slot.analysis_error = "No detection results for Imagen."
            slot.last_analyzed_at = datetime.now()
            return

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        try:
            temp_file.write(image_bytes)
            temp_file.flush()
            temp_file_path = temp_file.name
        finally:
            temp_file.close()

        try:
            imagen_bytes = modify_image_with_imagen(
                temp_file_path,
                detection_results,
            )
        except Exception as exc:
            imagen_bytes = None
            slot.analysis_status = "failed"
            slot.analysis_error = f"Imagen edit failed: {exc}"
            slot.last_analyzed_at = datetime.now()
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

        if not imagen_bytes:
            return

        output_key = s3_object_key.replace(".png", "-imagen.png")
        s3_client.put_object(
            Bucket=settings.aws_s3_bucket_name,
            Key=output_key,
            Body=imagen_bytes,
            ContentType="image/png",
        )

        game = session.get(Game, slot.game_id)
        if game is None:
            slot.analysis_status = "failed"
            slot.analysis_error = "Game not found."
            slot.last_analyzed_at = datetime.now()
            return

        stage = session.get(GameStage, slot.stage_id) if slot.stage_id else None
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
        if not stage or not stage.puzzle:
            slot.analysis_status = "failed"
            slot.analysis_error = "Puzzle not found."
            slot.last_analyzed_at = datetime.now()
            return

        stage.puzzle.modified_image_url = output_key
        stage.status = "playing"
        game.status = "playing"

        slot.analysis_status = "completed"
        slot.analysis_error = None
        slot.last_analyzed_at = datetime.now()


@celery_app.task
def run_imagen_pipeline(slot_id: int) -> None:
    chain(
        detect_objects_for_slot.s(slot_id),
        edit_image_with_imagen.s(),
    ).delay()


def _build_prompt(detected_objects: list) -> str:
    import random

    # 1. 틀린그림찾기용 액션 리스트 (랜덤 선택용)
    actions = [
        "Change the color of the object to a different hue.",  # 색상 변경
        "Replace the object with a similar but distinct item.",  # 비슷한 물건으로 교체
        "Remove the object completely and fill with background (inpainting).",  # 삭제
        "Change the texture or pattern of the object.",  # 패턴 변경
        "Flip or rotate the object slightly.",  # 회전/반전
    ]

    # 2. 프롬프트 헤더 작성
    prompt_lines = [
        "Create a 'Spot the Difference' puzzle image based on the input image.",
        "Apply visual modifications ONLY to the specific regions defined by the bounding boxes below.",
        "The coordinates are provided in [ymin, xmin, ymax, xmax] format on a 0-1000 scale.",
        "",  # 가독성을 위한 빈 줄
    ]

    # 3. 각 영역별 지시사항 생성
    for idx, item in enumerate(detected_objects, 1):
        rect = item["rect"]
        action = random.choice(actions)

        prompt_lines.append(f"{idx}. Region {rect}: {action}")

    # 4. 프롬프트 푸터
    prompt_lines.extend(
        [
            "",
            "Constraints:",
            "- Ensure all edits blend seamlessly with the original image's lighting, shadows, and style.",
            "- Do NOT modify any part of the image outside the specified bounding boxes.",
            "- Keep the image realistic and high quality.",
        ]
    )

    # 5. 하나의 문자열로 합쳐서 반환
    return "\n".join(prompt_lines)


@celery_app.task
def process_uploaded_image(slot_id: int):
    with get_session() as session:
        slot = session.get(GameUploadSlot, slot_id)
        if slot is None:
            return
        if slot.s3_object_key is None:
            slot.analysis_status = "failed"
            slot.analysis_error = "Upload slot has no image."
            slot.last_analyzed_at = datetime.now()
            return

        slot.analysis_status = "processing"
        slot.analysis_error = None
        slot.last_analyzed_at = datetime.now()

        game = session.get(Game, slot.game_id)
        if game is None:
            slot.analysis_status = "failed"
            slot.analysis_error = "Game not found."
            slot.last_analyzed_at = datetime.now()
            return

        existing_stage = (
            session.get(GameStage, slot.stage_id) if slot.stage_id else None
        )
        puzzle = (
            existing_stage.puzzle if existing_stage and existing_stage.puzzle else None
        )

        if puzzle is None:
            puzzle = Puzzle(
                difficulty=game.difficulty,
                original_image_url=slot.s3_object_key,
                modified_image_url=slot.s3_object_key,
                width=0,
                height=0,
            )
            session.add(puzzle)
            session.flush()

            if existing_stage is not None:
                existing_stage.puzzle_id = puzzle.id
            else:
                stage = GameStage(
                    game_id=game.id,
                    puzzle_id=puzzle.id,
                    stage_number=slot.slot_number,
                    status="waiting_puzzle",
                    started_at=datetime.now(),
                )
                session.add(stage)
                session.flush()
                slot.stage_id = stage.id
                game.status = "waiting_puzzle"
                existing_stage = stage

        # 이미지 가져오기
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )

        try:
            s3_response = s3_client.get_object(
                Bucket=settings.aws_s3_bucket_name, Key=slot.s3_object_key
            )
            image_bytes = s3_response["Body"].read()
        except Exception as exc:
            slot.analysis_status = "failed"
            slot.analysis_error = f"S3 download failed: {exc}"
            slot.last_analyzed_at = datetime.now()
            return

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                img_width, img_height = img.size
        except Exception as exc:
            slot.analysis_status = "failed"
            slot.analysis_error = f"Invalid image: {exc}"
            slot.last_analyzed_at = datetime.now()
            return

        puzzle.width = img_width
        puzzle.height = img_height

        detected = []
        index = 0

        stmt = delete(Difference).where(Difference.puzzle_id == puzzle.id)
        session.execute(stmt)
        try:
            detection_results = find_game_objects_normalized(image_bytes)
        except Exception as exc:
            detection_results = None
            slot.analysis_error = f"Gemini detection failed: {exc}"
        if not detection_results:
            slot.analysis_status = "failed"
            if slot.analysis_error is None:
                slot.analysis_error = "Gemini detection returned no objects."
            slot.last_analyzed_at = datetime.now()
            return

        debug_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        debug_draw = ImageDraw.Draw(debug_image)
        for item in detection_results:
            pixel_box = item.get("pixel_box")
            if not pixel_box:
                continue
            debug_draw.rectangle(
                [
                    (pixel_box["xmin"], pixel_box["ymin"]),
                    (pixel_box["xmax"], pixel_box["ymax"]),
                ],
                outline="red",
                width=3,
            )
            label = item.get("name")
            if label:
                debug_draw.text(
                    (pixel_box["xmin"], max(0, pixel_box["ymin"] - 12)),
                    label,
                    fill="red",
                )
        debug_image.show(title=f"slot-{slot_id}-detection")

        slot.detected_objects = []

        for item in detection_results:
            index += 1
            pixel_box = item["pixel_box"]

            x = pixel_box["xmin"]
            y = pixel_box["ymin"]
            width = pixel_box["xmax"] - pixel_box["xmin"]
            height = pixel_box["ymax"] - pixel_box["ymin"]

            difference = Difference(
                puzzle_id=puzzle.id,
                index=index,
                x=x,
                y=y,
                width=width,
                height=height,
                label=item.get("name"),
            )
            session.add(difference)
            detected.append(difference)

            normalized_rect = [
                int(coord * 1000) for coord in item.get("normalized", [])
            ]
            slot.detected_objects.append(
                {
                    "label": item.get("name"),
                    "rect": normalized_rect,
                    "prompt": item.get("prompt"),
                }
            )

        if existing_stage:
            existing_stage.total_difference_count = len(detected)

        temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            temp_file.write(image_bytes)
            temp_file.flush()
            temp_file_path = temp_file.name
        finally:
            temp_file.close()

        try:
            imagen_output = modify_image_with_imagen2(temp_file_path, detection_results)
        except Exception as exc:
            os.unlink(temp_file_path)
            slot.analysis_status = "failed"
            slot.analysis_error = f"Imagen edit failed: {exc}"
            slot.last_analyzed_at = datetime.now()
            return
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

        if isinstance(imagen_output, (bytes, bytearray)):
            output_key = slot.s3_object_key.replace(".png", "-modified.png")
            s3_client.put_object(
                Bucket=settings.aws_s3_bucket_name,
                Key=output_key,
                Body=imagen_output,
                ContentType="image/png",
            )
        elif isinstance(imagen_output, str):
            output_key = imagen_output
        else:
            slot.analysis_status = "failed"
            slot.analysis_error = "Imagen returned no data."
            slot.last_analyzed_at = datetime.now()
            return

        puzzle.modified_image_url = output_key
        slot.analysis_status = "completed"
        slot.analysis_error = None
        slot.last_analyzed_at = datetime.now()

        if existing_stage:
            existing_stage.status = "playing"
            existing_stage.started_at = existing_stage.started_at or datetime.now()
        game.status = "playing"
