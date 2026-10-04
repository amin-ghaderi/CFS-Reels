"""SQLAlchemy metadata for the global application database."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Integer, MetaData, Table, Text
from sqlalchemy.orm import DeclarativeBase


class AppBase(DeclarativeBase):
    metadata = MetaData()


app_setting = Table(
    "app_setting",
    AppBase.metadata,
    Column("id", Integer, primary_key=True),
    Column("network_policy", Text, nullable=False),
    Column("selected_speech_id", Text),
    Column("selected_vision_id", Text),
    Column("selected_provider_id", Text),
    Column("ffmpeg_directory", Text),
    Column("speech_device", Text, nullable=False),
    Column("speech_compute_type", Text, nullable=False),
    Column("semantic_source", Text),
    Column("selected_llama_runtime_id", Text),
    Column("selected_gguf_model_id", Text),
    Column("local_context_size", Integer),
    Column("local_threads", Integer),
    CheckConstraint("id = 1", name="ck_app_setting_singleton"),
)

resource_installation = Table(
    "resource_installation",
    AppBase.metadata,
    Column("resource_id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("version", Text),
    Column("local_path", Text, nullable=False),
    Column("ownership", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("license_name", Text),
    Column("license_url", Text),
    Column("identity", Text, nullable=False),
    Column("runtime", Text),
    Column("byte_size", Integer),
    Column("installed_at", Text, nullable=False),
    Column("validated_at", Text),
    Column("status", Text, nullable=False),
    Column("architecture", Text),
    Column("semantic_compatibility", Text),
)

provider_configuration = Table(
    "provider_configuration",
    AppBase.metadata,
    Column("provider_id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("placement", Text, nullable=False),
    Column("base_url", Text, nullable=False),
    Column("model_id", Text, nullable=False),
    Column("credential_ref", Text),
    Column("created_at", Text, nullable=False),
)

recent_project = Table(
    "recent_project",
    AppBase.metadata,
    Column("project_id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("root_path", Text, nullable=False),
    Column("last_opened_at", Text, nullable=False),
)

resource_job = Table(
    "resource_job",
    AppBase.metadata,
    Column("job_id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("progress_bp", Integer, nullable=False),
    Column("resource_id", Text),
    Column("error_code", Text),
    Column("error_message", Text),
    Column("created_at", Text, nullable=False),
    Column("finished_at", Text),
)
