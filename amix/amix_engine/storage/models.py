"""SQLAlchemy models for the per-project database.

Media times are integer microseconds. There is no binary column for picture or audio.
Generated analysis rows are inserted for a new run and are not updated in place.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


class ProjectRow(Base):
    __tablename__ = "project"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class MediaAssetRow(Base):
    __tablename__ = "media_asset"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    location_kind: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str | None] = mapped_column(Text)
    external_path: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_id: Mapped[str | None] = mapped_column(Text)
    content_id_kind: Mapped[str | None] = mapped_column(Text)
    duration_us: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps_num: Mapped[int | None] = mapped_column(Integer)
    fps_den: Mapped[int | None] = mapped_column(Integer)
    container_start_us: Mapped[int | None] = mapped_column(BigInteger)
    container: Mapped[str | None] = mapped_column(Text)
    video_codec: Mapped[str | None] = mapped_column(Text)
    audio_codec: Mapped[str | None] = mapped_column(Text)
    video_duration_us: Mapped[int | None] = mapped_column(BigInteger)
    audio_duration_us: Mapped[int | None] = mapped_column(BigInteger)
    duration_source: Mapped[str | None] = mapped_column(Text)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    audio_channels: Mapped[int | None] = mapped_column(Integer)
    channel_layout: Mapped[str | None] = mapped_column(Text)
    pixel_format: Mapped[str | None] = mapped_column(Text)
    r_fps_num: Mapped[int | None] = mapped_column(Integer)
    r_fps_den: Mapped[int | None] = mapped_column(Integer)
    time_base_num: Mapped[int | None] = mapped_column(Integer)
    time_base_den: Mapped[int | None] = mapped_column(Integer)
    rotation_degrees: Mapped[int | None] = mapped_column(Integer)
    bit_rate: Mapped[int | None] = mapped_column(BigInteger)
    video_start_us: Mapped[int | None] = mapped_column(BigInteger)
    audio_start_us: Mapped[int | None] = mapped_column(BigInteger)
    file_mtime_ns: Mapped[int | None] = mapped_column(BigInteger)
    probed_at: Mapped[str | None] = mapped_column(Text)
    probe_tool: Mapped[str | None] = mapped_column(Text)
    probe_config: Mapped[str | None] = mapped_column(Text)
    source_media_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_asset.id", ondelete="RESTRICT")
    )
    proxy_profile: Mapped[str | None] = mapped_column(Text)
    proxy_tool: Mapped[str | None] = mapped_column(Text)
    proxy_job_id: Mapped[str | None] = mapped_column(Text)
    proxy_source_size: Mapped[int | None] = mapped_column(BigInteger)
    proxy_source_mtime_ns: Mapped[int | None] = mapped_column(BigInteger)
    proxy_created_at: Mapped[str | None] = mapped_column(Text)
    timestamp_policy: Mapped[str | None] = mapped_column(Text)


class ParticipantRow(Base):
    __tablename__ = "participant"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class LayoutBindingRow(Base):
    __tablename__ = "layout_binding"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participant.id", ondelete="RESTRICT"), nullable=False)
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    w: Mapped[int] = mapped_column(Integer, nullable=False)
    h: Mapped[int] = mapped_column(Integer, nullable=False)


class AnalysisRunRow(Base):
    __tablename__ = "analysis_run"
    __table_args__ = (
        UniqueConstraint("id", "media_asset_id", "kind", name="uq_run_asset_kind"),
        Index("ix_analysis_run_asset_kind", "media_asset_id", "kind"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_id: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    window_start_us: Mapped[int | None] = mapped_column(BigInteger)
    window_end_us: Mapped[int | None] = mapped_column(BigInteger)
    input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AnalysisDependencyRow(Base):
    __tablename__ = "analysis_dependency"
    __table_args__ = (
        UniqueConstraint("run_id", "depends_on_run_id", name="uq_run_dependency"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False)
    depends_on_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False)


class TranscriptRow(Base):
    __tablename__ = "transcript"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), unique=True, nullable=False)
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False)
    language: Mapped[str | None] = mapped_column(Text)


class WordRow(Base):
    __tablename__ = "word"
    __table_args__ = (
        Index("ix_word_transcript_sequence", "transcript_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcript.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    segment_ref: Mapped[str | None] = mapped_column(Text)


class DiarizationSegmentRow(Base):
    __tablename__ = "diarization_segment"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "sequence", name="uq_diarization_sequence"),
        Index("ix_diarization_segment_run", "analysis_run_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    cluster_key: Mapped[str] = mapped_column(Text, nullable=False)
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SpeakerAssignmentRow(Base):
    __tablename__ = "participant_assignment"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "word_id", name="uq_assignment_word"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False)
    word_id: Mapped[str] = mapped_column(ForeignKey("word.id", ondelete="RESTRICT"), nullable=False)
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("participant.id", ondelete="RESTRICT"))


class TurnRow(Base):
    __tablename__ = "turn"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "turn_key", name="uq_turn_key"),
        Index("ix_turn_run", "analysis_run_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False)
    turn_key: Mapped[str] = mapped_column(Text, nullable=False)
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("participant.id", ondelete="RESTRICT"))
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TurnWordRow(Base):
    __tablename__ = "turn_word"
    __table_args__ = (
        UniqueConstraint("turn_id", "sequence", name="uq_turn_word_sequence"),
    )

    turn_id: Mapped[str] = mapped_column(ForeignKey("turn.id", ondelete="RESTRICT"), primary_key=True)
    word_id: Mapped[str] = mapped_column(ForeignKey("word.id", ondelete="RESTRICT"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class OverlapRegionRow(Base):
    __tablename__ = "overlap_region"
    __table_args__ = (
        Index("ix_overlap_run", "analysis_run_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False)
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class OverlapParticipantRow(Base):
    __tablename__ = "overlap_participant"

    region_id: Mapped[str] = mapped_column(ForeignKey("overlap_region.id", ondelete="RESTRICT"), primary_key=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participant.id", ondelete="RESTRICT"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class ProtectedRegionRow(Base):
    __tablename__ = "protected_region"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_asset.id", ondelete="RESTRICT"), nullable=False)
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class ShotPlanRow(Base):
    __tablename__ = "shot_plan"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"), unique=True, nullable=False)
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ShotRow(Base):
    __tablename__ = "shot"
    __table_args__ = (
        UniqueConstraint("shot_plan_id", "sequence", name="uq_shot_sequence"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    shot_plan_id: Mapped[str] = mapped_column(ForeignKey("shot_plan.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    presentation: Mapped[str] = mapped_column(Text, nullable=False)
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("participant.id", ondelete="RESTRICT"))
    floor_participant_id: Mapped[str | None] = mapped_column(ForeignKey("participant.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class ActiveAnalysisRow(Base):
    __tablename__ = "active_analysis"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_run_id", "media_asset_id", "kind"],
            ["analysis_run.id", "analysis_run.media_asset_id", "analysis_run.kind"],
            name="fk_active_run_asset_kind",
            ondelete="RESTRICT",
        ),
    )

    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_asset.id", ondelete="RESTRICT"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    activated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ManualCorrectionRow(Base):
    """Overlay on generated rows. Never updates those rows."""

    __tablename__ = "manual_correction"
    __table_args__ = (
        UniqueConstraint("kind", "target_id", name="uq_correction_target"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())


_JOB_STATUSES = (
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "INTERRUPTED",
)


class ProcessingJobRow(Base):
    """Execution record. Domain results stay on analysis tables."""

    __tablename__ = "processing_job"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in _JOB_STATUSES) + ")",
            name="ck_job_status",
        ),
        CheckConstraint("progress_bp >= 0 AND progress_bp <= 10000", name="ck_job_progress"),
        CheckConstraint("cancel_requested IN (0, 1)", name="ck_job_cancel"),
        CheckConstraint("attempt >= 1", name="ck_job_attempt"),
        Index("ix_processing_job_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    media_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_asset.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    progress_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spec_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resumed_from_job_id: Mapped[str | None] = mapped_column(ForeignKey("processing_job.id", ondelete="RESTRICT"))
    interrupt_reason: Mapped[str | None] = mapped_column(Text)
