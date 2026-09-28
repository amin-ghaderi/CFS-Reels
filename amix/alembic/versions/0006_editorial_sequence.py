"""Editorial sequence and source-order clips.

Revision ID: 0006_editorial_sequence
Revises: 0005_shot_override
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_editorial_sequence"
down_revision: Union[str, None] = "0005_shot_override"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "editorial_sequence",
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
    op.create_index("ix_sequence_clip_sequence", "sequence_clip", ["sequence_id"])


def downgrade() -> None:
    op.drop_index("ix_sequence_clip_sequence", table_name="sequence_clip")
    op.drop_table("sequence_clip")
    op.drop_table("editorial_sequence")
