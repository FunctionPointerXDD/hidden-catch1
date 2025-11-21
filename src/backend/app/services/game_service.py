from datetime import datetime, timedelta
from typing import Any

import boto3
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models import Game, GameStage, GameStageHit, GameUploadSlot
from app.schemas.game import (
    CreateGameRequest,
    CreateGameResponse,
    FinishGameRequest,
    FinishGameResponse,
    GameDetailResponse,
    StageCompleteRequest,
    StageResultResponse,
    UploadCompleteRequest,
    UploadSlot,
    UploadSlotsStatusResponse,
    UploadSlotStatus,
)
from app.schemas.puzzle import (
    CheckAnswerRequest,
    CheckAnswerResponse,
    DifferenceInfo,
    PuzzleForGameResponse,
)


def _build_s3_client() -> Any:
    client_kwargs: dict[str, str] = {}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("s3", region_name=settings.aws_region, **client_kwargs)


_S3_CLIENT = _build_s3_client()


class GameService:
    def __init__(self, session: Session, s3_client: Any | None = None):
        self.session = session
        self.s3_client = s3_client or _S3_CLIENT

    def _build_slot_key(self, game_id: int, slot_number: int) -> str:
        prefix = settings.s3_upload_prefix.strip("/")
        key_suffix = f"game-{game_id}/slot-{slot_number}.png"
        return f"{prefix}/{key_suffix}" if prefix else key_suffix

    def _generate_presigned_upload_url(self, object_key: str) -> str:
        if not settings.s3_bucket_name:
            raise HTTPException(status_code=500, detail="S3 bucket is not configured")
        ttl = settings.s3_presign_ttl_seconds if settings.s3_presign_ttl_seconds > 0 else 900
        return self.s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": settings.s3_bucket_name,
                "Key": object_key,
                "ContentType": "image/png",
            },
            ExpiresIn=ttl,
        )

    def create_game(self, payload: CreateGameRequest) -> CreateGameResponse:
        game = Game(
            mode=payload.mode,
            difficulty=payload.difficulty,
            status="waiting_upload",
            time_limit_seconds=payload.time_limit_seconds,
        )
        self.session.add(game)
        self.session.flush()  # assign ID before creating slots

        now = datetime.now()
        slots: list[UploadSlot] = []
        ttl_seconds = (
            settings.s3_presign_ttl_seconds
            if settings.s3_presign_ttl_seconds > 0
            else 900
        )
        for index in range(payload.requested_slot_count):
            slot_number = index + 1
            expires_at = now + timedelta(seconds=ttl_seconds)
            object_key = self._build_slot_key(game.id, slot_number)
            presigned_url = self._generate_presigned_upload_url(object_key)

            upload_slot = GameUploadSlot(
                game_id=game.id,
                slot_number=slot_number,
                presigned_url=presigned_url,
                expires_at=expires_at,
                s3_object_key=object_key,
            )
            self.session.add(upload_slot)

            slots.append(
                UploadSlot(
                    slot=slot_number,
                    presigned_url=presigned_url,
                    expires_at=expires_at,
                )
            )
        self.session.commit()
        return CreateGameResponse(
            game_id=game.id,
            mode=payload.mode,
            difficulty=payload.difficulty,
            status="waiting_upload",
            upload_slots=slots,
            time_limit_seconds=payload.time_limit_seconds or 300,
        )

    def mark_upload_complete(
        self, game_id: int, data: UploadCompleteRequest
    ) -> UploadSlotsStatusResponse:
        slot = (
            self.session.query(GameUploadSlot)
            .filter(
                GameUploadSlot.game_id == game_id,
                GameUploadSlot.slot_number == data.slot,
            )
            .one_or_none()
        )
        if slot is None:
            raise HTTPException(status_code=404, detail="Upload slot not found")

        slot.uploaded = True
        slot.s3_object_key = slot.s3_object_key or self._build_slot_key(
            game_id, slot.slot_number
        )
        slot.analysis_status = "pending"
        slot.analysis_error = None
        slot.detected_objects = None
        slot.last_analyzed_at = None
        self.session.commit()
        detect_objects_for_slot.delay(slot.id)

        slots = (
            self.session.query(GameUploadSlot)
            .filter(GameUploadSlot.game_id == game_id)
            .order_by(GameUploadSlot.slot_number)
            .all()
        )
        status = [
            UploadSlotStatus(
                slot=s.slot_number,
                s3_object_key=s.s3_object_key,
                uploaded=s.uploaded,
                analysis_status=s.analysis_status,
                analysis_error=s.analysis_error,
                detected_objects=s.detected_objects,
                last_analyzed_at=s.last_analyzed_at,
            )
            for s in slots
        ]
        return UploadSlotsStatusResponse(
            game_id=game_id,
            status="waiting_puzzle",
            slot_statuses=status,
        )

    def get_upload_status(self, game_id: int) -> UploadSlotsStatusResponse:
        slots = (
            self.session.query(GameUploadSlot)
            .filter(GameUploadSlot.game_id == game_id)
            .order_by(GameUploadSlot.slot_number)
            .all()
        )
        status = [
            UploadSlotStatus(
                slot=slot.slot_number,
                s3_object_key=slot.s3_object_key,
                uploaded=slot.uploaded,
                analysis_status=slot.analysis_status,
                analysis_error=slot.analysis_error,
                detected_objects=slot.detected_objects,
                last_analyzed_at=slot.last_analyzed_at,
            )
            for slot in slots
        ]
        return UploadSlotsStatusResponse(
            game_id=game_id,
            status="waiting_upload",
            slot_statuses=status,
        )

    def get_game_detail(self, game_id: int) -> GameDetailResponse:
        game = (
            self.session.query(Game)
            .options(
                selectinload(Game.stages).selectinload(GameStage.puzzle),
                selectinload(Game.stages)
                .selectinload(GameStage.hits)
                .selectinload(GameStageHit.difference),
            )
            .filter(Game.id == game_id)
            .one_or_none()
        )
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")

        current_stage = next(
            (
                stage
                for stage in game.stages
                if stage.status in ("waiting_puzzle", "playing")
            ),
            game.stages[-1] if game.stages else None,
        )
        current_stage_number = current_stage.stage_number if current_stage else 0
        puzzle = current_stage.puzzle if current_stage else None
        puzzle_schema = (
            PuzzleForGameResponse(
                puzzle_id=puzzle.id,
                original_image_url=puzzle.original_image_url,
                modified_image_url=puzzle.modified_image_url,
                width=puzzle.width,
                height=puzzle.height,
                total_difference_count=len(puzzle.differences),
            )
            if puzzle
            else None
        )

        return GameDetailResponse(
            game_id=game.id,
            mode=game.mode,
            difficulty=game.difficulty,
            status=game.status,
            created_at=game.created_at,
            updated_at=game.updated_at,
            puzzle=puzzle_schema,
            current_score=game.current_score,
            current_stage=current_stage_number,
            total_stages=len(game.stages),
        )

    def check_answer(
        self, game_id: int, stage_number: int, payload: CheckAnswerRequest
    ) -> CheckAnswerResponse:
        stage = (
            self.session.query(GameStage)
            .options(
                selectinload(GameStage.puzzle),
                selectinload(GameStage.hits).selectinload(GameStageHit.difference),
                selectinload(GameStage.game),
            )
            .filter(
                GameStage.game_id == game_id,
                GameStage.stage_number == stage_number,
            )
            .one_or_none()
        )
        if stage is None:
            raise HTTPException(status_code=404, detail="Stage not found")
        if stage.puzzle is None:
            raise HTTPException(status_code=400, detail="Puzzle not ready")

        matched = self._match_difference(stage.puzzle.differences, payload.x, payload.y)
        total_diffs = stage.total_difference_count or len(stage.puzzle.differences)

        if matched is None:
            return self._build_check_answer_response(
                stage,
                is_correct=False,
                total_difference_count=total_diffs,
            )

        already_hit_ids = {hit.difference_id for hit in stage.hits if hit.difference_id}
        if matched.id in already_hit_ids:
            return self._build_check_answer_response(
                stage,
                is_correct=False,
                is_already_found=True,
                total_difference_count=total_diffs,
            )

        hit = GameStageHit(stage_id=stage.id, difference_id=matched.id)
        stage.hits.append(hit)
        stage.found_difference_count += 1
        stage.game.current_score += 100
        if stage.total_difference_count is None:
            stage.total_difference_count = total_diffs

        self.session.add(hit)
        self.session.commit()
        self.session.refresh(hit)

        return self._build_check_answer_response(
            stage,
            is_correct=True,
            newly_hit=matched,
            hit_record=hit,
            total_difference_count=total_diffs,
        )

    def complete_stage(
        self,
        game_id: int,
        stage_number: int,
        payload: StageCompleteRequest,
    ) -> StageResultResponse:
        stage = (
            self.session.query(GameStage)
            .options(
                selectinload(GameStage.puzzle),
                selectinload(GameStage.game).selectinload(Game.upload_slots),
            )
            .filter(
                GameStage.game_id == game_id,
                GameStage.stage_number == stage_number,
            )
            .one_or_none()
        )
        if stage is None:
            raise HTTPException(status_code=404, detail="Stage not found")

        stage.status = "finished"
        stage.completed_at = datetime.now()
        if stage.total_difference_count is None and stage.puzzle is not None:
            stage.total_difference_count = len(stage.puzzle.differences)

        next_stage = (
            self.session.query(GameStage)
            .options(selectinload(GameStage.puzzle))
            .filter(
                GameStage.game_id == game_id,
                GameStage.stage_number == stage_number + 1,
            )
            .one_or_none()
        )
        next_puzzle_schema = None
        if next_stage and next_stage.puzzle:
            next_puzzle_schema = PuzzleForGameResponse(
                puzzle_id=next_stage.puzzle.id,
                original_image_url=next_stage.puzzle.original_image_url,
                modified_image_url=next_stage.puzzle.modified_image_url,
                width=next_stage.puzzle.width,
                height=next_stage.puzzle.height,
                total_difference_count=len(next_stage.puzzle.differences),
            )
            next_stage.status = "playing"

        self.session.commit()

        return StageResultResponse(
            game_id=game_id,
            stage_number=stage_number,
            total_stages=len(stage.game.stages),
            status=stage.game.status,
            current_score=stage.game.current_score,
            found_difference_count=stage.found_difference_count,
            total_difference_count=stage.total_difference_count or 0,
            next_puzzle=next_puzzle_schema,
        )

    def finish_game(
        self,
        game_id: int,
        payload: FinishGameRequest,
    ) -> FinishGameResponse:
        return FinishGameResponse(
            game_id=game_id,
            status="finished",
            difficulty="normal",
            final_score=2000,
            found_difference_count=25,
            total_difference_count=30,
        )

    def _match_difference(self, differences, x: float, y: float):
        for diff in differences:
            if (
                diff.x <= x <= diff.x + diff.width
                and diff.y <= y <= diff.y + diff.height
            ):
                return diff
        return None

    def _build_check_answer_response(
        self,
        stage: GameStage,
        *,
        is_correct: bool,
        is_already_found: bool = False,
        newly_hit=None,
        hit_record: GameStageHit | None = None,
        total_difference_count: int,
    ) -> CheckAnswerResponse:
        found_infos: list[DifferenceInfo] = []
        for hit in stage.hits:
            if hit.difference is None:
                continue
            found_infos.append(
                DifferenceInfo(
                    difference_id=hit.difference.id,
                    x=hit.difference.x,
                    y=hit.difference.y,
                    width=hit.difference.width,
                    height=hit.difference.height,
                    label=hit.difference.label,
                    hit_at=hit.hit_at,
                )
            )

        newly_hit_info = None
        if newly_hit and hit_record:
            newly_hit_info = DifferenceInfo(
                difference_id=newly_hit.id,
                x=newly_hit.x,
                y=newly_hit.y,
                width=newly_hit.width,
                height=newly_hit.height,
                label=newly_hit.label,
                hit_at=hit_record.hit_at,
            )

        return CheckAnswerResponse(
            is_correct=is_correct,
            is_already_found=is_already_found,
            current_score=stage.game.current_score,
            found_difference_count=stage.found_difference_count,
            total_difference_count=total_difference_count,
            game_status=stage.game.status,
            newly_hit_difference=newly_hit_info,
            found_differences=found_infos,
        )


def get_game_service(session: Session = Depends(get_db)) -> GameService:
    return GameService(session)
