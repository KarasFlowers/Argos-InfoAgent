"""add_board_template_profile

Revision ID: d4e5f6a7b8c9
Revises: c9f1d2e3a4b5
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c9f1d2e3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("board", sa.Column("template_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("board", "template_profile")
