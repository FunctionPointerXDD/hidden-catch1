from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.puzzle import PuzzleForGameResponse
from app.schemas.types import Difficulty, GameStatus, UploadAnalysisStatus

MAX_UPLOAD_SLOTS = 5


class UploadSlot(BaseModel):
    """이미지 업로드 슬롯 정보"""

    slot: int = Field(..., description="presigned URL이 연결된 업로드 순번")
    presigned_url: str = Field(
        ..., description="클라이언트가 이미지를 PUT할 presigned URL"
    )
    expires_at: datetime = Field(..., description="presigned URL 만료 시각")


class UploadSlotStatus(BaseModel):
    """업로드 슬롯별 현재 상태"""

    slot: int = Field(..., description="업로드 슬롯 번호")
    s3_object_key: str | None = Field(
        default=None,
        description="서버가 슬롯에 매핑한 S3 객체 키",
    )
    uploaded: bool = Field(default=False, description="업로드 완료 여부")
    analysis_status: str = Field(
        default="pending",
        description="Vision 분석 진행 상태",
    )
    analysis_error: str | None = Field(
        default=None,
        description="분석 실패 시 오류 메시지",
    )
    detected_objects: list[dict] | None = Field(
        default=None,
        description="Vision API에서 반환된 오브젝트 목록",
    )
    last_analyzed_at: datetime | None = Field(
        default=None,
        description="마지막 분석 완료 시각",
    )


class DetectedVertex(BaseModel):
    """Vision API에서 반환한 Vertex"""

    x: float = Field(..., description="정규화된 X 좌표(0~1)")
    y: float = Field(..., description="정규화된 Y 좌표(0~1)")


class DetectedObject(BaseModel):
    """Vision API가 탐지한 오브젝트"""

    name: str = Field(..., description="탐지된 오브젝트명")
    score: float = Field(..., description="확신도(0~1)")
    vertices: list[DetectedVertex] = Field(
        default_factory=list, description="bounding poly vertex 목록"
    )


UploadSlotStatus.model_rebuild()


class CreateGameRequest(BaseModel):
    """게임 생성 요청 본문"""

    mode: Literal["single", "multi"] = Field(
        default="single",
        description="single 또는 multi 중 선택",
    )
    difficulty: Difficulty | None = Field(
        default="normal",
        description="easy/normal/difficult 중 선택 값",
    )
    time_limit_seconds: int | None = Field(
        default=180,
        description="게임 제한 시간(초)",
    )
    requested_slot_count: int = Field(
        le=MAX_UPLOAD_SLOTS,
        ge=1,
        description="필요한 업로드 슬롯 수(1~5)",
    )


class CreateGameResponse(BaseModel):
    """게임 생성 응답"""

    game_id: int = Field(..., description="생성된 게임 식별자")
    mode: str = Field(..., description="게임 모드")
    difficulty: str | None = Field(
        default=None,
        description="지정된 난이도",
    )
    status: GameStatus = Field(..., description="현재 게임 상태")
    upload_slots: list[UploadSlot] = Field(
        ...,
        description="각 슬롯의 presigned URL 목록",
    )
    time_limit_seconds: int = Field(..., description="제한 시간(초)")


class UploadCompleteRequest(BaseModel):
    """업로드 완료 보고 요청"""

    slot: int = Field(..., description="업로드를 마친 슬롯 번호")
    # s3_object_key: str


class UploadSlotsStatusResponse(BaseModel):
    """업로드 진행 상태 응답"""

    game_id: int = Field(..., description="게임 식별자")
    status: str = Field(..., description="게임 상태")
    slot_statuses: list[UploadSlotStatus] = Field(
        ...,
        description="슬롯별 업로드 정보 목록",
    )


class GameDetailResponse(BaseModel):
    """게임 상세 조회 응답"""

    game_id: int = Field(..., description="게임 ID")
    mode: str = Field(..., description="게임 모드")
    difficulty: str | None = Field(
        default=None,
        description="게임 난이도",
    )
    status: str = Field(..., description="현재 상태")
    created_at: datetime = Field(..., description="생성 시각")
    updated_at: datetime | None = Field(
        default=None,
        description="수정 시각",
    )
    puzzle: PuzzleForGameResponse | None = Field(
        default=None,
        description="게임에 매핑된 퍼즐 정보",
    )
    current_score: int = Field(..., description="현재 점수")
    current_stage: int = Field(..., description="현재 진행 중인 스테이지 번호")
    total_stages: int = Field(..., description="해당 게임의 전체 스테이지 수")


class StageResultResponse(BaseModel):
    """스테이지가 완료될 때 클라이언트로 전달하는 결과"""

    game_id: int = Field(..., description="게임 식별자")
    stage_number: int = Field(..., description="현재 스테이지 번호")
    total_stages: int = Field(..., description="전체 스테이지 수")
    status: str = Field(..., description="현재 게임 상태")
    current_score: int = Field(..., description="현재까지의 누적 점수")
    found_difference_count: int = Field(..., description="이번 스테이지에서 찾은 개수")
    total_difference_count: int = Field(
        ...,
        description="이번 스테이지 퍼즐의 차이 총 개수",
    )
    next_stage_number: int | None = Field(
        default=None,
        description="다음 스테이지 번호 (없다면 None)",
    )
    next_puzzle: PuzzleForGameResponse | None = Field(
        default=None,
        description="다음 스테이지에서 사용할 퍼즐 정보 (마지막 스테이지라면 None)",
    )


class StageCompleteRequest(BaseModel):
    """스테이지 완료 시 서버에 전달하는 요청"""

    play_time_milliseconds: int | None = Field(
        default=None,
        description="해당 스테이지를 완료하는 데 걸린 시간(밀리초)",
    )


class FinishGameRequest(BaseModel):
    """게임 종료 요청"""

    play_time_milliseconds: int | None = Field(
        default=None,
        description="실제 플레이 시간(밀리초)",
    )


class FinishGameResponse(BaseModel):
    """게임 종료 결과 응답"""

    game_id: int = Field(..., description="게임 ID")
    status: str = Field(..., description="최종 상태")
    difficulty: str | None = Field(
        default=None,
        description="게임 난이도",
    )
    final_score: int = Field(..., description="최종 점수")
