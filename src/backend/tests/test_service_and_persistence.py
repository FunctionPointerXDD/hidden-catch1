"""Status transitions across worker persistence and the API service (SQLite)."""

from datetime import datetime

from app.models import Game, GameStage, GameUploadSlot
from app.schemas.game import StageCompleteRequest
from app.services.game_service import GameService
from app.worker import tasks


def _result(stage_label: str) -> tasks.PuzzleResult:
    return tasks.PuzzleResult(
        original_key=f"cache/{stage_label}/original.jpg",
        modified_key=f"cache/{stage_label}/modified.jpg",
        width=1024,
        height=768,
        differences=[
            {"index": 1, "x": 10, "y": 10, "width": 50, "height": 40, "label": "a"},
            {"index": 2, "x": 200, "y": 300, "width": 60, "height": 60, "label": "b"},
        ],
        detected=[{"label": "a", "rect": [13, 9, 65, 58]}],
        model="fake",
    )


def _create_game(session, slot_count: int) -> Game:
    game = Game(
        mode="single",
        difficulty="easy",
        status="waiting_upload",
        time_limit_seconds=180,
    )
    session.add(game)
    session.flush()
    for number in range(1, slot_count + 1):
        stage = GameStage(game_id=game.id, stage_number=number, status="waiting_upload")
        session.add(stage)
        session.flush()
        session.add(
            GameUploadSlot(
                game_id=game.id,
                slot_number=number,
                presigned_url="https://s3.test/put",
                expires_at=datetime.now(),
                s3_object_key=f"uploads/game-{game.id}/slot-{number}.png",
                uploaded=True,
                stage_id=stage.id,
            )
        )
    session.commit()
    return game


def _ids(session, game: Game, number: int) -> tuple[int, int]:
    slot = (
        session.query(GameUploadSlot)
        .filter_by(game_id=game.id, slot_number=number)
        .one()
    )
    return slot.id, slot.stage_id


def test_persist_result_makes_stage_and_game_playable(db_session, fake_s3):
    game = _create_game(db_session, 2)
    slot_id, stage_id = _ids(db_session, game, 1)

    tasks._persist_result(db_session, slot_id, stage_id, game.id, _result("s1"))
    db_session.commit()
    db_session.expire_all()

    stage = db_session.get(GameStage, stage_id)
    slot = db_session.get(GameUploadSlot, slot_id)
    game = db_session.get(Game, game.id)
    assert stage.status == "playing"
    assert stage.total_difference_count == 2
    assert stage.puzzle is not None and stage.puzzle.is_completed
    assert [d.label for d in stage.puzzle.differences] == ["a", "b"]
    assert slot.analysis_status == "completed"
    assert game.status == "playing"

    detail = GameService(db_session, s3_client=fake_s3).get_game_detail(game.id)
    assert detail.status == "playing"
    assert detail.current_stage == 1
    assert detail.total_stages == 2
    assert detail.ready_stages == 1 and detail.failed_stages == 0
    assert detail.puzzle is not None
    assert detail.puzzle.total_difference_count == 2
    assert detail.puzzle.original_image_url.startswith(
        "https://s3.test/cache/s1/original.jpg"
    )

    # Re-running persistence (redelivered task) replaces, not duplicates, answers.
    tasks._persist_result(db_session, slot_id, stage_id, game.id, _result("s1"))
    db_session.commit()
    db_session.expire_all()
    assert len(db_session.get(GameStage, stage_id).puzzle.differences) == 2


def test_later_stage_finishing_first_does_not_expose_missing_puzzle(
    db_session, fake_s3
):
    game = _create_game(db_session, 2)
    slot2, stage2 = _ids(db_session, game, 2)
    tasks._persist_result(db_session, slot2, stage2, game.id, _result("s2"))
    db_session.commit()
    db_session.expire_all()

    game = db_session.get(Game, game.id)
    assert game.status == "waiting_upload"  # stage 1 is still pending
    detail = GameService(db_session, s3_client=fake_s3).get_game_detail(game.id)
    assert detail.puzzle is None
    assert detail.ready_stages == 1


