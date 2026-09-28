"""Media probe columns and an explicit proxy source relation.

Revision ID: 0003_media_runtime
Revises: 0002_processing_job
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_media_runtime"
down_revision: Union[str, None] = "0002_processing_job"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("media_asset") as batch:
        batch.add_column(sa.Column("video_duration_us", sa.BigInteger()))
        batch.add_column(sa.Column("audio_duration_us", sa.BigInteger()))
        batch.add_column(sa.Column("duration_source", sa.Text()))
        batch.add_column(sa.Column("sample_rate", sa.Integer()))
        batch.add_column(sa.Column("audio_channels", sa.Integer()))
        batch.add_column(sa.Column("channel_layout", sa.Text()))
        batch.add_column(sa.Column("pixel_format", sa.Text()))
        batch.add_column(sa.Column("r_fps_num", sa.Integer()))
        batch.add_column(sa.Column("r_fps_den", sa.Integer()))
        batch.add_column(sa.Column("time_base_num", sa.Integer()))
        batch.add_column(sa.Column("time_base_den", sa.Integer()))
        batch.add_column(sa.Column("rotation_degrees", sa.Integer()))
        batch.add_column(sa.Column("bit_rate", sa.BigInteger()))
        batch.add_column(sa.Column("video_start_us", sa.BigInteger()))
        batch.add_column(sa.Column("audio_start_us", sa.BigInteger()))
        batch.add_column(sa.Column("file_mtime_ns", sa.BigInteger()))
        batch.add_column(sa.Column("probed_at", sa.Text()))
        batch.add_column(sa.Column("probe_tool", sa.Text()))
        batch.add_column(sa.Column("probe_config", sa.Text()))
        batch.add_column(sa.Column("source_media_asset_id", sa.Text()))
        batch.add_column(sa.Column("proxy_profile", sa.Text()))
        batch.add_column(sa.Column("proxy_tool", sa.Text()))
        batch.add_column(sa.Column("proxy_job_id", sa.Text()))
        batch.add_column(sa.Column("proxy_source_size", sa.BigInteger()))
        batch.add_column(sa.Column("proxy_source_mtime_ns", sa.BigInteger()))
        batch.add_column(sa.Column("proxy_created_at", sa.Text()))
        batch.add_column(sa.Column("timestamp_policy", sa.Text()))
        batch.create_foreign_key(
            "fk_media_asset_source",
            "media_asset",
            ["source_media_asset_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("media_asset") as batch:
        batch.drop_constraint("fk_media_asset_source", type_="foreignkey")
        for name in (
            "timestamp_policy",
            "proxy_created_at",
            "proxy_source_mtime_ns",
            "proxy_source_size",
            "proxy_job_id",
            "proxy_tool",
            "proxy_profile",
            "source_media_asset_id",
            "probe_config",
            "probe_tool",
            "probed_at",
            "file_mtime_ns",
            "audio_start_us",
            "video_start_us",
            "bit_rate",
            "rotation_degrees",
            "time_base_den",
            "time_base_num",
            "r_fps_den",
            "r_fps_num",
            "pixel_format",
            "channel_layout",
            "audio_channels",
            "sample_rate",
            "duration_source",
            "audio_duration_us",
            "video_duration_us",
        ):
            batch.drop_column(name)
