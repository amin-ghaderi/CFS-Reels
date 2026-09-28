"""Manual camera overrides for one automatic shot plan.

Revision ID: 0005_shot_override
Revises: 0004_diarization
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_shot_override"
down_revision: Union[str, None] = "0004_diarization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shot_override",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("media_asset_id", sa.Text(), nullable=False),
        sa.Column("shot_plan_run_id", sa.Text(), nullable=False),
        sa.Column("shot_id", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("participant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(decision = 'wide' AND participant_id IS NULL) OR (decision = 'full' AND participant_id IS NOT NULL)",
            name="ck_shot_override_decision",
        ),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_asset.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shot_plan_run_id"], ["analysis_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shot_id"], ["shot.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["participant_id"], ["participant.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shot_plan_run_id", "shot_id", name="uq_shot_override_shot"),
    )
    op.create_index("ix_shot_override_plan", "shot_override", ["shot_plan_run_id"])


def downgrade() -> None:
    op.drop_index("ix_shot_override_plan", table_name="shot_override")
    op.drop_table("shot_override")