def test_failed_stage_is_skipped(db_session, fake_s3):
    game = _create_game(db_session, 3)
    slot1, stage1 = _ids(db_session, game, 1)
    slot2, stage2 = _ids(db_session, game, 2)
    slot3, stage3 = _ids(db_session, game, 3)

    tasks._mark_failed(db_session, slot1, stage1, game.id, "ImageEditError: nope")
    tasks._persist_result(db_session, slot2, stage2, game.id, _result("s2"))
    db_session.commit()
    db_session.expire_all()

    game = db_session.get(Game, game.id)
    assert game.status == "playing"  # first *playable* stage is ready
    assert db_session.get(GameUploadSlot, slot1).analysis_error.startswith(
        "ImageEditError"
    )

    service = GameService(db_session, s3_client=fake_s3)
    detail = service.get_game_detail(game.id)
    assert detail.current_stage == 2
    assert detail.total_stages == 2 and detail.failed_stages == 1
    assert detail.puzzle is not None

    # Finishing stage 2 while stage 3 is still generating -> wait.
    outcome = service.complete_stage(
        game.id, 2, StageCompleteRequest(play_time_milliseconds=5)
    )
    assert outcome.status == "waiting_next_stage"
    assert outcome.next_stage_number == 3 and outcome.next_puzzle is None
    completed_at = db_session.get(GameStage, stage2).completed_at

    # Polling the same endpoint must not rewrite completion time.
    service.complete_stage(game.id, 2, StageCompleteRequest(play_time_milliseconds=0))
    assert db_session.get(GameStage, stage2).completed_at == completed_at

    # Stage 3 fails -> the game is over, nothing left to wait for.
    tasks._mark_failed(db_session, slot3, stage3, game.id, "boom")
    db_session.commit()
    outcome = service.complete_stage(
        game.id, 2, StageCompleteRequest(play_time_milliseconds=0)
    )
    assert outcome.status == "finished"
    assert outcome.next_puzzle is None and outcome.next_stage_number is None
    assert outcome.total_stages == 1


def test_all_stages_failed_marks_game_failed(db_session, fake_s3):
    game = _create_game(db_session, 2)
    for number in (1, 2):
        slot_id, stage_id = _ids(db_session, game, number)
        tasks._mark_failed(db_session, slot_id, stage_id, game.id, "no objects")
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Game, game.id).status == "failed"
    detail = GameService(db_session, s3_client=fake_s3).get_game_detail(game.id)
    assert detail.status == "failed" and detail.puzzle is None
    assert detail.total_stages == 0 and detail.failed_stages == 2


def test_complete_stage_serves_next_ready_puzzle(db_session, fake_s3):
    game = _create_game(db_session, 2)
    for number in (1, 2):
        slot_id, stage_id = _ids(db_session, game, number)
        tasks._persist_result(
            db_session, slot_id, stage_id, game.id, _result(f"s{number}")
        )
    db_session.commit()

    service = GameService(db_session, s3_client=fake_s3)
    outcome = service.complete_stage(
        game.id, 1, StageCompleteRequest(play_time_milliseconds=1000)
    )
    assert outcome.status == "playing"
    assert outcome.next_stage_number == 2
    assert outcome.next_puzzle is not None
    assert outcome.next_puzzle.modified_image_url.startswith(
        "https://s3.test/cache/s2/modified.jpg"
    )

    outcome = service.complete_stage(
        game.id, 2, StageCompleteRequest(play_time_milliseconds=1000)
    )
    assert outcome.status == "finished" and outcome.next_puzzle is None


def test_mark_upload_failed_skips_stage(db_session, fake_s3):
    from fastapi import HTTPException

    from app.schemas.game import UploadCompleteRequest

    game = _create_game(db_session, 2)
    slot1 = (
        db_session.query(GameUploadSlot).filter_by(game_id=game.id, slot_number=1).one()
    )
    slot1.uploaded = False
    db_session.commit()

    service = GameService(db_session, s3_client=fake_s3)
    status = service.mark_upload_failed(game.id, UploadCompleteRequest(slot=1))
    assert status.slot_statuses[0].analysis_status == "failed"
    assert db_session.get(GameStage, slot1.stage_id).status == "failed"

    # Slot 2 becomes the first playable stage.
    slot2, stage2 = _ids(db_session, game, 2)
    tasks._persist_result(db_session, slot2, stage2, game.id, _result("s2"))
    db_session.commit()
    detail = service.get_game_detail(game.id)
    assert detail.status == "playing" and detail.current_stage == 2
    assert detail.total_stages == 1 and detail.failed_stages == 1

    # An uploaded slot cannot be marked as failed by the client.
    try:
        service.mark_upload_failed(game.id, UploadCompleteRequest(slot=2))
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover
        raise AssertionError("expected 409")
