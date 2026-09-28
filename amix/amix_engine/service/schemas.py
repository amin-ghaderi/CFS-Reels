"""HTTP schemas. These are not the Phase 2 domain objects."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProjectRequest(_Model):
    path: str
    name: str = Field(min_length=1)


class OpenProjectRequest(_Model):
    path: str
    read_only: bool = False


class CreateJobRequest(_Model):
    kind: str = Field(min_length=1)
    media_asset_id: str | None = None
    spec: dict = Field(default_factory=dict)


class HealthResponse(_Model):
    status: str
    service: str
    version: str


class ProjectResponse(_Model):
    handle: str
    project_id: str
    name: str
    read_only: bool
    schema_revision: str | None


class JobResponse(_Model):
    job_id: str
    project_id: str
    media_asset_id: str | None
    kind: str
    status: str
    progress_bp: int
    spec: dict
    result: dict | None
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    cancel_requested: bool
    attempt: int
    resumed_from_job_id: str | None
    interrupt_reason: str | None


class ErrorBody(_Model):
    code: str
    message: str


class ErrorResponse(_Model):
    error: ErrorBody


class LinkMediaRequest(_Model):
    path: str = Field(min_length=1)
    role: str = "master"


class RelinkMediaRequest(_Model):
    path: str = Field(min_length=1)


class WordTextRequest(_Model):
    text: str = Field(min_length=1, max_length=500)


class MediaResponse(_Model):
    asset_id: str
    role: str
    display_name: str
    location_kind: str
    relative_path: str | None
    external_path: str | None
    byte_size: int | None
    duration_us: int | None
    width: int | None
    height: int | None
    fps_num: int | None
    fps_den: int | None
    status: str


class MediaStatusResponse(_Model):
    asset_id: str
    status: str


class TranscriptResponse(_Model):
    active: bool
    transcript_id: str | None = None
    analysis_run_id: str | None = None
    media_asset_id: str | None = None
    language: str | None = None
    word_count: int | None = None


class TranscriptWordResponse(_Model):
    word_id: str
    sequence: int
    effective_text: str
    machine_text: str
    start_us: int
    end_us: int
    confidence: float | None
    text_corrected: bool
    participant_id: str | None
    participant_name: str | None


class TranscriptWordPage(_Model):
    offset: int
    limit: int
    word_count: int
    words: list[TranscriptWordResponse]
