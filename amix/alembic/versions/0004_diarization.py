"""Anonymous diarization segments for one analysis run.

Revision ID: 0004_diarization
Revises: 0003_media_runtime
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_diarization"
down_revision: Union[str, None] = "0003_media_runtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diarization_segment",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("cluster_key", sa.Text(), nullable=False),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_run.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_run_id", "sequence", name="uq_diarization_sequence"),
    )
    op.create_index("ix_diarization_segment_run", "diarization_segment", ["analysis_run_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_diarization_segment_run", table_name="diarization_segment")
    op.drop_table("diarization_segment")
