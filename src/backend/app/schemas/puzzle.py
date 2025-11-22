from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.types import Difficulty, GameStatus


class DifferenceInfo(BaseModel):
    """수정된 부분(Rect) 정보"""

    difference_id: int = Field(..., description="Rect ID")
    x: float = Field(..., description="Rect X 좌표")
    y: float = Field(..., description="Rect Y 좌표")
    width: float = Field(..., description="Rect 너비")
    height: float = Field(..., description="Rect 높이")
    label: str | None = Field(
        default=None,
        description="탐지된 오브젝트 (선택)",
    )
    hit_at: datetime | None = Field(
        default=None,
        description="해당 Rect를 맞춘 시각",
    )


class FoundDifference(BaseModel):
    """클라이언트에 알려줄 핵심 정답 정보"""

    difference_id: int = Field(..., description="Rect ID")
    x: float = Field(..., description="Rect 중심 좌표 X")
    y: float = Field(..., description="Rect 중심 좌표 Y")
    label: str | None = Field(..., description="탐지된 오브젝트")
    hit_at: datetime | None = Field(..., description="해당 Rect를 맞춘 시각")


class HitAttempt(BaseModel):
    """사용자가 방금 터치한 좌표"""

    x: float = Field(..., description="터치 좌표 X")
    y: float = Field(..., description="터치 좌표 Y")


class DifferenceCreate(BaseModel):
    """퍼즐 생성 시 각 Rect 정보를 등록할 때 사용"""

    index: int = Field(..., description="차이 순번 (0부터 시작 가능)")
    x: float = Field(..., description="Rect X 좌표")
    y: float = Field(..., description="Rect Y 좌표")
    width: float = Field(..., description="Rect 너비")
    height: float = Field(..., description="Rect 높이")
    label: str | None = Field(
        default=None,
        description="탐지된 오브젝트 (선택)",
    )


class PuzzleCreateRequest(BaseModel):
    """퍼즐 생성 요청"""

    original_image_url: str = Field(..., description="원본 이미지 S3 URL")
    modified_image_url: str = Field(..., description="수정본 이미지 S3 URL")
    width: float = Field(..., description="이미지 너비(px)")
    height: float = Field(..., description="이미지 높이(px)")
    difficulty: Difficulty = Field(..., description="퍼즐 난이도")
    differences: list[DifferenceCreate] = Field(..., description="정답 목록")


class PuzzleResponse(BaseModel):
    """퍼즐 관리용 응답"""

    id: int = Field(..., description="퍼즐 ID")
    difficulty: Difficulty = Field(..., description="퍼즐 난이도")
    total_difference_count: int = Field(..., description="총 개수")
    created_at: datetime = Field(..., description="생성 시각")
    updated_at: datetime | None = Field(
        default=None,
        description="수정 시각",
    )


class PuzzleForGameResponse(BaseModel):
    """특정 스테이지에서 사용할 퍼즐 정보를 게임에 전달"""

    puzzle_id: int = Field(..., description="해당 스테이지에 할당된 퍼즐 ID")
    original_image_url: str = Field(..., description="원본 이미지 S3 URL")
    modified_image_url: str = Field(..., description="수정본 이미지 S3 URL")
    width: float = Field(..., description="이미지 너비(px)")
    height: float = Field(..., description="이미지 높이(px)")
    total_difference_count: int = Field(
        ..., description="해당 스테이지 퍼즐의 차이 총 개수"
    )


class CheckAnswerResponse(BaseModel):
    """한 스테이지에서 정답 판정 후 클라이언트에 돌려주는 결과"""

    is_correct: bool = Field(..., description="정답 여부")
    is_already_found: bool = Field(..., description="이미 찾은 위치인지 여부")
    current_score: int = Field(..., description="게임 누적 점수")
    found_difference_count: int = Field(
        ..., description="이 스테이지 퍼즐에서 찾은 개수"
    )
    total_difference_count: int = Field(..., description="이 스테이지 퍼즐의 전체 개수")
    game_status: str = Field(..., description="게임 상태")
    newly_hit_difference: HitAttempt | None = Field(
        default=None,
        description="이번 요청에서 사용자가 터치한 좌표",
    )
    found_differences: list[FoundDifference] = Field(
        default_factory=list,
        description="해당 스테이지에서 현재까지 맞힌 차이 목록",
    )


class CheckAnswerRequest(BaseModel):
    """스테이지 내 정답 판정을 위한 요청"""

    x: float = Field(..., description="사용자가 선택한 좌표 X 값")
    y: float = Field(..., description="사용자가 선택한 좌표 Y 값")
