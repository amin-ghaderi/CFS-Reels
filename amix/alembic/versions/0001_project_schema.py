"""Initial project schema.

Revision ID: 0001_project
Revises:
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_project"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "media_asset",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("project.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("location_kind", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text()),
        sa.Column("external_path", sa.Text()),
        sa.Column("byte_size", sa.BigInteger()),
        sa.Column("content_id", sa.Text()),
        sa.Column("content_id_kind", sa.Text()),
        sa.Column("duration_us", sa.BigInteger()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("fps_num", sa.Integer()),
        sa.Column("fps_den", sa.Integer()),
        sa.Column("container_start_us", sa.BigInteger()),
        sa.Column("container", sa.Text()),
        sa.Column("video_codec", sa.Text()),
        sa.Column("audio_codec", sa.Text()),
    )
    op.create_table(
        "participant",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("project.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "analysis_run",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("project.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("media_asset_id", sa.Text(), sa.ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("algorithm_id", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("window_start_us", sa.BigInteger()),
        sa.Column("window_end_us", sa.BigInteger()),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("id", "media_asset_id", "kind", name="uq_run_asset_kind"),
    )
    op.create_index("ix_analysis_run_asset_kind", "analysis_run", ["media_asset_id", "kind"])
    op.create_table(
        "analysis_dependency",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("depends_on_run_id", sa.Text(), sa.ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False),
        sa.UniqueConstraint("run_id", "depends_on_run_id", name="uq_run_dependency"),
    )
    op.create_table(
        "transcript",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("media_asset_id", sa.Text(), sa.ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("language", sa.Text()),
    )
    op.create_table(
        "word",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("transcript_id", sa.Text(), sa.ForeignKey("transcript.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("segment_ref", sa.Text()),
    )
    op.create_index("ix_word_transcript_sequence", "word", ["transcript_id", "sequence"])
    op.create_table(
        "layout_binding",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("project.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("media_asset_id", sa.Text(), sa.ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("participant_id", sa.Text(), sa.ForeignKey("participant.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("w", sa.Integer(), nullable=False),
        sa.Column("h", sa.Integer(), nullable=False),
    )
    op.create_table(
        "participant_assignment",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("word_id", sa.Text(), sa.ForeignKey("word.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("participant_id", sa.Text(), sa.ForeignKey("participant.id", ondelete="RESTRICT")),
        sa.UniqueConstraint("analysis_run_id", "word_id", name="uq_assignment_word"),
    )
    op.create_table(
        "turn",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("turn_key", sa.Text(), nullable=False),
        sa.Column("participant_id", sa.Text(), sa.ForeignKey("participant.id", ondelete="RESTRICT")),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("analysis_run_id", "turn_key", name="uq_turn_key"),
    )
    op.create_index("ix_turn_run", "turn", ["analysis_run_id"])
    op.create_table(
        "turn_word",
        sa.Column("turn_id", sa.Text(), sa.ForeignKey("turn.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("word_id", sa.Text(), sa.ForeignKey("word.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("turn_id", "sequence", name="uq_turn_word_sequence"),
    )
    op.create_table(
        "overlap_region",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
    )
    op.create_index("ix_overlap_run", "overlap_region", ["analysis_run_id"])
    op.create_table(
        "overlap_participant",
        sa.Column("region_id", sa.Text(), sa.ForeignKey("overlap_region.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("participant_id", sa.Text(), sa.ForeignKey("participant.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
    )
    op.create_table(
        "protected_region",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("media_asset_id", sa.Text(), sa.ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text()),
    )
    op.create_table(
        "shot_plan",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "shot",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("shot_plan_id", sa.Text(), sa.ForeignKey("shot_plan.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.Column("presentation", sa.Text(), nullable=False),
        sa.Column("participant_id", sa.Text(), sa.ForeignKey("participant.id", ondelete="RESTRICT")),
        sa.Column("floor_participant_id", sa.Text(), sa.ForeignKey("participant.id", ondelete="RESTRICT")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.UniqueConstraint("shot_plan_id", "sequence", name="uq_shot_sequence"),
    )
    op.create_table(
        "active_analysis",
        sa.Column("media_asset_id", sa.Text(), sa.ForeignKey("media_asset.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("activated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id", "media_asset_id", "kind"],
            ["analysis_run.id", "analysis_run.media_asset_id", "analysis_run.kind"],
            name="fk_active_run_asset_kind",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "manual_correction",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("project.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("value", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("kind", "target_id", name="uq_correction_target"),
    )


def downgrade() -> None:
    for name in (
        "manual_correction",
        "active_analysis",
        "shot",
        "shot_plan",
        "protected_region",
        "overlap_participant",
        "overlap_region",
        "turn_word",
        "turn",
        "participant_assignment",
        "layout_binding",
        "word",
        "transcript",
        "analysis_dependency",
        "analysis_run",
        "participant",
        "media_asset",
        "project",
    ):
        op.drop_table(name)
