"""add upload slot analysis fields

Revision ID: 81d07d45b61d
Revises: b36d05d5a6f4
Create Date: 2025-11-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81d07d45b61d'
down_revision: Union[str, Sequence[str], None] = 'b36d05d5a6f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'game_upload_slots',
        sa.Column(
            'analysis_status',
            sa.String(length=32),
            nullable=False,
            server_default='pending',
        ),
    )
    op.add_column(
        'game_upload_slots',
        sa.Column('analysis_error', sa.String(length=512), nullable=True),
    )
    op.add_column(
        'game_upload_slots',
        sa.Column('detected_objects', sa.JSON(), nullable=True),
    )
    op.add_column(
        'game_upload_slots',
        sa.Column('last_analyzed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('game_upload_slots', 'last_analyzed_at')
    op.drop_column('game_upload_slots', 'detected_objects')
    op.drop_column('game_upload_slots', 'analysis_error')
    op.drop_column('game_upload_slots', 'analysis_status')
