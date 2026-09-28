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
