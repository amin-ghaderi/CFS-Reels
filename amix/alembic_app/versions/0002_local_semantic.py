"""Local semantic runtime selection. No secrets and no server ports.

Revision ID: 0002_local_semantic
Revises: 0001_app_state
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_local_semantic"
down_revision: Union[str, None] = "0001_app_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_setting", sa.Column("semantic_source", sa.Text()))
    op.add_column("app_setting", sa.Column("selected_llama_runtime_id", sa.Text()))
    op.add_column("app_setting", sa.Column("selected_gguf_model_id", sa.Text()))
    op.add_column("app_setting", sa.Column("local_context_size", sa.Integer()))
    op.add_column("app_setting", sa.Column("local_threads", sa.Integer()))
    op.add_column("resource_installation", sa.Column("architecture", sa.Text()))
    op.add_column("resource_installation", sa.Column("semantic_compatibility", sa.Text()))


def downgrade() -> None:
    op.drop_column("resource_installation", "semantic_compatibility")
    op.drop_column("resource_installation", "architecture")
    op.drop_column("app_setting", "local_threads")
    op.drop_column("app_setting", "local_context_size")
    op.drop_column("app_setting", "selected_gguf_model_id")
    op.drop_column("app_setting", "selected_llama_runtime_id")
    op.drop_column("app_setting", "semantic_source")
