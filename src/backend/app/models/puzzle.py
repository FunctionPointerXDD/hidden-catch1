from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Puzzle(Base):
    """게임 스테이지에 배정되는 퍼즐"""

    __tablename__ = "puzzles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    original_image_url: Mapped[str] = mapped_column(nullable=True)
    modified_image_url: Mapped[str] = mapped_column(nullable=False)
    width: Mapped[float] = mapped_column(nullable=False)
    height: Mapped[float] = mapped_column(nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    differences: Mapped[list["Difference"]] = relationship(
        back_populates="puzzle",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class Difference(Base):
    """Rect 정보"""

    __tablename__ = "differences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    puzzle_id: Mapped[int] = mapped_column(
        ForeignKey("puzzles.id", ondelete="CASCADE"),
        nullable=False,
    )
    index: Mapped[int] = mapped_column(nullable=False)
    x: Mapped[float] = mapped_column(nullable=False)
    y: Mapped[float] = mapped_column(nullable=False)
    width: Mapped[float] = mapped_column(nullable=False)
    height: Mapped[float] = mapped_column(nullable=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)

    puzzle: Mapped[Puzzle] = relationship(back_populates="differences")
