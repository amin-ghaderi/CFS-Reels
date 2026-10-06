"""Dismissed reel suggestions, keyed by source turn range.

Revision ID: 0011_reel_dismissal
Revises: 0010_caption_track
Create Date: 2026-10-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_reel_dismissal"
down_revision: Union[str, None] = "0010_caption_track"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reel_dismissal",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("media_asset_id", sa.Text(), nullable=False),
        sa.Column("first_turn_id", sa.Text(), nullable=False),
        sa.Column("last_turn_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_asset.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_asset_id", "first_turn_id", "last_turn_id", name="uq_reel_dismissal_range"),
    )
    op.create_index("ix_reel_dismissal_asset", "reel_dismissal", ["media_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_reel_dismissal_asset", table_name="reel_dismissal")
    op.drop_table("reel_dismissal")
