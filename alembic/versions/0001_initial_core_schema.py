"""initial_core_schema

Revision ID: 0001_initial_core_schema
Revises:
Create Date: 2026-06-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "0001_initial_core_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "board",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("icon", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("system_prompt", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source_config", sa.JSON(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("schedule", sa.Text(), server_default="", nullable=False),
        sa.Column("notify_channels", sa.Text(), server_default="", nullable=False),
        sa.Column("perspectives", sa.JSON(), nullable=True),
        sa.Column("prompt_key", sa.Text(), server_default="daily_briefing", nullable=False),
        sa.Column("output_language", sa.Text(), server_default="auto", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_board_display_order"), "board", ["display_order"], unique=False)
    op.create_index(op.f("ix_board_slug"), "board", ["slug"], unique=True)

    op.create_table(
        "dailysummary",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("perspective", sa.Text(), server_default="overview", nullable=False),
        sa.Column("overview", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("stats_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("board_id", "date", "perspective", name="ux_dailysummary_board_date_perspective"),
    )
    op.create_index(op.f("ix_dailysummary_board_id"), "dailysummary", ["board_id"], unique=False)
    op.create_index(op.f("ix_dailysummary_date"), "dailysummary", ["date"], unique=False)

    op.create_table(
        "contentcluster",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(), nullable=True),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_contentcluster_board_id"), "contentcluster", ["board_id"], unique=False)
    op.create_index(op.f("ix_contentcluster_fingerprint"), "contentcluster", ["fingerprint"], unique=True)

    op.create_table(
        "newsitem",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("headline", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("key_points", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("topic_path", sa.Text(), server_default="", nullable=False),
        sa.Column("original_link", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("summary_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["contentcluster.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["summary_id"], ["dailysummary.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_newsitem_category"), "newsitem", ["category"], unique=False)
    op.create_index(op.f("ix_newsitem_cluster_id"), "newsitem", ["cluster_id"], unique=False)
    op.create_index(op.f("ix_newsitem_headline"), "newsitem", ["headline"], unique=False)

    op.create_table(
        "userfeedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sentiment", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_userfeedback_article_url"), "userfeedback", ["article_url"], unique=True)

    op.create_table(
        "chatmessage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chatmessage_article_url"), "chatmessage", ["article_url"], unique=False)

    op.create_table(
        "articleoverview",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("overview_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_articleoverview_article_url"), "articleoverview", ["article_url"], unique=True)

    op.create_table(
        "userpersona",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("source", sa.Text(), server_default="manual", nullable=False),
        sa.Column("last_refreshed", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_userpersona_board_id"), "userpersona", ["board_id"], unique=False)
    op.create_index(op.f("ix_userpersona_category"), "userpersona", ["category"], unique=False)

    op.create_table(
        "usermemory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sa.Text(), server_default="auto", nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_usermemory_category"), "usermemory", ["category"], unique=False)
    op.create_index(op.f("ix_usermemory_key"), "usermemory", ["key"], unique=True)

    op.create_table(
        "dailyreportrefinementsession",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("date", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("original_summary_json", sa.JSON(), nullable=True),
        sa.Column("refined_summary_json", sa.JSON(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["board_id"], ["board.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dailyreportrefinementsession_board_id"),
        "dailyreportrefinementsession",
        ["board_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dailyreportrefinementsession_date"),
        "dailyreportrefinementsession",
        ["date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dailyreportrefinementsession_status"),
        "dailyreportrefinementsession",
        ["status"],
        unique=False,
    )

    op.create_table(
        "articlereadstate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["board_id"], ["board.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_url", "board_id", name="ux_articlereadstate_url_board"),
    )
    op.create_index(op.f("ix_articlereadstate_article_url"), "articlereadstate", ["article_url"], unique=False)
    op.create_index(op.f("ix_articlereadstate_board_id"), "articlereadstate", ["board_id"], unique=False)
    op.create_index(op.f("ix_articlereadstate_is_read"), "articlereadstate", ["is_read"], unique=False)

    op.create_table(
        "savedarticle",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("headline", sa.Text(), server_default="", nullable=False),
        sa.Column("source", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.Text(), server_default="", nullable=False),
        sa.Column("board_slug", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_url", "status", name="ux_savedarticle_url_status"),
    )
    op.create_index(op.f("ix_savedarticle_article_url"), "savedarticle", ["article_url"], unique=False)
    op.create_index(op.f("ix_savedarticle_status"), "savedarticle", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_savedarticle_status"), table_name="savedarticle")
    op.drop_index(op.f("ix_savedarticle_article_url"), table_name="savedarticle")
    op.drop_table("savedarticle")
    op.drop_index(op.f("ix_articlereadstate_is_read"), table_name="articlereadstate")
    op.drop_index(op.f("ix_articlereadstate_board_id"), table_name="articlereadstate")
    op.drop_index(op.f("ix_articlereadstate_article_url"), table_name="articlereadstate")
    op.drop_table("articlereadstate")
    op.drop_index(op.f("ix_dailyreportrefinementsession_status"), table_name="dailyreportrefinementsession")
    op.drop_index(op.f("ix_dailyreportrefinementsession_date"), table_name="dailyreportrefinementsession")
    op.drop_index(op.f("ix_dailyreportrefinementsession_board_id"), table_name="dailyreportrefinementsession")
    op.drop_table("dailyreportrefinementsession")
    op.drop_index(op.f("ix_usermemory_key"), table_name="usermemory")
    op.drop_index(op.f("ix_usermemory_category"), table_name="usermemory")
    op.drop_table("usermemory")
    op.drop_index(op.f("ix_userpersona_category"), table_name="userpersona")
    op.drop_index(op.f("ix_userpersona_board_id"), table_name="userpersona")
    op.drop_table("userpersona")
    op.drop_index(op.f("ix_articleoverview_article_url"), table_name="articleoverview")
    op.drop_table("articleoverview")
    op.drop_index(op.f("ix_chatmessage_article_url"), table_name="chatmessage")
    op.drop_table("chatmessage")
    op.drop_index(op.f("ix_userfeedback_article_url"), table_name="userfeedback")
    op.drop_table("userfeedback")
    op.drop_index(op.f("ix_newsitem_headline"), table_name="newsitem")
    op.drop_index(op.f("ix_newsitem_cluster_id"), table_name="newsitem")
    op.drop_index(op.f("ix_newsitem_category"), table_name="newsitem")
    op.drop_table("newsitem")
    op.drop_index(op.f("ix_contentcluster_fingerprint"), table_name="contentcluster")
    op.drop_index(op.f("ix_contentcluster_board_id"), table_name="contentcluster")
    op.drop_table("contentcluster")
    op.drop_index(op.f("ix_dailysummary_date"), table_name="dailysummary")
    op.drop_index(op.f("ix_dailysummary_board_id"), table_name="dailysummary")
    op.drop_table("dailysummary")
    op.drop_index(op.f("ix_board_slug"), table_name="board")
    op.drop_index(op.f("ix_board_display_order"), table_name="board")
    op.drop_table("board")
