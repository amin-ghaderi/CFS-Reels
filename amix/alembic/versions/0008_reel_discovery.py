"""Primary and reel sequences, plus reel discovery candidates.

Revision ID: 0008_reel_discovery
Revises: 0007_conversation_map
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_reel_discovery"
down_revision: Union[str, None] = "0007_conversation_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reel_candidate",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("conversation_thread_id", sa.Text(), nullable=False),
        sa.Column("first_turn_id", sa.Text(), nullable=False),
        sa.Column("last_turn_id", sa.Text(), nullable=False),
        sa.Column("first_word_id", sa.Text(), nullable=False),
        sa.Column("last_word_id", sa.Text(), nullable=False),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.CheckConstraint("end_us > start_us", name="ck_reel_candidate_range"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_word_id"], ["word.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_word_id"], ["word.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_run_id", "order_index", name="uq_reel_candidate_order"),
    )
    op.create_index("ix_reel_candidate_run", "reel_candidate", ["analysis_run_id"])
    op.execute(
        "CREATE TABLE sequence_clip_hold AS SELECT id, sequence_id, order_index, source_start_us, source_end_us FROM sequence_clip"
    )
    op.drop_index("ix_sequence_clip_sequence", table_name="sequence_clip")
    op.drop_table("sequence_clip")
    op.create_table(
        "editorial_sequence_next",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("media_asset_id", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("origin_candidate_id", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("source_start_us", sa.BigInteger(), nullable=False),
        sa.Column("source_end_us", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("source_end_us > source_start_us", name="ck_sequence_source_range"),
        sa.CheckConstraint("purpose IN ('primary', 'reel')", name="ck_sequence_purpose"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_asset.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO editorial_sequence_next "
        "(id, project_id, media_asset_id, purpose, origin_candidate_id, display_name, "
        "source_start_us, source_end_us, revision, created_at, updated_at) "
        "SELECT id, project_id, media_asset_id, 'primary', NULL, display_name, "
        "source_start_us, source_end_us, revision, created_at, updated_at FROM editorial_sequence"
    )
    op.drop_table("editorial_sequence")
    op.rename_table("editorial_sequence_next", "editorial_sequence")
    op.create_index(
        "uq_sequence_primary",
        "editorial_sequence",
        ["media_asset_id"],
        unique=True,
        sqlite_where=sa.text("purpose = 'primary'"),
    )
    op.create_index("ix_sequence_asset", "editorial_sequence", ["media_asset_id"])
    op.create_table(
        "sequence_clip",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("sequence_id", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("source_start_us", sa.BigInteger(), nullable=False),
        sa.Column("source_end_us", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("source_end_us > source_start_us", name="ck_sequence_clip_range"),
        sa.ForeignKeyConstraint(["sequence_id"], ["editorial_sequence.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence_id", "order_index", name="uq_sequence_clip_order"),
    )
    op.execute(
        "INSERT INTO sequence_clip (id, sequence_id, order_index, source_start_us, source_end_us) "
        "SELECT id, sequence_id, order_index, source_start_us, source_end_us FROM sequence_clip_hold"
    )
    op.drop_table("sequence_clip_hold")
    op.create_index("ix_sequence_clip_sequence", "sequence_clip", ["sequence_id"])


def downgrade() -> None:
    op.drop_index("ix_sequence_clip_sequence", table_name="sequence_clip")
    op.execute(
        "CREATE TABLE sequence_clip_hold AS SELECT id, sequence_id, order_index, source_start_us, source_end_us FROM sequence_clip"
    )
    op.drop_table("sequence_clip")
    op.drop_index("ix_sequence_asset", table_name="editorial_sequence")
    op.drop_index("uq_sequence_primary", table_name="editorial_sequence")
    op.create_table(
        "editorial_sequence_prev",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("media_asset_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("source_start_us", sa.BigInteger(), nullable=False),
        sa.Column("source_end_us", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("source_end_us > source_start_us", name="ck_sequence_source_range"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_asset.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_asset_id", name="uq_sequence_media"),
    )
    op.execute(
        "INSERT INTO editorial_sequence_prev "
        "(id, project_id, media_asset_id, display_name, source_start_us, source_end_us, revision, created_at, updated_at) "
        "SELECT id, project_id, media_asset_id, display_name, source_start_us, source_end_us, revision, created_at, updated_at "
        "FROM editorial_sequence WHERE purpose = 'primary'"
    )
    op.drop_table("editorial_sequence")
    op.rename_table("editorial_sequence_prev", "editorial_sequence")
    op.create_table(
        "sequence_clip",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("sequence_id", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("source_start_us", sa.BigInteger(), nullable=False),
        sa.Column("source_end_us", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("source_end_us > source_start_us", name="ck_sequence_clip_range"),
        sa.ForeignKeyConstraint(["sequence_id"], ["editorial_sequence.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence_id", "order_index", name="uq_sequence_clip_order"),
    )
    op.execute(
        "INSERT INTO sequence_clip (id, sequence_id, order_index, source_start_us, source_end_us) "
        "SELECT id, sequence_id, order_index, source_start_us, source_end_us FROM sequence_clip_hold "
        "WHERE sequence_id IN (SELECT id FROM editorial_sequence)"
    )
    op.drop_table("sequence_clip_hold")
    op.create_index("ix_sequence_clip_sequence", "sequence_clip", ["sequence_id"])
    op.drop_index("ix_reel_candidate_run", table_name="reel_candidate")
    op.drop_table("reel_candidate")
