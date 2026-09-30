"""Sequence-scoped caption tracks and subtitle sidecar provenance.

Revision ID: 0010_caption_track
Revises: 0009_producing_job
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_caption_track"
down_revision: Union[str, None] = "0009_producing_job"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "caption_track",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("media_asset_id", sa.Text(), nullable=False),
        sa.Column("sequence_id", sa.Text(), nullable=False),
        sa.Column("sequence_revision_at_generation", sa.Integer(), nullable=False),
        sa.Column("transcript_analysis_run_id", sa.Text(), nullable=False),
        sa.Column("effective_text_fingerprint", sa.Text(), nullable=False),
        sa.Column("generation_profile", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("superseded_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_caption_track_revision"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_asset.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sequence_id"], ["editorial_sequence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transcript_analysis_run_id"], ["analysis_run.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_caption_track_sequence", "caption_track", ["sequence_id"])
    op.create_index(
        "uq_caption_track_current",
        "caption_track",
        ["sequence_id"],
        unique=True,
        sqlite_where=sa.text("superseded_at IS NULL"),
    )
    op.create_table(
        "caption_cue",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("track_id", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("first_word_id", sa.Text(), nullable=False),
        sa.Column("last_word_id", sa.Text(), nullable=False),
        sa.Column("source_start_us", sa.BigInteger(), nullable=False),
        sa.Column("source_end_us", sa.BigInteger(), nullable=False),
        sa.Column("sequence_start_us", sa.BigInteger(), nullable=False),
        sa.Column("sequence_end_us", sa.BigInteger(), nullable=False),
        sa.Column("generated_text", sa.Text(), nullable=False),
        sa.Column("manual_text", sa.Text(), nullable=True),
        sa.CheckConstraint("source_end_us > source_start_us", name="ck_caption_cue_source"),
        sa.CheckConstraint("sequence_end_us > sequence_start_us", name="ck_caption_cue_sequence"),
        sa.ForeignKeyConstraint(["track_id"], ["caption_track.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_word_id"], ["word.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_word_id"], ["word.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id", "order_index", name="uq_caption_cue_order"),
    )
    op.create_index("ix_caption_cue_track", "caption_cue", ["track_id"])
    op.create_table(
        "caption_export",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("media_asset_id", sa.Text(), nullable=False),
        sa.Column("source_media_asset_id", sa.Text(), nullable=False),
        sa.Column("sequence_id", sa.Text(), nullable=False),
        sa.Column("sequence_purpose", sa.Text(), nullable=False),
        sa.Column("sequence_revision", sa.Integer(), nullable=False),
        sa.Column("sequence_fingerprint", sa.Text(), nullable=False),
        sa.Column("caption_track_id", sa.Text(), nullable=False),
        sa.Column("caption_track_revision", sa.Integer(), nullable=False),
        sa.Column("transcript_analysis_run_id", sa.Text(), nullable=False),
        sa.Column("effective_text_fingerprint", sa.Text(), nullable=False),
        sa.Column("generation_profile", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("format IN ('srt', 'vtt')", name="ck_caption_export_format"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_asset.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_media_asset_id"], ["media_asset.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sequence_id"], ["editorial_sequence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["caption_track_id"], ["caption_track.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_caption_export_sequence", "caption_export", ["sequence_id"])


def downgrade() -> None:
    op.drop_index("ix_caption_export_sequence", table_name="caption_export")
    op.drop_table("caption_export")
    op.drop_index("ix_caption_cue_track", table_name="caption_cue")
    op.drop_table("caption_cue")
    op.drop_index("uq_caption_track_current", table_name="caption_track")
    op.drop_index("ix_caption_track_sequence", table_name="caption_track")
    op.drop_table("caption_track")
