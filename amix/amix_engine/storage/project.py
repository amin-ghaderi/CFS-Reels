"""Per-project directory, write lock, and SQLite store.

The engine owns this database. Callers pass domain values in and get domain
values out. There is no repository class per table.

Identities are UUID strings, except participant ids and word ids, which the
caller supplies so they stay stable across export. Display names are not part
of those ids.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from amix.amix_engine import __version__
from amix.amix_engine.domain.types import (
    DiarizationSegment,
    LayoutBinding,
    OverlapRegion,
    ParticipantId,
    Presentation,
    ProtectedRegion,
    Shot,
    ShotPlan,
    SpeakerAssignment,
    Turn,
    Word,
)
from amix.amix_engine.storage.database import create_project_engine
from amix.amix_engine.storage.errors import (
    InvalidJobState,
    MediaMissing,
    NoActiveTranscript,
    ProjectDatabaseInvalid,
    SchemaMismatch,
)
from amix.amix_engine.storage.jobs import (
    CANCEL_REQUESTED,
    CANCELLED,
    FAILED,
    INTERRUPTED,
    QUEUED,
    RETRYABLE,
    RUNNING,
    SUCCEEDED,
    StoredJob,
    create_job,
    get_job,
    interrupt_stale,
    list_jobs,
    set_progress,
    transition,
)
from amix.amix_engine.storage.kinds import (
    ANALYSIS_KINDS,
    CONVERSATION_MAP,
    DIARIZATION,
    OVERLAP,
    PARTICIPANT_ASSIGNMENT,
    REEL_DISCOVERY,
    SHOT_PLAN,
    SPEAKER_OVERRIDE,
    TURNS,
    WORD_TEXT,
)
from amix.amix_engine.storage.lock import ProjectWriteLock
from amix.amix_engine.storage.migrate import current_revision, head_revision, upgrade_database
from amix.amix_engine.storage.models import (
    ActiveAnalysisRow,
    AnalysisDependencyRow,
    AnalysisRunRow,
    ConversationThreadRow,
    ReelCandidateRow,
    DiarizationSegmentRow,
    LayoutBindingRow,
    ManualCorrectionRow,
    MediaAssetRow,
    OverlapParticipantRow,
    OverlapRegionRow,
    ParticipantRow,
    ProjectRow,
    ProtectedRegionRow,
    ShotPlanRow,
    EditorialSequenceRow,
    SequenceClipRow,
    ShotOverrideRow,
    ShotRow,
    SpeakerAssignmentRow,
    TranscriptRow,
    TurnRow,
    TurnWordRow,
    WordRow,
)
from amix.amix_engine.time.clock import TimeRange

DATABASE_NAME = "project.sqlite"
# Application format marker. Alembic revision is the schema, not this number.
PROJECT_SCHEMA_VERSION = 1
INTERNAL_DIR = ".amix"
_INTERNAL_FOLDERS = ("media", "proxy", "cache", "artifacts", "logs")
_PRIVATE_PREFIXES = ("proxy/", "media/", "cache/", "artifacts/", "logs/", ".stt/", ".diarize/", ".overlap/")


def database_file(user_root: str | Path) -> Path:
    """The project database. New projects keep it under ``.amix``.

    A database already at the folder the user chose is the previous layout
    and stays there. Two database files in one project are refused.
    """
    root = Path(user_root)
    modern = root / INTERNAL_DIR / DATABASE_NAME
    previous = root / DATABASE_NAME
    if modern.is_file() and previous.is_file():
        raise ProjectDatabaseInvalid("project database is duplicated")
    if modern.is_file():
        return modern
    if previous.is_file():
        return previous
    return modern


def private_directory(user_root: str | Path) -> Path:
    """Directory that holds the database, cache, proxy, and lock."""
    return database_file(user_root).parent


def manifest_identity(user_root: str | Path) -> tuple[str, str]:
    """Project id and display name from the manifest beside the database.

    This does not acquire the project lock and does not open the database.
    """
    root = Path(user_root)
    database = database_file(root)
    if not database.is_file():
        raise ProjectDatabaseInvalid(f"missing project database: {database}")
    manifest_path = database.parent / "manifest.json"
    if not manifest_path.is_file():
        raise ProjectDatabaseInvalid(f"missing manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectDatabaseInvalid(f"manifest is not readable: {manifest_path}") from exc
    project_id = manifest.get("project_id")
    name = manifest.get("name")
    if not isinstance(project_id, str) or not project_id:
        raise ProjectDatabaseInvalid("manifest has no project id")
    display_name = name.strip() if isinstance(name, str) else ""
    return project_id, display_name or "Project"


def poster_file(user_root: str | Path) -> Path | None:
    """Existing poster still, if the project folder has one. Never creates it."""
    root = Path(user_root)
    if not root.is_dir():
        return None
    try:
        database = database_file(root)
    except ProjectDatabaseInvalid:
        return None
    if not database.is_file():
        return None
    poster = (database.parent / "cache" / "poster.jpg").resolve()
    cache = (database.parent / "cache").resolve()
    if poster.parent != cache:
        return None
    if not poster.is_file() or poster.stat().st_size <= 0:
        return None
    return poster


def create_project(path: str | Path, name: str) -> ProjectStore:
    root = Path(path)
    modern = root / INTERNAL_DIR / DATABASE_NAME
    previous = root / DATABASE_NAME
    if modern.exists() or previous.exists():
        raise ProjectDatabaseInvalid(f"project database already exists: {modern}")
    root.mkdir(parents=True, exist_ok=True)
    private = root / INTERNAL_DIR
    private.mkdir(exist_ok=True)
    for folder in _INTERNAL_FOLDERS:
        (private / folder).mkdir(exist_ok=True)
    (root / "exports").mkdir(exist_ok=True)
    lock = ProjectWriteLock(private)
    lock.acquire()
    store: ProjectStore | None = None
    try:
        upgrade_database(modern)
        store = ProjectStore(root, lock=lock, read_only=False)
        store._insert_project(name)
        return store
    except Exception:
        if store is not None:
            store._engine.dispose()
        lock.release()
        raise


def open_project(path: str | Path, *, read_only: bool = False) -> ProjectStore:
    root = Path(path)
    database = database_file(root)
    if not database.is_file():
        raise ProjectDatabaseInvalid(f"missing project database: {database}")
    private = database.parent
    lock = None
    if read_only:
        revision = current_revision(database)
        if revision != head_revision():
            raise SchemaMismatch(
                f"database revision {revision!r} is not {head_revision()!r}; "
                "open the project for write to migrate"
            )
    else:
        lock = ProjectWriteLock(private)
        lock.acquire()
        try:
            upgrade_database(database)
        except Exception:
            lock.release()
            raise
    store = ProjectStore(root, lock=lock, read_only=read_only)
    try:
        store._load_identity()
        if not read_only:
            store.interrupt_stale_jobs()
    except Exception:
        store.close()
        raise
    return store


@dataclass(frozen=True)
class StoredMedia:
    asset_id: str
    role: str
    display_name: str
    location_kind: str
    relative_path: str | None
    external_path: str | None
    byte_size: int | None
    content_id: str | None
    duration_us: int | None
    width: int | None
    height: int | None
    fps_num: int | None
    fps_den: int | None
    container_start_us: int | None
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    video_duration_us: int | None = None
    audio_duration_us: int | None = None
    duration_source: str | None = None
    sample_rate: int | None = None
    audio_channels: int | None = None
    channel_layout: str | None = None
    pixel_format: str | None = None
    r_fps_num: int | None = None
    r_fps_den: int | None = None
    time_base_num: int | None = None
    time_base_den: int | None = None
    rotation_degrees: int | None = None
    bit_rate: int | None = None
    video_start_us: int | None = None
    audio_start_us: int | None = None
    file_mtime_ns: int | None = None
    probed_at: str | None = None
    probe_tool: str | None = None
    probe_config: str | None = None
    source_media_asset_id: str | None = None
    proxy_profile: str | None = None
    proxy_tool: str | None = None
    producing_job_id: str | None = None
    proxy_source_size: int | None = None
    proxy_source_mtime_ns: int | None = None
    proxy_created_at: str | None = None
    timestamp_policy: str | None = None


@dataclass(frozen=True)
class MediaProbeRecord:
    """Canonical probe fields written onto an existing asset."""

    container: str | None
    duration_us: int | None
    duration_source: str | None
    container_start_us: int | None
    bit_rate: int | None
    video_codec: str | None
    width: int | None
    height: int | None
    pixel_format: str | None
    fps_num: int | None
    fps_den: int | None
    r_fps_num: int | None
    r_fps_den: int | None
    time_base_num: int | None
    time_base_den: int | None
    video_start_us: int | None
    video_duration_us: int | None
    rotation_degrees: int | None
    audio_codec: str | None
    sample_rate: int | None
    audio_channels: int | None
    channel_layout: str | None
    audio_start_us: int | None
    audio_duration_us: int | None
    byte_size: int
    file_mtime_ns: int
    probe_tool: str
    probe_config: str


@dataclass(frozen=True)
class StoredWord:
    word_id: str
    sequence: int
    machine_text: str
    effective_text: str
    start_us: int
    end_us: int
    confidence: float | None
    segment_ref: str | None = None


@dataclass(frozen=True)
class ActiveTranscript:
    transcript_id: str
    analysis_run_id: str
    media_asset_id: str
    language: str | None
    word_count: int


@dataclass(frozen=True)
class WordHit:
    """Active-transcript word that contains one canonical source time. No text."""

    word_id: str
    sequence: int
    start_us: int
    end_us: int


@dataclass(frozen=True)
class TranscriptWordView:
    word_id: str
    sequence: int
    machine_text: str
    effective_text: str
    start_us: int
    end_us: int
    confidence: float | None
    text_corrected: bool
    participant_id: str | None
    participant_name: str | None


class ProjectStore:
    def __init__(self, root: Path, *, lock: ProjectWriteLock | None, read_only: bool) -> None:
        self.root = root.resolve()
        self.private = private_directory(self.root)
        self.read_only = read_only
        self._lock = lock
        self._engine = create_project_engine(self.private / DATABASE_NAME, read_only=read_only)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)
        self.project_id = ""
        self.project_name = ""

    def close(self) -> None:
        self._engine.dispose()
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    def _session(self) -> Session:
        return self._sessions()

    def _require_write(self) -> None:
        if self.read_only:
            raise ProjectDatabaseInvalid("project is open read-only")

    def _insert_project(self, name: str) -> None:
        self._require_write()
        project_id = str(uuid.uuid4())
        created_at = _now()
        with self._session() as session:
            session.add(ProjectRow(id=project_id, name=name, created_at=created_at))
            session.commit()
        manifest = {
            "project_id": project_id,
            "name": name,
            "created_at": created_at,
            "project_schema_version": PROJECT_SCHEMA_VERSION,
            "created_by": f"amix {__version__}",
        }
        (self.private / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        self.project_id = project_id
        self.project_name = name

    def _load_identity(self) -> None:
        manifest_path = self.private / "manifest.json"
        if not manifest_path.is_file():
            raise ProjectDatabaseInvalid(f"missing manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = manifest.get("project_schema_version")
        if version is None:
            raise ProjectDatabaseInvalid("manifest has no project_schema_version")
        if version != PROJECT_SCHEMA_VERSION:
            raise SchemaMismatch(
                f"project format {version} is not supported (this engine writes {PROJECT_SCHEMA_VERSION})"
            )
        with self._session() as session:
            row = session.get(ProjectRow, manifest["project_id"])
            if row is None:
                raise ProjectDatabaseInvalid("manifest project id is not in the database")
            self.project_id = row.id
            self.project_name = row.name

    def pragma(self, name: str) -> str:
        allowed = {"foreign_keys", "journal_mode", "synchronous", "query_only"}
        if name not in allowed:
            raise ValueError(f"unsupported pragma: {name}")
        with self._engine.connect() as connection:
            value = connection.execute(text(f"PRAGMA {name}")).scalar()
        return str(value)

    def schema_sql(self) -> list[str]:
        with self._engine.connect() as connection:
            rows = connection.execute(text("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
            return [row[0] for row in rows]

    def alembic_revision(self) -> str | None:
        return current_revision(self.private / DATABASE_NAME)

    def list_media_assets(self) -> list[StoredMedia]:
        with self._session() as session:
            rows = session.scalars(
                select(MediaAssetRow)
                .where(MediaAssetRow.project_id == self.project_id)
                .order_by(MediaAssetRow.display_name, MediaAssetRow.id)
            ).all()
            return [_media(row) for row in rows]

    def list_active_analyses(self) -> list[tuple[str, str, str]]:
        with self._session() as session:
            rows = session.scalars(select(ActiveAnalysisRow)).all()
            return [(row.media_asset_id, row.kind, row.analysis_run_id) for row in rows]

    def count_analysis_runs(self) -> int:
        with self._session() as session:
            return int(session.scalar(select(func.count()).select_from(AnalysisRunRow)) or 0)

    def create_processing_job(
        self,
        *,
        kind: str,
        spec: dict | None = None,
        media_asset_id: str | None = None,
        attempt: int = 1,
        resumed_from_job_id: str | None = None,
    ) -> StoredJob:
        self._require_write()
        with self._session() as session:
            job = create_job(
                session,
                project_id=self.project_id,
                kind=kind,
                spec=spec or {},
                media_asset_id=media_asset_id,
                attempt=attempt,
                resumed_from_job_id=resumed_from_job_id,
            )
            session.commit()
            return job

    def get_processing_job(self, job_id: str) -> StoredJob:
        with self._session() as session:
            return get_job(session, job_id, self.project_id)

    def list_processing_jobs(self) -> list[StoredJob]:
        with self._session() as session:
            return list_jobs(session, self.project_id)

    def start_processing_job(self, job_id: str) -> bool:
        self._require_write()
        with self._session() as session:
            try:
                transition(
                    session,
                    job_id,
                    self.project_id,
                    RUNNING,
                    started_at=_now(),
                )
            except InvalidJobState:
                session.rollback()
                return False
            session.commit()
            return True

    def set_job_progress(self, job_id: str, progress_bp: int) -> StoredJob:
        self._require_write()
        with self._session() as session:
            job = set_progress(session, job_id, self.project_id, progress_bp)
            session.commit()
            return job

    def request_job_cancel(self, job_id: str) -> StoredJob:
        """Queue cancels immediately. A running job becomes CANCEL_REQUESTED."""
        self._require_write()
        with self._session() as session:
            current = get_job(session, job_id, self.project_id)
            if current.status == QUEUED:
                job = transition(
                    session,
                    job_id,
                    self.project_id,
                    CANCELLED,
                    cancel_requested=1,
                )
            elif current.status in {RUNNING, CANCEL_REQUESTED}:
                if current.status == RUNNING:
                    job = transition(
                        session,
                        job_id,
                        self.project_id,
                        CANCEL_REQUESTED,
                        cancel_requested=1,
                    )
                else:
                    row_job = current
                    job = row_job
            else:
                raise InvalidJobState(f"cannot cancel a job that is {current.status}")
            session.commit()
            return job

    def finish_job_succeeded(self, job_id: str, result: dict, *, committed: bool = False) -> StoredJob:
        self._require_write()
        with self._session() as session:
            current = get_job(session, job_id, self.project_id)
            allowed = {RUNNING, CANCEL_REQUESTED} if committed else {RUNNING}
            if current.status not in allowed:
                raise InvalidJobState(f"cannot complete a job that is {current.status}")
            if current.progress_bp < 10000:
                set_progress(session, job_id, self.project_id, 10000)
            job = transition(
                session,
                job_id,
                self.project_id,
                SUCCEEDED,
                result_json=json.dumps(result, sort_keys=True),
            )
            session.commit()
            return job

    def finish_job_failed(self, job_id: str, error_code: str, error_message: str) -> StoredJob:
        self._require_write()
        with self._session() as session:
            job = transition(
                session,
                job_id,
                self.project_id,
                FAILED,
                error_code=error_code,
                error_message=error_message[:500],
            )
            session.commit()
            return job

    def finish_job_cancelled(self, job_id: str) -> StoredJob:
        self._require_write()
        with self._session() as session:
            current = get_job(session, job_id, self.project_id)
            if current.status == CANCELLED:
                return current
            if current.status == RUNNING:
                transition(
                    session,
                    job_id,
                    self.project_id,
                    CANCEL_REQUESTED,
                    cancel_requested=1,
                )
            elif current.status not in {QUEUED, CANCEL_REQUESTED}:
                raise InvalidJobState(f"cannot cancel a job that is {current.status}")
            job = transition(
                session,
                job_id,
                self.project_id,
                CANCELLED,
                cancel_requested=1,
            )
            session.commit()
            return job

    def retry_processing_job(self, job_id: str) -> StoredJob:
        """New attempt from the stored spec. This is not a checkpoint resume."""
        self._require_write()
        with self._session() as session:
            previous = get_job(session, job_id, self.project_id)
            if previous.status not in RETRYABLE:
                raise InvalidJobState(f"cannot retry a job that is {previous.status}")
            job = create_job(
                session,
                project_id=self.project_id,
                kind=previous.kind,
                spec=previous.spec,
                media_asset_id=previous.media_asset_id,
                attempt=previous.attempt + 1,
                resumed_from_job_id=previous.job_id,
            )
            session.commit()
            return job

    def interrupt_stale_jobs(self) -> int:
        self._require_write()
        with self._session() as session:
            count = interrupt_stale(session, self.project_id)
            session.commit()
            return count

    def add_participant(self, participant_id: str, display_name: str, *, sort_order: int = 0) -> str:
        self._require_write()
        with self._session() as session:
            session.add(ParticipantRow(
                id=participant_id,
                project_id=self.project_id,
                display_name=display_name,
                sort_order=sort_order,
            ))
            session.commit()
        return participant_id

    def list_participants(self) -> list[tuple[str, str, int]]:
        with self._session() as session:
            rows = session.scalars(
                select(ParticipantRow)
                .where(ParticipantRow.project_id == self.project_id)
                .order_by(ParticipantRow.sort_order, ParticipantRow.display_name, ParticipantRow.id)
            ).all()
            return [(row.id, row.display_name, int(row.sort_order)) for row in rows]

    def rename_participant(self, participant_id: str, display_name: str) -> None:
        self._require_write()
        with self._session() as session:
            row = session.get(ParticipantRow, participant_id)
            if row is None or row.project_id != self.project_id:
                raise ProjectDatabaseInvalid(f"unknown participant {participant_id}")
            row.display_name = display_name
            session.commit()

    def add_media_asset(
        self,
        *,
        display_name: str,
        role: str = "master",
        location_kind: str,
        relative_path: str | None = None,
        external_path: str | None = None,
        byte_size: int | None = None,
        content_id: str | None = None,
        content_id_kind: str | None = None,
        duration_us: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps_num: int | None = None,
        fps_den: int | None = None,
        container_start_us: int | None = None,
        container: str | None = None,
        video_codec: str | None = None,
        audio_codec: str | None = None,
        file_mtime_ns: int | None = None,
        asset_id: str | None = None,
    ) -> str:
        self._require_write()
        if location_kind not in {"project", "external"}:
            raise ValueError("location_kind must be 'project' or 'external'")
        if location_kind == "project" and not relative_path:
            raise ValueError("project media needs a relative path")
        if location_kind == "external" and not external_path:
            raise ValueError("external media needs a path")
        asset_id = asset_id or str(uuid.uuid4())
        with self._session() as session:
            session.add(MediaAssetRow(
                id=asset_id,
                project_id=self.project_id,
                role=role,
                display_name=display_name,
                location_kind=location_kind,
                relative_path=relative_path.replace("\\", "/") if relative_path else None,
                external_path=external_path,
                byte_size=byte_size,
                content_id=content_id,
                content_id_kind=content_id_kind,
                duration_us=duration_us,
                width=width,
                height=height,
                fps_num=fps_num,
                fps_den=fps_den,
                container_start_us=container_start_us,
                container=container,
                video_codec=video_codec,
                audio_codec=audio_codec,
                file_mtime_ns=file_mtime_ns,
            ))
            session.commit()
        return asset_id

    def get_media(self, asset_id: str) -> StoredMedia:
        with self._session() as session:
            row = self._asset(session, asset_id)
            return _media(row)

    def relink_media(
        self,
        asset_id: str,
        *,
        relative_path: str | None = None,
        external_path: str | None = None,
    ) -> None:
        """Update the file location only. Analysis rows are not rewritten."""
        self._require_write()
        with self._session() as session:
            row = self._asset(session, asset_id)
            if relative_path is not None:
                row.location_kind = "project"
                row.relative_path = relative_path.replace("\\", "/")
            if external_path is not None:
                row.location_kind = "external"
                row.external_path = external_path
            session.commit()

    def project_file(self, relative: str) -> Path:
        """Resolve a stored project-relative path.

        Proxy, cache, and similar internal files live under the private
        directory. Exports stay in the folder the user chose. When the
        database itself is in that folder, both locations are the same.
        """
        text = (relative or "").replace("\\", "/")
        if text == "proxy" or text.startswith(_PRIVATE_PREFIXES):
            return self.private / text
        return self.root / text

    def resolve_media(self, asset_id: str) -> Path:
        with self._session() as session:
            row = self._asset(session, asset_id)
            if row.location_kind == "project":
                return self.project_file(row.relative_path or "")
            return Path(row.external_path or "")

    def media_status(self, asset_id: str) -> str:
        path = self.resolve_media(asset_id)
        return "present" if path.is_file() else "missing"

    def relink_external(
        self,
        asset_id: str,
        external_path: str,
        *,
        byte_size: int,
        display_name: str,
        file_mtime_ns: int | None = None,
    ) -> StoredMedia:
        """Point the same asset at a new external file. Analysis rows stay put."""
        self._require_write()
        with self._session() as session:
            row = self._asset(session, asset_id)
            row.location_kind = "external"
            row.external_path = external_path
            row.relative_path = None
            row.byte_size = byte_size
            row.display_name = display_name
            row.file_mtime_ns = file_mtime_ns
            _clear_probe(row)
            session.commit()
            session.refresh(row)
            return _media(row)

    def apply_probe(self, asset_id: str, record: MediaProbeRecord) -> StoredMedia:
        """Write probe metadata onto the same asset. This does not add a row."""
        self._require_write()
        with self._session() as session:
            row = self._asset(session, asset_id)
            _write_probe(row, record)
            session.commit()
            session.refresh(row)
            return _media(row)

    def find_proxy(self, source_asset_id: str) -> StoredMedia | None:
        with self._session() as session:
            row = session.scalar(
                select(MediaAssetRow)
                .where(
                    MediaAssetRow.source_media_asset_id == source_asset_id,
                    MediaAssetRow.role == "proxy",
                    MediaAssetRow.project_id == self.project_id,
                )
                .order_by(MediaAssetRow.proxy_created_at.desc())
            )
            return None if row is None else _media(row)

    def publish_proxy(
        self,
        source_asset_id: str,
        record: MediaProbeRecord,
        *,
        relative_path: str,
        display_name: str,
        profile: str,
        proxy_tool: str,
        job_id: str,
        source_size: int,
        source_mtime_ns: int,
        timestamp_policy: str,
    ) -> StoredMedia:
        """Create or update the one proxy row for this source. The file must already exist."""
        self._require_write()
        with self._session() as session:
            self._asset(session, source_asset_id)
            row = session.scalar(
                select(MediaAssetRow).where(
                    MediaAssetRow.source_media_asset_id == source_asset_id,
                    MediaAssetRow.role == "proxy",
                    MediaAssetRow.project_id == self.project_id,
                )
            )
            if row is None:
                row = MediaAssetRow(
                    id=str(uuid.uuid4()),
                    project_id=self.project_id,
                    role="proxy",
                    display_name=display_name,
                    location_kind="project",
                    source_media_asset_id=source_asset_id,
                )
                session.add(row)
            row.display_name = display_name
            row.location_kind = "project"
            row.relative_path = relative_path.replace("\\", "/")
            row.external_path = None
            row.source_media_asset_id = source_asset_id
            row.proxy_profile = profile
            row.proxy_tool = proxy_tool
            row.producing_job_id = job_id
            row.proxy_source_size = source_size
            row.proxy_source_mtime_ns = source_mtime_ns
            row.proxy_created_at = _now()
            row.timestamp_policy = timestamp_policy
            _write_probe(row, record)
            session.commit()
            session.refresh(row)
            return _media(row)

    def clean_proxy_tmp(self, keep_name: str | None = None) -> None:
        """Remove interrupted proxy fragments. A published proxy file is not in this directory."""
        folder = self.private / "proxy" / ".tmp"
        if not folder.is_dir():
            return
        for item in folder.iterdir():
            if item.is_file() and item.name != keep_name:
                item.unlink()

    def observed_file(self, asset_id: str) -> tuple[int | None, int | None]:
        path = self.resolve_media(asset_id)
        if not path.is_file():
            return None, None
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns

    def require_media(self, asset_id: str) -> Path:
        path = self.resolve_media(asset_id)
        if not path.is_file():
            raise MediaMissing(str(path))
        return path

    def add_layout_binding(self, asset_id: str, binding: LayoutBinding) -> str:
        self._require_write()
        binding_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(LayoutBindingRow(
                id=binding_id,
                project_id=self.project_id,
                media_asset_id=asset_id,
                participant_id=binding.participant_id.value,
                start_us=binding.span.start_us,
                end_us=binding.span.end_us,
                x=binding.x,
                y=binding.y,
                w=binding.w,
                h=binding.h,
            ))
            session.commit()
        return binding_id

    def update_layout_binding(self, asset_id: str, binding_id: str, binding: LayoutBinding) -> None:
        """Replace one saved rectangle. The binding id stays the same."""
        self._require_write()
        with self._session() as session:
            self._asset(session, asset_id)
            row = session.get(LayoutBindingRow, binding_id)
            if row is None or row.media_asset_id != asset_id or row.project_id != self.project_id:
                raise ProjectDatabaseInvalid(f"unknown layout {binding_id}")
            row.participant_id = binding.participant_id.value
            row.start_us = binding.span.start_us
            row.end_us = binding.span.end_us
            row.x = binding.x
            row.y = binding.y
            row.w = binding.w
            row.h = binding.h
            session.commit()

    def load_layout_bindings(self, asset_id: str) -> list[LayoutBinding]:
        with self._session() as session:
            rows = session.scalars(
                select(LayoutBindingRow)
                .where(LayoutBindingRow.media_asset_id == asset_id)
                .order_by(LayoutBindingRow.start_us)
            ).all()
            return [
                LayoutBinding(
                    ParticipantId(row.participant_id),
                    row.x, row.y, row.w, row.h,
                    TimeRange(row.start_us, row.end_us),
                )
                for row in rows
            ]

    def list_layout_records(self, asset_id: str) -> list[dict]:
        with self._session() as session:
            self._asset(session, asset_id)
            rows = session.scalars(
                select(LayoutBindingRow)
                .where(LayoutBindingRow.media_asset_id == asset_id)
                .order_by(LayoutBindingRow.start_us, LayoutBindingRow.id)
            ).all()
            return [
                {
                    "binding_id": row.id,
                    "participant_id": row.participant_id,
                    "start_us": int(row.start_us),
                    "end_us": int(row.end_us),
                    "x": int(row.x),
                    "y": int(row.y),
                    "w": int(row.w),
                    "h": int(row.h),
                }
                for row in rows
            ]

    def add_protected_region(self, asset_id: str, region: ProtectedRegion, *, note: str | None = None) -> str:
        self._require_write()
        region_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(ProtectedRegionRow(
                id=region_id,
                media_asset_id=asset_id,
                start_us=region.span.start_us,
                end_us=region.span.end_us,
                note=note,
            ))
            session.commit()
        return region_id

    def load_protected_regions(self, asset_id: str) -> list[ProtectedRegion]:
        with self._session() as session:
            rows = session.scalars(
                select(ProtectedRegionRow)
                .where(ProtectedRegionRow.media_asset_id == asset_id)
                .order_by(ProtectedRegionRow.start_us)
            ).all()
            return [ProtectedRegion(TimeRange(row.start_us, row.end_us)) for row in rows]

    def save_transcript(
        self,
        *,
        asset_id: str,
        words: list[Word],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange | None = None,
        config: dict | None = None,
        origin: str = "local",
        language: str | None = None,
        confidences: dict[str, float] | None = None,
    ) -> str:
        self._require_write()
        run_id = str(uuid.uuid4())
        transcript_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                run_id, asset_id, "transcript", algorithm_id, algorithm_version,
                origin, config, window, fingerprint,
            ))
            session.flush()
            session.add(TranscriptRow(
                id=transcript_id,
                analysis_run_id=run_id,
                media_asset_id=asset_id,
                language=language,
            ))
            session.flush()
            for index, word in enumerate(words):
                session.add(WordRow(
                    id=word.word_id,
                    transcript_id=transcript_id,
                    sequence=index,
                    text=word.text,
                    start_us=word.start_us,
                    end_us=word.end_us,
                    confidence=None if confidences is None else confidences.get(word.word_id),
                ))
            session.commit()
        return run_id

    def transcript_id(self, run_id: str) -> str:
        with self._session() as session:
            row = session.scalar(select(TranscriptRow).where(TranscriptRow.analysis_run_id == run_id))
            if row is None:
                raise ProjectDatabaseInvalid(f"no transcript for run {run_id}")
            return row.id

    def word_text_revision(self) -> str:
        """Changes when a word-text correction is added, edited, or removed."""
        with self._session() as session:
            count, newest = session.execute(
                select(func.count(), func.max(ManualCorrectionRow.created_at)).where(
                    ManualCorrectionRow.kind == WORD_TEXT
                )
            ).one()
        return f"{int(count or 0)}:{newest or ''}"

    def load_words(self, transcript_run_id: str) -> list[StoredWord]:
        with self._session() as session:
            transcript = session.scalar(
                select(TranscriptRow).where(TranscriptRow.analysis_run_id == transcript_run_id)
            )
            if transcript is None:
                raise ProjectDatabaseInvalid(f"no transcript for run {transcript_run_id}")
            words = session.scalars(
                select(WordRow).where(WordRow.transcript_id == transcript.id).order_by(WordRow.sequence)
            ).all()
            corrections = {
                row.target_id: row.value
                for row in session.scalars(
                    select(ManualCorrectionRow).where(ManualCorrectionRow.kind == WORD_TEXT)
                )
            }
            loaded = []
            for word in words:
                effective = corrections[word.id] if word.id in corrections and corrections[word.id] is not None else word.text
                loaded.append(StoredWord(
                    word.id, word.sequence, word.text, effective,
                    word.start_us, word.end_us, word.confidence, word.segment_ref,
                ))
            return loaded

    def correct_word_text(self, word_id: str, text_value: str, *, scope_id: str) -> None:
        self._write_correction(WORD_TEXT, word_id, scope_id, text_value)

    def clear_word_text(self, word_id: str) -> None:
        """Drop the text overlay. Machine word text is left as stored."""
        self._require_write()
        with self._session() as session:
            row = session.get(WordRow, word_id)
            if row is None:
                raise ProjectDatabaseInvalid(f"unknown word {word_id}")
            machine = row.text
            session.execute(
                delete(ManualCorrectionRow).where(
                    ManualCorrectionRow.kind == WORD_TEXT,
                    ManualCorrectionRow.target_id == word_id,
                )
            )
            session.commit()
            session.expire_all()
            if session.get(WordRow, word_id).text != machine:
                raise ProjectDatabaseInvalid("clearing a correction rewrote machine text")

    def active_transcript(self, asset_id: str) -> ActiveTranscript | None:
        with self._session() as session:
            self._asset(session, asset_id)
            active = session.get(ActiveAnalysisRow, (asset_id, "transcript"))
            if active is None:
                return None
            transcript = session.scalar(
                select(TranscriptRow).where(TranscriptRow.analysis_run_id == active.analysis_run_id)
            )
            if transcript is None:
                raise ProjectDatabaseInvalid(f"no transcript for run {active.analysis_run_id}")
            count = int(session.scalar(
                select(func.count()).select_from(WordRow).where(WordRow.transcript_id == transcript.id)
            ) or 0)
            return ActiveTranscript(
                transcript.id,
                active.analysis_run_id,
                asset_id,
                transcript.language,
                count,
            )

    def page_active_words(self, asset_id: str, offset: int, limit: int) -> tuple[ActiveTranscript, list[TranscriptWordView]]:
        if offset < 0 or limit < 1:
            raise ValueError("invalid word page")
        described = self.active_transcript(asset_id)
        if described is None:
            raise NoActiveTranscript(asset_id)
        with self._session() as session:
            words = session.scalars(
                select(WordRow)
                .where(WordRow.transcript_id == described.transcript_id)
                .order_by(WordRow.sequence, WordRow.id)
                .offset(offset)
                .limit(limit)
            ).all()
            return described, self._word_views(session, asset_id, words, described.analysis_run_id)

    def word_at_time(self, asset_id: str, time_us: int) -> WordHit | None:
        """Active transcript word containing time_us, using [start_us, end_us)."""
        if time_us < 0:
            raise ValueError("invalid word time")
        described = self.active_transcript(asset_id)
        if described is None:
            raise NoActiveTranscript(asset_id)
        with self._session() as session:
            word = session.scalar(
                select(WordRow)
                .where(
                    WordRow.transcript_id == described.transcript_id,
                    WordRow.start_us <= time_us,
                    WordRow.end_us > time_us,
                )
                .order_by(WordRow.sequence, WordRow.id)
                .limit(1)
            )
            if word is None:
                return None
            return WordHit(word.id, int(word.sequence), int(word.start_us), int(word.end_us))

    def active_word_view(self, asset_id: str, word_id: str) -> TranscriptWordView:
        described = self.active_transcript(asset_id)
        if described is None:
            raise NoActiveTranscript(asset_id)
        with self._session() as session:
            word = session.get(WordRow, word_id)
            if word is None or word.transcript_id != described.transcript_id:
                raise ProjectDatabaseInvalid(f"unknown word {word_id}")
            return self._word_views(session, asset_id, [word], described.analysis_run_id)[0]

    def _word_views(
        self,
        session: Session,
        asset_id: str,
        words: list[WordRow],
        transcript_run_id: str,
    ) -> list[TranscriptWordView]:
        ids = [word.id for word in words]
        if not ids:
            return []
        text_overrides = {
            row.target_id: row.value
            for row in session.scalars(
                select(ManualCorrectionRow).where(
                    ManualCorrectionRow.kind == WORD_TEXT,
                    ManualCorrectionRow.target_id.in_(ids),
                )
            )
        }
        assignment_row = session.get(ActiveAnalysisRow, (asset_id, PARTICIPANT_ASSIGNMENT))
        assignment_run_id = None
        if assignment_row is not None:
            depends = set(session.scalars(
                select(AnalysisDependencyRow.depends_on_run_id).where(
                    AnalysisDependencyRow.run_id == assignment_row.analysis_run_id,
                )
            ))
            if transcript_run_id in depends:
                assignment_run_id = assignment_row.analysis_run_id
        assigned: dict[str, str | None] = {}
        overrides: dict[str, str | None] = {}
        if assignment_run_id is not None:
            assigned = {
                row.word_id: row.participant_id
                for row in session.scalars(
                    select(SpeakerAssignmentRow).where(
                        SpeakerAssignmentRow.analysis_run_id == assignment_run_id,
                        SpeakerAssignmentRow.word_id.in_(ids),
                    )
                )
            }
            overrides = {
                row.target_id: row.value
                for row in session.scalars(
                    select(ManualCorrectionRow).where(
                        ManualCorrectionRow.kind == SPEAKER_OVERRIDE,
                        ManualCorrectionRow.target_id.in_(ids),
                    )
                )
            }
        participant_ids = {
            value
            for value in [*assigned.values(), *overrides.values()]
            if value
        }
        names = {}
        if participant_ids:
            names = {
                row.id: row.display_name
                for row in session.scalars(
                    select(ParticipantRow).where(ParticipantRow.id.in_(participant_ids))
                )
            }
        views = []
        for word in words:
            corrected = word.id in text_overrides and text_overrides[word.id] is not None
            effective = text_overrides[word.id] if corrected else word.text
            participant_id = None
            labeled = False
            if assignment_run_id is not None and word.id in overrides:
                participant_id = overrides[word.id]
                labeled = True
            elif assignment_run_id is not None and word.id in assigned:
                participant_id = assigned[word.id]
                labeled = True
            if labeled and not participant_id:
                participant_name = "Unknown"
            elif participant_id:
                participant_name = names.get(participant_id)
            else:
                participant_name = None
            views.append(TranscriptWordView(
                word.id,
                word.sequence,
                word.text,
                effective if effective is not None else word.text,
                word.start_us,
                word.end_us,
                word.confidence,
                corrected,
                participant_id,
                participant_name,
            ))
        return views

    def machine_word_text(self, word_id: str) -> str:
        with self._session() as session:
            row = session.get(WordRow, word_id)
            if row is None:
                raise ProjectDatabaseInvalid(f"unknown word {word_id}")
            return row.text

    def correct_speaker(self, word_id: str, participant_id: str | None, *, scope_id: str) -> None:
        """Record a speaker overlay. Generated assignment rows are not updated."""
        self._write_correction(SPEAKER_OVERRIDE, word_id, scope_id, participant_id)

    def correction_value(self, kind: str, target_id: str) -> str | None:
        with self._session() as session:
            row = session.scalar(
                select(ManualCorrectionRow).where(
                    ManualCorrectionRow.kind == kind,
                    ManualCorrectionRow.target_id == target_id,
                )
            )
            if row is None:
                raise ProjectDatabaseInvalid(f"no {kind} correction for {target_id}")
            return row.value

    def inapplicable_corrections(self, transcript_run_id: str) -> list[str]:
        """Corrections whose target word is not in this transcript."""
        with self._session() as session:
            transcript = session.scalar(
                select(TranscriptRow).where(TranscriptRow.analysis_run_id == transcript_run_id)
            )
            if transcript is None:
                raise ProjectDatabaseInvalid(transcript_run_id)
            word_ids = set(session.scalars(
                select(WordRow.id).where(WordRow.transcript_id == transcript.id)
            ))
            rows = session.scalars(select(ManualCorrectionRow)).all()
            return [row.target_id for row in rows if row.target_id not in word_ids]

    def save_assignments(
        self,
        *,
        asset_id: str,
        assignments: list[SpeakerAssignment],
        depends_on: list[str],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange | None = None,
        config: dict | None = None,
        origin: str = "local",
    ) -> str:
        return self._save_rows(
            asset_id, PARTICIPANT_ASSIGNMENT, depends_on, algorithm_id, algorithm_version,
            fingerprint, window, config, origin,
            lambda session, run_id: [
                SpeakerAssignmentRow(
                    analysis_run_id=run_id,
                    word_id=row.word_id,
                    participant_id=None if row.participant_id is None else row.participant_id.value,
                )
                for row in assignments
            ],
        )

    def load_assignments(self, run_id: str) -> list[SpeakerAssignment]:
        with self._session() as session:
            rows = session.execute(
                select(SpeakerAssignmentRow, WordRow.sequence)
                .join(WordRow, WordRow.id == SpeakerAssignmentRow.word_id)
                .where(SpeakerAssignmentRow.analysis_run_id == run_id)
                .order_by(WordRow.sequence)
            ).all()
            return [
                SpeakerAssignment(
                    row.word_id,
                    None if row.participant_id is None else ParticipantId(row.participant_id),
                )
                for row, _sequence in rows
            ]

    def save_turns(
        self,
        *,
        asset_id: str,
        turns: list[Turn],
        depends_on: list[str],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange | None = None,
        config: dict | None = None,
        origin: str = "local",
    ) -> str:
        def rows(session: Session, run_id: str):
            created = []
            for turn in turns:
                turn_id = str(uuid.uuid4())
                created.append(TurnRow(
                    id=turn_id,
                    analysis_run_id=run_id,
                    turn_key=turn.turn_id,
                    participant_id=None if turn.participant_id is None else turn.participant_id.value,
                    start_us=turn.start_us,
                    end_us=turn.end_us,
                ))
                for index, word_id in enumerate(turn.word_ids):
                    created.append(TurnWordRow(turn_id=turn_id, word_id=word_id, sequence=index))
            return created
        return self._save_rows(
            asset_id, "turns", depends_on, algorithm_id, algorithm_version,
            fingerprint, window, config, origin, rows,
        )

    def load_turns(self, run_id: str) -> list[Turn]:
        with self._session() as session:
            turns = session.scalars(
                select(TurnRow).where(TurnRow.analysis_run_id == run_id).order_by(TurnRow.turn_key)
            ).all()
            loaded = []
            for turn in turns:
                word_ids = session.scalars(
                    select(TurnWordRow.word_id)
                    .where(TurnWordRow.turn_id == turn.id)
                    .order_by(TurnWordRow.sequence)
                ).all()
                loaded.append(Turn(
                    turn.turn_key,
                    None if turn.participant_id is None else ParticipantId(turn.participant_id),
                    turn.start_us,
                    turn.end_us,
                    tuple(word_ids),
                ))
            return loaded

    def publish_conversation_map(
        self,
        *,
        asset_id: str,
        threads: list[dict],
        transcript_run_id: str,
        turns_run_id: str,
        fingerprint: str,
        window: TimeRange,
        config: dict,
        origin: str,
    ) -> str:
        """Store one complete map and switch the active pointer in the same commit."""
        self._require_write()
        run_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                run_id, asset_id, CONVERSATION_MAP, "amix.conversation.map.v1", "1",
                origin, config, window, fingerprint,
            ))
            session.flush()
            for parent in (transcript_run_id, turns_run_id):
                session.add(AnalysisDependencyRow(run_id=run_id, depends_on_run_id=parent))
            session.flush()
            for index, thread in enumerate(threads):
                session.add(ConversationThreadRow(
                    id=str(uuid.uuid4()),
                    analysis_run_id=run_id,
                    order_index=index,
                    first_turn_id=thread["first_turn_id"],
                    last_turn_id=thread["last_turn_id"],
                    first_word_id=thread["first_word_id"],
                    last_word_id=thread["last_word_id"],
                    title=thread["title"],
                    summary=thread["summary"],
                    topic=thread.get("topic"),
                    start_us=thread["start_us"],
                    end_us=thread["end_us"],
                ))
            self._point_active(session, asset_id, CONVERSATION_MAP, run_id)
            session.commit()
        return run_id

    def publish_reel_discovery(
        self,
        *,
        asset_id: str,
        candidates: list[dict],
        parents: list[str],
        window: TimeRange,
        config: dict,
        origin: str,
    ) -> str:
        """Store one complete candidate set and switch the active pointer in the same commit."""
        self._require_write()
        run_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                run_id, asset_id, REEL_DISCOVERY, "amix.reel.discover.v1", "1",
                origin, config, window, config["text_fingerprint"],
            ))
            session.flush()
            for parent in parents:
                session.add(AnalysisDependencyRow(run_id=run_id, depends_on_run_id=parent))
            session.flush()
            for index, candidate in enumerate(candidates):
                session.add(ReelCandidateRow(
                    id=str(uuid.uuid4()),
                    analysis_run_id=run_id,
                    order_index=index,
                    conversation_thread_id=candidate["conversation_thread_id"],
                    first_turn_id=candidate["first_turn_id"],
                    last_turn_id=candidate["last_turn_id"],
                    first_word_id=candidate["first_word_id"],
                    last_word_id=candidate["last_word_id"],
                    start_us=candidate["start_us"],
                    end_us=candidate["end_us"],
                    title=candidate["title"],
                    summary=candidate["summary"],
                    hook=candidate["hook"],
                ))
            self._point_active(session, asset_id, REEL_DISCOVERY, run_id)
            session.commit()
        return run_id

    def load_reel_candidates(self, run_id: str) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(
                select(ReelCandidateRow)
                .where(ReelCandidateRow.analysis_run_id == run_id)
                .order_by(ReelCandidateRow.order_index)
            ).all()
            return [
                {
                    "candidate_id": row.id,
                    "order_index": int(row.order_index),
                    "conversation_thread_id": row.conversation_thread_id,
                    "first_turn_id": row.first_turn_id,
                    "last_turn_id": row.last_turn_id,
                    "first_word_id": row.first_word_id,
                    "last_word_id": row.last_word_id,
                    "start_us": int(row.start_us),
                    "end_us": int(row.end_us),
                    "title": row.title,
                    "summary": row.summary,
                    "hook": row.hook,
                }
                for row in rows
            ]

    def load_reel_candidate(self, candidate_id: str) -> dict | None:
        with self._session() as session:
            row = session.get(ReelCandidateRow, candidate_id)
            if row is None:
                return None
            run = session.get(AnalysisRunRow, row.analysis_run_id)
            if run is None or run.project_id != self.project_id:
                return None
            return {
                "candidate_id": row.id,
                "analysis_run_id": row.analysis_run_id,
                "media_asset_id": run.media_asset_id,
                "order_index": int(row.order_index),
                "conversation_thread_id": row.conversation_thread_id,
                "first_turn_id": row.first_turn_id,
                "last_turn_id": row.last_turn_id,
                "first_word_id": row.first_word_id,
                "last_word_id": row.last_word_id,
                "start_us": int(row.start_us),
                "end_us": int(row.end_us),
                "title": row.title,
                "summary": row.summary,
                "hook": row.hook,
            }

    def load_conversation_threads(self, run_id: str) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(
                select(ConversationThreadRow)
                .where(ConversationThreadRow.analysis_run_id == run_id)
                .order_by(ConversationThreadRow.order_index)
            ).all()
            return [
                {
                    "thread_id": row.id,
                    "order_index": int(row.order_index),
                    "first_turn_id": row.first_turn_id,
                    "last_turn_id": row.last_turn_id,
                    "first_word_id": row.first_word_id,
                    "last_word_id": row.last_word_id,
                    "title": row.title,
                    "summary": row.summary,
                    "topic": row.topic,
                    "start_us": int(row.start_us),
                    "end_us": int(row.end_us),
                }
                for row in rows
            ]

    def save_overlaps(
        self,
        *,
        asset_id: str,
        regions: list[OverlapRegion],
        depends_on: list[str],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange | None = None,
        config: dict | None = None,
        origin: str = "local",
    ) -> str:
        def rows(session: Session, run_id: str):
            created = []
            for region in regions:
                region_id = str(uuid.uuid4())
                created.append(OverlapRegionRow(
                    id=region_id,
                    analysis_run_id=run_id,
                    start_us=region.start_us,
                    end_us=region.end_us,
                    confidence=region.confidence,
                ))
                for index, participant in enumerate(region.participant_ids):
                    created.append(OverlapParticipantRow(
                        region_id=region_id,
                        participant_id=participant.value,
                        sequence=index,
                    ))
            return created
        return self._save_rows(
            asset_id, "overlap", depends_on, algorithm_id, algorithm_version,
            fingerprint, window, config, origin, rows,
        )

    def load_overlaps(self, run_id: str) -> list[OverlapRegion]:
        with self._session() as session:
            regions = session.scalars(
                select(OverlapRegionRow)
                .where(OverlapRegionRow.analysis_run_id == run_id)
                .order_by(OverlapRegionRow.start_us)
            ).all()
            loaded = []
            for region in regions:
                people = session.scalars(
                    select(OverlapParticipantRow.participant_id)
                    .where(OverlapParticipantRow.region_id == region.id)
                    .order_by(OverlapParticipantRow.sequence)
                ).all()
                loaded.append(OverlapRegion(
                    region.start_us,
                    region.end_us,
                    tuple(ParticipantId(value) for value in people),
                    region.confidence,
                ))
            return loaded

    def save_shot_plan(
        self,
        *,
        asset_id: str,
        plan: ShotPlan,
        depends_on: list[str],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        config: dict | None = None,
        origin: str = "local",
    ) -> str:
        def rows(session: Session, run_id: str):
            plan_id = str(uuid.uuid4())
            created = [ShotPlanRow(
                id=plan_id,
                analysis_run_id=run_id,
                start_us=plan.span.start_us,
                end_us=plan.span.end_us,
            )]
            for index, shot in enumerate(plan.shots):
                created.append(ShotRow(
                    shot_plan_id=plan_id,
                    sequence=index,
                    start_us=shot.start_us,
                    end_us=shot.end_us,
                    presentation=shot.presentation.value,
                    participant_id=None if shot.participant_id is None else shot.participant_id.value,
                    floor_participant_id=None if shot.floor_participant_id is None else shot.floor_participant_id.value,
                    reason=shot.reason,
                ))
            return created
        return self._save_rows(
            asset_id, "shot_plan", depends_on, algorithm_id, algorithm_version,
            fingerprint, plan.span, config, origin, rows,
        )

    def load_shot_plan(self, run_id: str) -> ShotPlan:
        with self._session() as session:
            plan = session.scalar(select(ShotPlanRow).where(ShotPlanRow.analysis_run_id == run_id))
            if plan is None:
                raise ProjectDatabaseInvalid(f"no shot plan for run {run_id}")
            shots = session.scalars(
                select(ShotRow).where(ShotRow.shot_plan_id == plan.id).order_by(ShotRow.sequence)
            ).all()
            return ShotPlan(
                TimeRange(plan.start_us, plan.end_us),
                tuple(
                    Shot(
                        shot.start_us,
                        shot.end_us,
                        Presentation(shot.presentation),
                        None if shot.participant_id is None else ParticipantId(shot.participant_id),
                        None if shot.floor_participant_id is None else ParticipantId(shot.floor_participant_id),
                        shot.reason,
                    )
                    for shot in shots
                ),
            )

    def list_shot_records(self, run_id: str) -> list[dict]:
        with self._session() as session:
            plan = session.scalar(select(ShotPlanRow).where(ShotPlanRow.analysis_run_id == run_id))
            if plan is None:
                raise ProjectDatabaseInvalid(f"no shot plan for run {run_id}")
            shots = session.scalars(
                select(ShotRow).where(ShotRow.shot_plan_id == plan.id).order_by(ShotRow.sequence)
            ).all()
            return [
                {
                    "shot_id": shot.id,
                    "sequence": int(shot.sequence),
                    "start_us": int(shot.start_us),
                    "end_us": int(shot.end_us),
                    "presentation": shot.presentation,
                    "participant_id": shot.participant_id,
                    "floor_participant_id": shot.floor_participant_id,
                    "reason": shot.reason,
                }
                for shot in shots
            ]

    def list_shot_overrides(self, plan_run_id: str) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(
                select(ShotOverrideRow)
                .where(ShotOverrideRow.shot_plan_run_id == plan_run_id)
                .order_by(ShotOverrideRow.shot_id)
            ).all()
            return [
                {
                    "override_id": row.id,
                    "shot_id": row.shot_id,
                    "decision": row.decision,
                    "participant_id": row.participant_id,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ]

    def save_shot_override(
        self,
        *,
        asset_id: str,
        plan_run_id: str,
        shot_id: str,
        decision: str,
        participant_id: str | None,
    ) -> str:
        self._require_write()
        with self._session() as session:
            self._asset(session, asset_id)
            current = session.scalar(
                select(ShotOverrideRow).where(
                    ShotOverrideRow.shot_plan_run_id == plan_run_id,
                    ShotOverrideRow.shot_id == shot_id,
                )
            )
            now = _now()
            if current is None:
                current = ShotOverrideRow(
                    id=str(uuid.uuid4()),
                    media_asset_id=asset_id,
                    shot_plan_run_id=plan_run_id,
                    shot_id=shot_id,
                    decision=decision,
                    participant_id=participant_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(current)
            else:
                current.decision = decision
                current.participant_id = participant_id
                current.updated_at = now
            session.commit()
            return current.id

    def clear_shot_override(self, plan_run_id: str, shot_id: str) -> None:
        self._require_write()
        with self._session() as session:
            current = session.scalar(
                select(ShotOverrideRow).where(
                    ShotOverrideRow.shot_plan_run_id == plan_run_id,
                    ShotOverrideRow.shot_id == shot_id,
                )
            )
            if current is not None:
                session.delete(current)
                session.commit()

    def load_primary_sequence(self, asset_id: str) -> dict | None:
        """The source's primary edit, if one exists. A reel sequence is never returned."""
        with self._session() as session:
            row = session.scalar(
                select(EditorialSequenceRow).where(
                    EditorialSequenceRow.media_asset_id == asset_id,
                    EditorialSequenceRow.purpose == "primary",
                )
            )
            if row is None:
                return None
            return _sequence_view(session, row)

    def load_editorial_sequence(self, asset_id: str) -> dict | None:
        """Primary sequence only. Callers that mean the main edit use this or load_primary_sequence."""
        return self.load_primary_sequence(asset_id)

    def list_sequences(self, asset_id: str, purpose: str | None = None) -> list[dict]:
        with self._session() as session:
            query = select(EditorialSequenceRow).where(EditorialSequenceRow.media_asset_id == asset_id)
            if purpose is not None:
                query = query.where(EditorialSequenceRow.purpose == purpose)
            rows = session.scalars(query.order_by(EditorialSequenceRow.created_at, EditorialSequenceRow.id)).all()
            return [_sequence_view(session, row) for row in rows]

    def load_editorial_sequence_by_id(self, sequence_id: str) -> dict:
        with self._session() as session:
            row = session.get(EditorialSequenceRow, sequence_id)
            if row is None or row.project_id != self.project_id:
                raise ProjectDatabaseInvalid(f"unknown sequence {sequence_id}")
            return _sequence_view(session, row)

    def insert_editorial_sequence(
        self,
        *,
        asset_id: str,
        display_name: str,
        source_start_us: int,
        source_end_us: int,
        clips: list[tuple[int, int]],
        purpose: str = "primary",
        origin_candidate_id: str | None = None,
    ) -> str:
        self._require_write()
        from amix.amix_engine.editorial.sequence import validate_clips

        if purpose not in {"primary", "reel"}:
            raise ProjectDatabaseInvalid(f"unknown sequence purpose {purpose}")
        if purpose == "reel" and not origin_candidate_id:
            raise ProjectDatabaseInvalid("A reel sequence needs its origin candidate.")
        validate_clips(clips, source_start_us, source_end_us)
        sequence_id = str(uuid.uuid4())
        now = _now()
        with self._session() as session:
            self._asset(session, asset_id)
            if purpose == "primary":
                existing = session.scalar(
                    select(EditorialSequenceRow.id).where(
                        EditorialSequenceRow.media_asset_id == asset_id,
                        EditorialSequenceRow.purpose == "primary",
                    )
                )
                if existing is not None:
                    raise ProjectDatabaseInvalid("This source already has a primary sequence.")
            session.add(EditorialSequenceRow(
                id=sequence_id,
                project_id=self.project_id,
                media_asset_id=asset_id,
                purpose=purpose,
                origin_candidate_id=origin_candidate_id,
                display_name=display_name,
                source_start_us=source_start_us,
                source_end_us=source_end_us,
                revision=1,
                created_at=now,
                updated_at=now,
            ))
            session.flush()
            _replace_clip_rows(session, sequence_id, clips)
            session.commit()
        return sequence_id

    def replace_sequence_clips(self, sequence_id: str, clips: list[tuple[int, int]]) -> int:
        """Replace kept ranges and bump the editorial revision. The sequence id stays."""
        self._require_write()
        with self._session() as session:
            row = session.get(EditorialSequenceRow, sequence_id)
            if row is None or row.project_id != self.project_id:
                raise ProjectDatabaseInvalid(f"unknown sequence {sequence_id}")
            from amix.amix_engine.editorial.sequence import validate_clips

            validate_clips(clips, int(row.source_start_us), int(row.source_end_us))
            _replace_clip_rows(session, sequence_id, clips)
            row.revision = int(row.revision) + 1
            row.updated_at = _now()
            session.commit()
            return int(row.revision)

    def publish_export(
        self,
        source_asset_id: str,
        record: MediaProbeRecord,
        *,
        relative_path: str,
        display_name: str,
        job_id: str,
    ) -> str:
        """Insert one export asset. The encoded file must already be in place."""
        self._require_write()
        asset_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, source_asset_id)
            row = MediaAssetRow(
                id=asset_id,
                project_id=self.project_id,
                role="export",
                display_name=display_name,
                location_kind="project",
                relative_path=relative_path.replace("\\", "/"),
                source_media_asset_id=source_asset_id,
                producing_job_id=job_id,
                proxy_created_at=_now(),
            )
            _write_probe(row, record)
            session.add(row)
            session.commit()
        return asset_id

    def publish_activated_transcript(
        self,
        *,
        asset_id: str,
        words: list[Word],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange,
        config: dict,
        language: str | None,
        confidences: dict[str, float | None],
        segments: dict[str, str | None],
    ) -> str:
        """Store one transcript and make it active in the same commit.

        An older transcript and its corrections stay on their own word ids.
        """
        self._require_write()
        run_id = str(uuid.uuid4())
        transcript_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                run_id, asset_id, "transcript", algorithm_id, algorithm_version,
                "local", config, window, fingerprint,
            ))
            session.flush()
            session.add(TranscriptRow(
                id=transcript_id,
                analysis_run_id=run_id,
                media_asset_id=asset_id,
                language=language,
            ))
            session.flush()
            for index, word in enumerate(words):
                session.add(WordRow(
                    id=word.word_id,
                    transcript_id=transcript_id,
                    sequence=index,
                    text=word.text,
                    start_us=word.start_us,
                    end_us=word.end_us,
                    confidence=confidences.get(word.word_id),
                    segment_ref=segments.get(word.word_id),
                ))
            session.flush()
            current = session.get(ActiveAnalysisRow, (asset_id, "transcript"))
            if current is None:
                session.add(ActiveAnalysisRow(
                    media_asset_id=asset_id,
                    kind="transcript",
                    analysis_run_id=run_id,
                    activated_at=_now(),
                ))
            else:
                current.analysis_run_id = run_id
                current.activated_at = _now()
            session.commit()
        return run_id

    def analysis_record(self, run_id: str) -> dict:
        with self._session() as session:
            row = session.get(AnalysisRunRow, run_id)
            if row is None:
                raise ProjectDatabaseInvalid(run_id)
            return {
                "run_id": row.id,
                "media_asset_id": row.media_asset_id,
                "kind": row.kind,
                "status": row.status,
                "algorithm_id": row.algorithm_id,
                "algorithm_version": row.algorithm_version,
                "origin": row.origin,
                "fingerprint": row.input_fingerprint,
                "window_start_us": row.window_start_us,
                "window_end_us": row.window_end_us,
                "config": json.loads(row.config_json),
                "created_at": row.created_at,
            }

    def publish_diarization(
        self,
        *,
        asset_id: str,
        segments: list[DiarizationSegment],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange | None,
        config: dict | None = None,
        origin: str = "local",
    ) -> str:
        """Store anonymous segments and switch the active diarization pointer.

        Assignment and turn pointers are left unchanged.
        """
        self._require_write()
        run_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                run_id, asset_id, DIARIZATION, algorithm_id, algorithm_version,
                origin, config, window, fingerprint,
            ))
            session.flush()
            for index, segment in enumerate(segments):
                session.add(DiarizationSegmentRow(
                    analysis_run_id=run_id,
                    sequence=index,
                    cluster_key=segment.cluster_id,
                    start_us=segment.start_us,
                    end_us=segment.end_us,
                ))
            self._point_active(session, asset_id, DIARIZATION, run_id)
            session.commit()
        return run_id

    def publish_overlap(
        self,
        *,
        asset_id: str,
        regions: list[OverlapRegion],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange,
        config: dict,
    ) -> str:
        """Store overlap regions and switch the active overlap pointer.

        This run has no transcript or turn dependency.
        """
        self._require_write()
        run_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                run_id, asset_id, OVERLAP, algorithm_id, algorithm_version,
                "local", config, window, fingerprint,
            ))
            session.flush()
            for region in regions:
                region_id = str(uuid.uuid4())
                session.add(OverlapRegionRow(
                    id=region_id,
                    analysis_run_id=run_id,
                    start_us=region.start_us,
                    end_us=region.end_us,
                    confidence=region.confidence,
                ))
                session.flush()
                for index, participant in enumerate(region.participant_ids):
                    session.add(OverlapParticipantRow(
                        region_id=region_id,
                        participant_id=participant.value,
                        sequence=index,
                    ))
            self._point_active(session, asset_id, OVERLAP, run_id)
            session.commit()
        return run_id

    def publish_shot_plan(
        self,
        *,
        asset_id: str,
        plan: ShotPlan,
        depends_on: list[str],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        config: dict,
    ) -> str:
        """Store one automatic plan and switch the active shot-plan pointer."""
        self._require_write()
        run_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            for dependency in depends_on:
                if session.get(AnalysisRunRow, dependency) is None:
                    raise ProjectDatabaseInvalid(f"unknown analysis dependency {dependency}")
            session.add(self._run(
                run_id, asset_id, SHOT_PLAN, algorithm_id, algorithm_version,
                "local", config, plan.span, fingerprint,
            ))
            session.flush()
            for dependency in depends_on:
                session.add(AnalysisDependencyRow(
                    run_id=run_id,
                    depends_on_run_id=dependency,
                ))
            plan_id = str(uuid.uuid4())
            session.add(ShotPlanRow(
                id=plan_id,
                analysis_run_id=run_id,
                start_us=plan.span.start_us,
                end_us=plan.span.end_us,
            ))
            session.flush()
            for index, shot in enumerate(plan.shots):
                session.add(ShotRow(
                    shot_plan_id=plan_id,
                    sequence=index,
                    start_us=shot.start_us,
                    end_us=shot.end_us,
                    presentation=shot.presentation.value,
                    participant_id=None if shot.participant_id is None else shot.participant_id.value,
                    floor_participant_id=None if shot.floor_participant_id is None else shot.floor_participant_id.value,
                    reason=shot.reason,
                ))
            self._point_active(session, asset_id, SHOT_PLAN, run_id)
            session.commit()
        return run_id

    def load_diarization_segments(self, run_id: str) -> list[DiarizationSegment]:
        with self._session() as session:
            rows = session.scalars(
                select(DiarizationSegmentRow)
                .where(DiarizationSegmentRow.analysis_run_id == run_id)
                .order_by(DiarizationSegmentRow.sequence)
            ).all()
            return [
                DiarizationSegment(int(row.start_us), int(row.end_us), row.cluster_key)
                for row in rows
            ]

    def publish_assignment_and_turns(
        self,
        *,
        asset_id: str,
        assignments: list[SpeakerAssignment],
        turns: list[Turn],
        transcript_run_id: str,
        diarization_run_id: str,
        fingerprint: str,
        window: TimeRange | None,
        assignment_config: dict,
        turn_config: dict,
        assignment_algorithm: str,
        turn_algorithm: str,
    ) -> tuple[str, str]:
        """Insert assignment and turns, then switch both active pointers in one commit."""
        self._require_write()
        assignment_id = str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                assignment_id, asset_id, PARTICIPANT_ASSIGNMENT, assignment_algorithm, "1",
                "local", assignment_config, window, fingerprint,
            ))
            session.flush()
            session.add(AnalysisDependencyRow(run_id=assignment_id, depends_on_run_id=transcript_run_id))
            session.add(AnalysisDependencyRow(run_id=assignment_id, depends_on_run_id=diarization_run_id))
            session.flush()
            for row in assignments:
                session.add(SpeakerAssignmentRow(
                    analysis_run_id=assignment_id,
                    word_id=row.word_id,
                    participant_id=None if row.participant_id is None else row.participant_id.value,
                ))
            session.add(self._run(
                turn_id, asset_id, TURNS, turn_algorithm, "1",
                "local", turn_config, window, fingerprint,
            ))
            session.flush()
            session.add(AnalysisDependencyRow(run_id=turn_id, depends_on_run_id=assignment_id))
            session.flush()
            for turn in turns:
                stored_turn = str(uuid.uuid4())
                session.add(TurnRow(
                    id=stored_turn,
                    analysis_run_id=turn_id,
                    turn_key=turn.turn_id,
                    participant_id=None if turn.participant_id is None else turn.participant_id.value,
                    start_us=turn.start_us,
                    end_us=turn.end_us,
                ))
                session.flush()
                for index, word_id in enumerate(turn.word_ids):
                    session.add(TurnWordRow(turn_id=stored_turn, word_id=word_id, sequence=index))
            self._point_active(session, asset_id, PARTICIPANT_ASSIGNMENT, assignment_id)
            self._point_active(session, asset_id, TURNS, turn_id)
            session.commit()
        return assignment_id, turn_id

    def _point_active(self, session: Session, asset_id: str, kind: str, run_id: str) -> None:
        current = session.get(ActiveAnalysisRow, (asset_id, kind))
        if current is None:
            session.add(ActiveAnalysisRow(
                media_asset_id=asset_id,
                kind=kind,
                analysis_run_id=run_id,
                activated_at=_now(),
            ))
        else:
            current.analysis_run_id = run_id
            current.activated_at = _now()

    def set_active(self, asset_id: str, kind: str, run_id: str) -> None:
        self._require_write()
        if kind not in ANALYSIS_KINDS:
            raise ValueError(f"unknown analysis kind: {kind}")
        with self._session() as session:
            run = session.get(AnalysisRunRow, run_id)
            if run is None or run.media_asset_id != asset_id or run.kind != kind:
                raise ProjectDatabaseInvalid(
                    f"run {run_id} is not a {kind} analysis of asset {asset_id}"
                )
            current = session.get(ActiveAnalysisRow, (asset_id, kind))
            if current is None:
                session.add(ActiveAnalysisRow(
                    media_asset_id=asset_id,
                    kind=kind,
                    analysis_run_id=run_id,
                    activated_at=_now(),
                ))
            else:
                current.analysis_run_id = run_id
                current.activated_at = _now()
            session.commit()

    def get_active_run_id(self, asset_id: str, kind: str) -> str | None:
        with self._session() as session:
            row = session.get(ActiveAnalysisRow, (asset_id, kind))
            return None if row is None else row.analysis_run_id

    def list_run_ids(self, asset_id: str, kind: str) -> list[str]:
        with self._session() as session:
            return list(session.scalars(
                select(AnalysisRunRow.id)
                .where(AnalysisRunRow.media_asset_id == asset_id, AnalysisRunRow.kind == kind)
                .order_by(AnalysisRunRow.created_at)
            ))

    def run_window(self, run_id: str) -> tuple[int | None, int | None]:
        with self._session() as session:
            row = session.get(AnalysisRunRow, run_id)
            if row is None:
                raise ProjectDatabaseInvalid(run_id)
            return row.window_start_us, row.window_end_us

    def run_dependencies(self, run_id: str) -> list[str]:
        with self._session() as session:
            return list(session.scalars(
                select(AnalysisDependencyRow.depends_on_run_id)
                .where(AnalysisDependencyRow.run_id == run_id)
            ))

    def _save_rows(
        self,
        asset_id: str,
        kind: str,
        depends_on: list[str],
        algorithm_id: str,
        algorithm_version: str,
        fingerprint: str,
        window: TimeRange | None,
        config: dict | None,
        origin: str,
        build,
    ) -> str:
        self._require_write()
        run_id = str(uuid.uuid4())
        with self._session() as session:
            self._asset(session, asset_id)
            session.add(self._run(
                run_id, asset_id, kind, algorithm_id, algorithm_version,
                origin, config, window, fingerprint,
            ))
            session.flush()
            for parent in depends_on:
                session.add(AnalysisDependencyRow(run_id=run_id, depends_on_run_id=parent))
                session.flush()
            for row in build(session, run_id):
                session.add(row)
                session.flush()
            session.commit()
        return run_id

    def _run(
        self,
        run_id: str,
        asset_id: str,
        kind: str,
        algorithm_id: str,
        algorithm_version: str,
        origin: str,
        config: dict | None,
        window: TimeRange | None,
        fingerprint: str,
    ) -> AnalysisRunRow:
        return AnalysisRunRow(
            id=run_id,
            project_id=self.project_id,
            media_asset_id=asset_id,
            kind=kind,
            status="succeeded",
            algorithm_id=algorithm_id,
            algorithm_version=algorithm_version,
            origin=origin,
            config_json=json.dumps(config or {}, sort_keys=True),
            window_start_us=None if window is None else window.start_us,
            window_end_us=None if window is None else window.end_us,
            input_fingerprint=fingerprint,
            created_at=_now(),
        )

    def _write_correction(self, kind: str, target_id: str, scope_id: str, value: str | None) -> None:
        self._require_write()
        with self._session() as session:
            if session.get(WordRow, target_id) is None:
                raise ProjectDatabaseInvalid(f"unknown word {target_id}")
            before = session.get(WordRow, target_id).text
            existing = session.scalar(
                select(ManualCorrectionRow).where(
                    ManualCorrectionRow.kind == kind,
                    ManualCorrectionRow.target_id == target_id,
                )
            )
            if existing is None:
                session.add(ManualCorrectionRow(
                    project_id=self.project_id,
                    kind=kind,
                    target_id=target_id,
                    scope_id=scope_id,
                    value=value,
                    created_at=_now(),
                ))
            else:
                existing.value = value
                existing.scope_id = scope_id
                existing.created_at = _now()
            session.commit()
            session.expire_all()
            if session.get(WordRow, target_id).text != before:
                raise ProjectDatabaseInvalid("a correction rewrote machine text")

    def _asset(self, session: Session, asset_id: str) -> MediaAssetRow:
        row = session.get(MediaAssetRow, asset_id)
        if row is None or row.project_id != self.project_id:
            raise ProjectDatabaseInvalid(f"unknown media asset {asset_id}")
        return row


