from datetime import datetime, timedelta

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
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
    PuzzleForGameResponse,
)


class GameService:
    def __init__(self, session: Session):
        self.session = session

    def create_game(self, payload: CreateGameRequest) -> CreateGameResponse:
        # Health-check query to ensure the PostgreSQL connection is alive.
        self.session.execute(text("SELECT 1"))

        now = datetime.now()
        slots = [
            UploadSlot(
                slot=i + 1,
                presigned_url=f"https://s3.example.com/upload/{i + 1}",
                expires_at=now + timedelta(minutes=15),
            )
            for i in range(payload.requested_slot_count)
        ]
        slot_statuses = [UploadSlotStatus(slot=slot.slot) for slot in slots]

        return CreateGameResponse(
            game_id=1,
            mode=payload.mode,
            difficulty=payload.difficulty,
            status="waiting_upload",
            upload_slots=slots,
            slot_statuses=slot_statuses,
            time_limit_seconds=payload.time_limit_seconds or 300,
        )

    def mark_upload_complete(
        self, game_id: int, data: UploadCompleteRequest
    ) -> UploadSlotsStatusResponse:
        status = [
            UploadSlotStatus(
                slot=i,
                s3_object_key=f"games/{game_id}/slot-{i}.png",
                uploaded=i <= data.slot,
            )
            for i in range(1, 6)
        ]
        return UploadSlotsStatusResponse(
            game_id=game_id,
            status="waiting_puzzle",
            slot_statuses=status,
        )

    def get_upload_status(self, game_id: int) -> UploadSlotsStatusResponse:
        status = [
            UploadSlotStatus(
                slot=i,
                s3_object_key=f"games/{game_id}/slot-{i}.png",
                uploaded=False,
            )
            for i in range(1, 6)
        ]
        return UploadSlotsStatusResponse(
            game_id=game_id,
            status="waiting_upload",
            slot_statuses=status,
        )

    def get_game_detail(self, game_id: int) -> GameDetailResponse:
        now = datetime.now()
        return GameDetailResponse(
            game_id=game_id,
            mode="single",
            difficulty="easy",
            status="playing",
            created_at=now - timedelta(minutes=5),
            updated_at=now,
            puzzle=PuzzleForGameResponse(
                puzzle_id=10,
                modified_image_url="https://s3.example.com/puzzles/10.png",
                width=1024,
                height=768,
                total_difference_count=7,
            ),
            current_score=1200,
            current_stage=2,
            total_stages=5,
        )

    def check_answer(
        self, game_id: int, stage_number: int, payload: CheckAnswerRequest
    ) -> CheckAnswerResponse:
        return CheckAnswerResponse(
            is_correct=True,
            is_already_found=False,
            current_score=1300,
            found_difference_count=3,
            total_difference_count=7,
            game_status="playing",
            newly_hit_difference=None,
            found_differences=[],
        )

    def complete_stage(
        self,
        game_id: int,
        stage_number: int,
        payload: StageCompleteRequest,
    ) -> StageResultResponse:
        return StageResultResponse(
            game_id=game_id,
            stage_number=stage_number,
            total_stages=5,
            status="playing",
            current_score=1500,
            found_difference_count=5,
            total_difference_count=7,
            next_puzzle=PuzzleForGameResponse(
                puzzle_id=stage_number + 1,
                modified_image_url=f"https://s3.example.com/puzzles/{stage_number + 1}.png",
                width=1024,
                height=768,
                total_difference_count=6,
            ),
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


def get_game_service(session: Session = Depends(get_db)) -> GameService:
    return GameService(session)
