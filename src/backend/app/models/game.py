from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.puzzle import Difference, Puzzle


class Game(Base):
    """게임 모델"""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="waiting_upload"
    )
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_score: Mapped[int] = mapped_column(default=0)

    stages: Mapped[list["GameStage"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GameStage.stage_number",
    )


class GameStage(Base):
    """게임 내 단일 스테이지/퍼즐 진행 상태"""

    __tablename__ = "game_stages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
    )
    puzzle_id: Mapped[int] = mapped_column(
        ForeignKey("puzzles.id", ondelete="SET NULL"),
        nullable=True,
    )
    stage_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="waiting_puzzle"
    )
    found_difference_count: Mapped[int] = mapped_column(default=0)
    total_difference_count: Mapped[int | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    game: Mapped[Game] = relationship(back_populates="stages")
    puzzle: Mapped[Puzzle | None] = relationship(lazy="joined")
    hits: Mapped[list["GameStageHit"]] = relationship(
        back_populates="stage", cascade="all, delete-orphan", lazy="selectin"
    )


class GameStageHit(Base):
    """스테이지 내 특정 Rect를 맞힌 기록"""

    __tablename__ = "game_stage_hits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("game_stages.id", ondelete="CASCADE"),
        nullable=False,
    )
    difference_id: Mapped[int | None] = mapped_column(
        ForeignKey("differences.id", ondelete="SET NULL"),
        nullable=True,
    )
    hit_at: Mapped[datetime] = mapped_column(default=datetime.now)

    stage: Mapped[GameStage] = relationship(back_populates="hits")
    difference: Mapped[Difference | None] = relationship()
