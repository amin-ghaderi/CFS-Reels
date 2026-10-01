"""Global application settings. No secrets.

Revision ID: 0001_app_state
Revises:
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_app_state"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("network_policy", sa.Text(), nullable=False),
        sa.Column("selected_speech_id", sa.Text()),
        sa.Column("selected_vision_id", sa.Text()),
        sa.Column("selected_provider_id", sa.Text()),
        sa.Column("ffmpeg_directory", sa.Text()),
        sa.Column("speech_device", sa.Text(), nullable=False),
        sa.Column("speech_compute_type", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_app_setting_singleton"),
    )
    op.create_table(
        "resource_installation",
        sa.Column("resource_id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text()),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("ownership", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("license_name", sa.Text()),
        sa.Column("license_url", sa.Text()),
        sa.Column("identity", sa.Text(), nullable=False),
        sa.Column("runtime", sa.Text()),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("installed_at", sa.Text(), nullable=False),
        sa.Column("validated_at", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_table(
        "provider_configuration",
        sa.Column("provider_id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("placement", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("credential_ref", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "resource_job",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress_bp", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("resource_job")
    op.drop_table("provider_configuration")
    op.drop_table("resource_installation")
    op.drop_table("app_setting")
