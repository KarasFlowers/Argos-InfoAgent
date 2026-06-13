"""add_source_credibility_override

Revision ID: c9f1d2e3a4b5
Revises: a1b2c3d4e5f6
Create Date: 2026-06-08 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9f1d2e3a4b5"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source",
        sa.Column("credibility_override", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("source", "credibility_override")
