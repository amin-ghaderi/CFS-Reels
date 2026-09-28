"""Processing-job rows. Progress is integer basis points, not a media time."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from amix.amix_engine.storage.errors import (
    InvalidJobState,
    JobSpecRejected,
    ProjectDatabaseInvalid,
    UnknownJob,
)
from amix.amix_engine.storage.models import MediaAssetRow, ProcessingJobRow

QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
CANCELLED = "CANCELLED"
INTERRUPTED = "INTERRUPTED"

TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED, INTERRUPTED})
STALE_ON_OPEN = frozenset({QUEUED, RUNNING, CANCEL_REQUESTED})

_TRANSITIONS = {
    QUEUED: frozenset({RUNNING, CANCELLED, INTERRUPTED}),
    RUNNING: frozenset({SUCCEEDED, FAILED, CANCEL_REQUESTED, INTERRUPTED}),
    CANCEL_REQUESTED: frozenset({CANCELLED, FAILED, INTERRUPTED}),
    SUCCEEDED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    INTERRUPTED: frozenset(),
}

_SECRET_KEYS = frozenset({
    "authorization",
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "credential",
})

INTERRUPT_REASON = "previous_engine_session_ended"
RETRYABLE = frozenset({FAILED, INTERRUPTED, CANCELLED})


@dataclass(frozen=True)
class StoredJob:
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


def reject_secret_spec(spec: dict) -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in _SECRET_KEYS:
                    raise JobSpecRejected("job spec contains a field that must not be stored")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(spec)


def create_job(
    session: Session,
    *,
    project_id: str,
    kind: str,
    spec: dict,
    media_asset_id: str | None = None,
    attempt: int = 1,
    resumed_from_job_id: str | None = None,
) -> StoredJob:
    reject_secret_spec(spec)
    if media_asset_id is not None:
        asset = session.get(MediaAssetRow, media_asset_id)
        if asset is None or asset.project_id != project_id:
            raise ProjectDatabaseInvalid(f"unknown media asset {media_asset_id}")
    if resumed_from_job_id is not None and session.get(ProcessingJobRow, resumed_from_job_id) is None:
        raise UnknownJob(resumed_from_job_id)
    row = ProcessingJobRow(
        id=str(uuid.uuid4()),
        project_id=project_id,
        media_asset_id=media_asset_id,
        kind=kind,
        status=QUEUED,
        progress_bp=0,
        spec_json=json.dumps(spec, sort_keys=True),
        created_at=_now(),
        cancel_requested=0,
        attempt=attempt,
        resumed_from_job_id=resumed_from_job_id,
    )
    session.add(row)
    session.flush()
    return _view(row)


def get_job(session: Session, job_id: str, project_id: str) -> StoredJob:
    return _view(_row(session, job_id, project_id))


def list_jobs(session: Session, project_id: str) -> list[StoredJob]:
    rows = session.scalars(
        select(ProcessingJobRow)
        .where(ProcessingJobRow.project_id == project_id)
        .order_by(ProcessingJobRow.created_at, ProcessingJobRow.id)
    ).all()
    return [_view(row) for row in rows]


def transition(session: Session, job_id: str, project_id: str, status: str, **fields: object) -> StoredJob:
    row = _row(session, job_id, project_id)
    allowed = _TRANSITIONS.get(row.status, frozenset())
    if status not in allowed:
        raise InvalidJobState(f"cannot move job from {row.status} to {status}")
    row.status = status
    for name, value in fields.items():
        setattr(row, name, value)
    if status in TERMINAL and row.finished_at is None:
        row.finished_at = _now()
    session.flush()
    return _view(row)


def set_progress(session: Session, job_id: str, project_id: str, progress_bp: int) -> StoredJob:
    if not isinstance(progress_bp, int) or isinstance(progress_bp, bool):
        raise InvalidJobState("progress must be an integer basis-point value")
    if progress_bp < 0 or progress_bp > 10000:
        raise InvalidJobState("progress is outside 0..10000")
    row = _row(session, job_id, project_id)
    if row.status in TERMINAL:
        raise InvalidJobState(f"job is already {row.status}")
    if progress_bp < row.progress_bp:
        raise InvalidJobState("progress cannot decrease")
    row.progress_bp = progress_bp
    session.flush()
    return _view(row)


def interrupt_stale(session: Session, project_id: str) -> int:
    rows = session.scalars(
        select(ProcessingJobRow).where(
            ProcessingJobRow.project_id == project_id,
            ProcessingJobRow.status.in_(tuple(STALE_ON_OPEN)),
        )
    ).all()
    now = _now()
    for row in rows:
        row.status = INTERRUPTED
        row.interrupt_reason = INTERRUPT_REASON
        row.finished_at = now
    session.flush()
    return len(rows)


def _row(session: Session, job_id: str, project_id: str) -> ProcessingJobRow:
    row = session.get(ProcessingJobRow, job_id)
    if row is None or row.project_id != project_id:
        raise UnknownJob(job_id)
    return row


def _view(row: ProcessingJobRow) -> StoredJob:
    return StoredJob(
        job_id=row.id,
        project_id=row.project_id,
        media_asset_id=row.media_asset_id,
        kind=row.kind,
        status=row.status,
        progress_bp=row.progress_bp,
        spec=json.loads(row.spec_json),
        result=None if row.result_json is None else json.loads(row.result_json),
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        cancel_requested=bool(row.cancel_requested),
        attempt=row.attempt,
        resumed_from_job_id=row.resumed_from_job_id,
        interrupt_reason=row.interrupt_reason,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
