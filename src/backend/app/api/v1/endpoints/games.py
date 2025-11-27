from fastapi import APIRouter, Depends, status

from app.schemas.game import (
    CreateGameRequest,
    CreateGameResponse,
    FinishGameRequest,
    FinishGameResponse,
    GameDetailResponse,
    StageCompleteRequest,
    StageResultResponse,
    UploadCompleteRequest,
    UploadSlotsStatusResponse,
)
from app.schemas.puzzle import CheckAnswerRequest, CheckAnswerResponse
from app.services.game_service import GameService, get_game_service

router = APIRouter(prefix="/games", tags=["games"])


@router.post(
    "",
    response_model=CreateGameResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_game(
    payload: CreateGameRequest,
    service: GameService = Depends(get_game_service),
) -> CreateGameResponse:
    return service.create_game(payload)


@router.post(
    "/{game_id}/uploads/complete",
    response_model=UploadSlotsStatusResponse,
    status_code=status.HTTP_200_OK,
)
def complete_upload(
    game_id: int,
    payload: UploadCompleteRequest,
    service: GameService = Depends(get_game_service),
) -> UploadSlotsStatusResponse:
    return service.mark_upload_complete(game_id, payload)


@router.get(
    "/{game_id}/uploads",
    response_model=UploadSlotsStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_upload_status(
    game_id: int,
    service: GameService = Depends(get_game_service),
) -> UploadSlotsStatusResponse:
    return service.get_upload_status(game_id)


@router.get(
    "/{game_id}",
    response_model=GameDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_game_detail(
    game_id: int,
    service: GameService = Depends(get_game_service),
) -> GameDetailResponse:
    return service.get_game_detail(game_id)


@router.post(
    "/{game_id}/stages/{stage_number}/check",
    response_model=CheckAnswerResponse,
    status_code=status.HTTP_200_OK,
)
def check_answer(
    game_id: int,
    stage_number: int,
    payload: CheckAnswerRequest,
    service: GameService = Depends(get_game_service),
) -> CheckAnswerResponse:
    return service.check_answer(game_id, stage_number, payload)


@router.post(
    "/{game_id}/stages/{stage_number}/complete",
    response_model=StageResultResponse,
    status_code=status.HTTP_200_OK,
)
def complete_stage(
    game_id: int,
    stage_number: int,
    payload: StageCompleteRequest,
    service: GameService = Depends(get_game_service),
) -> StageResultResponse:
    return service.complete_stage(game_id, stage_number, payload)


@router.post(
    "/{game_id}/finish",
    response_model=FinishGameResponse,
    status_code=status.HTTP_200_OK,
)
def finish_game(
    game_id: int,
    payload: FinishGameRequest,
    service: GameService = Depends(get_game_service),
) -> FinishGameResponse:
    return service.finish_game(game_id, payload)
