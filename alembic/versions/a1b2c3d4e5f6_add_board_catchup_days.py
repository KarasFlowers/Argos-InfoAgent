"""add_board_catchup_days

Revision ID: a1b2c3d4e5f6
Revises: 892f72113d37
Create Date: 2026-06-04 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '892f72113d37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('board', sa.Column('catchup_days', sa.Integer(), server_default='7', nullable=False))


def downgrade() -> None:
    op.drop_column('board', 'catchup_days')
