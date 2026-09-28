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

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from amix.amix_engine import __version__
from amix.amix_engine.domain.types import (
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
    MediaMissing,
    ProjectDatabaseInvalid,
    SchemaMismatch,
)
from amix.amix_engine.storage.kinds import (
    ANALYSIS_KINDS,
    PARTICIPANT_ASSIGNMENT,
    SPEAKER_OVERRIDE,
    WORD_TEXT,
)
from amix.amix_engine.storage.lock import ProjectWriteLock
from amix.amix_engine.storage.migrate import current_revision, head_revision, upgrade_database
from amix.amix_engine.storage.models import (
    ActiveAnalysisRow,
    AnalysisDependencyRow,
    AnalysisRunRow,
    LayoutBindingRow,
    ManualCorrectionRow,
    MediaAssetRow,
    OverlapParticipantRow,
    OverlapRegionRow,
    ParticipantRow,
    ProjectRow,
    ProtectedRegionRow,
    ShotPlanRow,
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
_FOLDERS = ("media", "proxy", "cache", "artifacts", "exports", "logs")


def create_project(path: str | Path, name: str) -> ProjectStore:
    root = Path(path)
    database = root / DATABASE_NAME
    if database.exists():
        raise ProjectDatabaseInvalid(f"project database already exists: {database}")
    root.mkdir(parents=True, exist_ok=True)
    for folder in _FOLDERS:
        (root / folder).mkdir(exist_ok=True)
    lock = ProjectWriteLock(root)
    lock.acquire()
    store: ProjectStore | None = None
    try:
        upgrade_database(database)
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
    database = root / DATABASE_NAME
    if not database.is_file():
        raise ProjectDatabaseInvalid(f"missing project database: {database}")
    lock = None
    if read_only:
        revision = current_revision(database)
        if revision != head_revision():
            raise SchemaMismatch(
                f"database revision {revision!r} is not {head_revision()!r}; "
                "open the project for write to migrate"
            )
    else:
        lock = ProjectWriteLock(root)
        lock.acquire()
        try:
            upgrade_database(database)
        except Exception:
            lock.release()
            raise
    store = ProjectStore(root, lock=lock, read_only=read_only)
    try:
        store._load_identity()
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


@dataclass(frozen=True)
class StoredWord:
    word_id: str
    sequence: int
    machine_text: str
    effective_text: str
    start_us: int
    end_us: int
    confidence: float | None


class ProjectStore:
    def __init__(self, root: Path, *, lock: ProjectWriteLock | None, read_only: bool) -> None:
        self.root = root.resolve()
        self.read_only = read_only
        self._lock = lock
        self._engine = create_project_engine(self.root / DATABASE_NAME, read_only=read_only)
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
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        self.project_id = project_id
        self.project_name = name

    def _load_identity(self) -> None:
        manifest_path = self.root / "manifest.json"
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
        return current_revision(self.root / DATABASE_NAME)

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
            ))
            session.commit()
        return asset_id

    def get_media(self, asset_id: str) -> StoredMedia:
        with self._session() as session:
            row = self._asset(session, asset_id)
            return StoredMedia(
                row.id,
                row.role,
                row.display_name,
                row.location_kind,
                row.relative_path,
                row.external_path,
                row.byte_size,
                row.content_id,
                row.duration_us,
                row.width,
                row.height,
                row.fps_num,
                row.fps_den,
                row.container_start_us,
            )

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

    def resolve_media(self, asset_id: str) -> Path:
        with self._session() as session:
            row = self._asset(session, asset_id)
            if row.location_kind == "project":
                return self.root / (row.relative_path or "")
            return Path(row.external_path or "")

    def media_status(self, asset_id: str) -> str:
        path = self.resolve_media(asset_id)
        return "present" if path.is_file() else "missing"

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
                    word.start_us, word.end_us, word.confidence,
                ))
            return loaded

    def correct_word_text(self, word_id: str, text_value: str, *, scope_id: str) -> None:
        self._write_correction(WORD_TEXT, word_id, scope_id, text_value)

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
