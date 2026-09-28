"""Processing job records.

Revision ID: 0002_processing_job
Revises: 0001_project
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_processing_job"
down_revision: Union[str, None] = "0001_project"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processing_job",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("project.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("media_asset_id", sa.Text(), sa.ForeignKey("media_asset.id", ondelete="RESTRICT")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress_bp", sa.Integer(), nullable=False),
        sa.Column("spec_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("finished_at", sa.Text()),
        sa.Column("cancel_requested", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("resumed_from_job_id", sa.Text(), sa.ForeignKey("processing_job.id", ondelete="RESTRICT")),
        sa.Column("interrupt_reason", sa.Text()),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', "
            "'CANCEL_REQUESTED', 'CANCELLED', 'INTERRUPTED')",
            name="ck_job_status",
        ),
        sa.CheckConstraint("progress_bp >= 0 AND progress_bp <= 10000", name="ck_job_progress"),
        sa.CheckConstraint("cancel_requested IN (0, 1)", name="ck_job_cancel"),
        sa.CheckConstraint("attempt >= 1", name="ck_job_attempt"),
    )
    op.create_index("ix_processing_job_project", "processing_job", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_processing_job_project", table_name="processing_job")
    op.drop_table("processing_job")
