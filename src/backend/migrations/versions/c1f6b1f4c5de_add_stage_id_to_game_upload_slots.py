"""add stage_id to game_upload_slots

Revision ID: c1f6b1f4c5de
Revises: 81d07d45b61d
Create Date: 2025-11-21 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1f6b1f4c5de"
down_revision: Union[str, Sequence[str], None] = "81d07d45b61d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "game_upload_slots",
        sa.Column(
            "stage_id",
            sa.Integer(),
            sa.ForeignKey("game_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("game_upload_slots", "stage_id")

