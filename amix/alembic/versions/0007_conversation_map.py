"""Conversation threads for a conversation_map analysis run.

Revision ID: 0007_conversation_map
Revises: 0006_editorial_sequence
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_conversation_map"
down_revision: Union[str, None] = "0006_editorial_sequence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_thread",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("first_turn_id", sa.Text(), nullable=False),
        sa.Column("last_turn_id", sa.Text(), nullable=False),
        sa.Column("first_word_id", sa.Text(), nullable=False),
        sa.Column("last_word_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("start_us", sa.BigInteger(), nullable=False),
        sa.Column("end_us", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("end_us > start_us", name="ck_conversation_thread_range"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_word_id"], ["word.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_word_id"], ["word.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_run_id", "order_index", name="uq_conversation_thread_order"),
    )
    op.create_index("ix_conversation_thread_run", "conversation_thread", ["analysis_run_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_thread_run", table_name="conversation_thread")
    op.drop_table("conversation_thread")
