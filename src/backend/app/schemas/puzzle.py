from datetime import datetime

from pydantic import BaseModel


class DifferenceInfo(BaseModel):
    difference_id: int
    x: float
    y: float
    width: float
    height: float
    label: str | None = None


class DifferenceCreate(BaseModel):
    index: int
    x: float
    y: float
    width: float
    height: float
    label: str | None = None


class PuzzleCreateRequest(BaseModel):
    original_image_url: str
    modified_image_url: str
    width: float
    height: float
    difficulty: str
    diferences: list[DifferenceCreate]


class PuzzleResponse(BaseModel):
    id: int
    difficulty: str
    total_difference_count: int
    created_at: datetime
    updated_at: datetime | None


class PuzzleForGameResponse(BaseModel):
    puzzle_id: int
    modified_image_url: str
    width: float
    height: float
    total_difference_count: int
