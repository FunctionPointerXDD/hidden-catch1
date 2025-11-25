from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import sqltypes

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.game import Game


class GameUploadSlot(Base):
    """게임 생성 시 발급되는 이미지 업로드 슬롯"""

    __tablename__ = "game_upload_slots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
    )
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    presigned_url: Mapped[str] = mapped_column(String(512), nullable=False)
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey("game_stages.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    s3_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    analysis_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    analysis_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detected_objects: Mapped[list[dict] | None] = mapped_column(
        sqltypes.JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    last_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    game: Mapped[Game] = relationship(back_populates="upload_slots")
