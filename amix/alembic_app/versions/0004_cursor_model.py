"""Selected Cursor Development model id. No tokens and no prompts.

Revision ID: 0004_cursor_model
Revises: 0003_recent_project
Create Date: 2026-10-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_cursor_model"
down_revision: Union[str, None] = "0003_recent_project"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_setting", sa.Column("cursor_model_id", sa.Text()))


def downgrade() -> None:
    op.drop_column("app_setting", "cursor_model_id")