def _media(row: MediaAssetRow) -> StoredMedia:
    return StoredMedia(
        asset_id=row.id,
        role=row.role,
        display_name=row.display_name,
        location_kind=row.location_kind,
        relative_path=row.relative_path,
        external_path=row.external_path,
        byte_size=row.byte_size,
        content_id=row.content_id,
        duration_us=row.duration_us,
        width=row.width,
        height=row.height,
        fps_num=row.fps_num,
        fps_den=row.fps_den,
        container_start_us=row.container_start_us,
        container=row.container,
        video_codec=row.video_codec,
        audio_codec=row.audio_codec,
        video_duration_us=row.video_duration_us,
        audio_duration_us=row.audio_duration_us,
        duration_source=row.duration_source,
        sample_rate=row.sample_rate,
        audio_channels=row.audio_channels,
        channel_layout=row.channel_layout,
        pixel_format=row.pixel_format,
        r_fps_num=row.r_fps_num,
        r_fps_den=row.r_fps_den,
        time_base_num=row.time_base_num,
        time_base_den=row.time_base_den,
        rotation_degrees=row.rotation_degrees,
        bit_rate=row.bit_rate,
        video_start_us=row.video_start_us,
        audio_start_us=row.audio_start_us,
        file_mtime_ns=row.file_mtime_ns,
        probed_at=row.probed_at,
        probe_tool=row.probe_tool,
        probe_config=row.probe_config,
        source_media_asset_id=row.source_media_asset_id,
        proxy_profile=row.proxy_profile,
        proxy_tool=row.proxy_tool,
        producing_job_id=row.producing_job_id,
        proxy_source_size=row.proxy_source_size,
        proxy_source_mtime_ns=row.proxy_source_mtime_ns,
        proxy_created_at=row.proxy_created_at,
        timestamp_policy=row.timestamp_policy,
    )


