"""Rename the media producing-job column.

Revision ID: 0009_producing_job
Revises: 0008_reel_discovery
Create Date: 2026-09-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009_producing_job"
down_revision: Union[str, None] = "0008_reel_discovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE media_asset RENAME COLUMN proxy_job_id TO producing_job_id")


def downgrade() -> None:
    op.execute("ALTER TABLE media_asset RENAME COLUMN producing_job_id TO proxy_job_id")
