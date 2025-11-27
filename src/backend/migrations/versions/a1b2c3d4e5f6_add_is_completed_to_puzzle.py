"""add is_completed to puzzle

Revision ID: a1b2c3d4e5f6
Revises: c1f6b1f4c5de
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'c1f6b1f4c5de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_completed column with default False
    op.add_column(
        'puzzles',
        sa.Column(
            'is_completed',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )
    
    # Update existing data: set is_completed=True where modified_image_url != original_image_url
    op.execute("""
        UPDATE puzzles
        SET is_completed = true
        WHERE modified_image_url != original_image_url
        OR (modified_image_url IS NOT NULL AND original_image_url IS NULL)
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('puzzles', 'is_completed')

