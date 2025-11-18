from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.puzzle import PuzzleForGameResponse

GameStatus = Literal["waiting_upload", "waiting_puzzle", "playing", "finished"]


class CreateGameRequest(BaseModel):
    mode: Literal["single", "multi"]
    difficulty: str | None = None
    time_limit_seconds: int | None = None


class CreateGameResponse(BaseModel):
    game_id: int
    mode: str
    status: GameStatus
    original_image_url: str
    s3_object_key: str
    time_limit_seconds: int


class ImageUploadedResponse(BaseModel):
    game_id: int
    status: GameStatus


class GameDetailResponse(BaseModel):
    game_id: int
    mode: str
    status: GameStatus
    created_at: datetime
    updated_at: datetime | None = None

    puzzle: PuzzleForGameResponse | None = None

    current_score: int
    found_difference_count: int
    total_difference_count: int


class FinishGameRequest(BaseModel):
    play_time_milliseconds: int | None = None


class FinishGameResponse(BaseModel):
    game_id: int
    status: GameStatus
    final_score: int
    found_difference_count: int
    total_difference_count: int
