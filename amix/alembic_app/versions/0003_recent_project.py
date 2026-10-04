"""Recent projects. Paths only. No analysis and no image bytes.

Revision ID: 0003_recent_project
Revises: 0002_local_semantic
Create Date: 2026-10-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_recent_project"
down_revision: Union[str, None] = "0002_local_semantic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recent_project",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("last_opened_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_recent_project_root_path", "recent_project", ["root_path"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_recent_project_root_path", table_name="recent_project")
    op.drop_table("recent_project")