def _write_probe(row: MediaAssetRow, record: MediaProbeRecord) -> None:
    row.container = record.container
    row.duration_us = record.duration_us
    row.duration_source = record.duration_source
    row.container_start_us = record.container_start_us
    row.bit_rate = record.bit_rate
    row.video_codec = record.video_codec
    row.width = record.width
    row.height = record.height
    row.pixel_format = record.pixel_format
    row.fps_num = record.fps_num
    row.fps_den = record.fps_den
    row.r_fps_num = record.r_fps_num
    row.r_fps_den = record.r_fps_den
    row.time_base_num = record.time_base_num
    row.time_base_den = record.time_base_den
    row.video_start_us = record.video_start_us
    row.video_duration_us = record.video_duration_us
    row.rotation_degrees = record.rotation_degrees
    row.audio_codec = record.audio_codec
    row.sample_rate = record.sample_rate
    row.audio_channels = record.audio_channels
    row.channel_layout = record.channel_layout
    row.audio_start_us = record.audio_start_us
    row.audio_duration_us = record.audio_duration_us
    row.byte_size = record.byte_size
    row.file_mtime_ns = record.file_mtime_ns
    row.probed_at = _now()
    row.probe_tool = record.probe_tool
    row.probe_config = record.probe_config


def _clear_probe(row: MediaAssetRow) -> None:
    row.container = None
    row.duration_us = None
    row.duration_source = None
    row.container_start_us = None
    row.bit_rate = None
    row.video_codec = None
    row.audio_codec = None
    row.width = None
    row.height = None
    row.pixel_format = None
    row.fps_num = None
    row.fps_den = None
    row.r_fps_num = None
    row.r_fps_den = None
    row.time_base_num = None
    row.time_base_den = None
    row.video_start_us = None
    row.video_duration_us = None
    row.rotation_degrees = None
    row.sample_rate = None
    row.audio_channels = None
    row.channel_layout = None
    row.audio_start_us = None
    row.audio_duration_us = None
    row.probed_at = None
    row.probe_tool = None
    row.probe_config = None


def _sequence_view(session, row: EditorialSequenceRow) -> dict:
    clips = session.scalars(
        select(SequenceClipRow)
        .where(SequenceClipRow.sequence_id == row.id)
        .order_by(SequenceClipRow.order_index)
    ).all()
    return {
        "sequence_id": row.id,
        "media_asset_id": row.media_asset_id,
        "purpose": row.purpose,
        "origin_candidate_id": row.origin_candidate_id,
        "display_name": row.display_name,
        "source_start_us": int(row.source_start_us),
        "source_end_us": int(row.source_end_us),
        "revision": int(row.revision),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "clips": [
            {
                "clip_id": clip.id,
                "order_index": int(clip.order_index),
                "source_start_us": int(clip.source_start_us),
                "source_end_us": int(clip.source_end_us),
            }
            for clip in clips
        ],
    }


def _replace_clip_rows(session, sequence_id: str, clips: list[tuple[int, int]]) -> None:
    existing = session.scalars(
        select(SequenceClipRow).where(SequenceClipRow.sequence_id == sequence_id)
    ).all()
    for clip in existing:
        session.delete(clip)
    session.flush()
    for index, (start_us, end_us) in enumerate(clips):
        session.add(SequenceClipRow(
            id=str(uuid.uuid4()),
            sequence_id=sequence_id,
            order_index=index,
            source_start_us=start_us,
            source_end_us=end_us,
        ))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
