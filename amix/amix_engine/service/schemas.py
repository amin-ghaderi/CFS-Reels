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
    container: str | None = None
    container_start_us: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    audio_channels: int | None = None
    channel_layout: str | None = None
    rotation_degrees: int | None = None
    probed_at: str | None = None
    source_media_asset_id: str | None = None
    proxy_state: str | None = None
    proxy_asset_id: str | None = None
    prepare_state: str = "preparing"
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


class WordAtTimeResponse(_Model):
    found: bool
    word_id: str | None = None
    sequence: int | None = None
    start_us: int | None = None
    end_us: int | None = None


class SpeechModelStatusResponse(_Model):
    state: str
    model_id: str | None = None
    display_name: str | None = None
    runtime: str | None = None
    message: str


class PlaybackResponse(_Model):
    source_media_asset_id: str
    playable: bool
    status: str
    warning: str | None = None
    playback_media_asset_id: str | None = None
    profile: str | None = None
    resolved_path: str | None = None
    playback_duration_us: int | None = None
    source_duration_us: int | None = None
    source_container_start_us: int | None = None
    proxy_container_start_us: int | None = None
    canonical_origin_us: int | None = None
    timestamp_policy: str | None = None
    byte_size: int | None = None
    file_mtime_ns: int | None = None
    container: str | None = None
    mime: str | None = None
    source_present: bool


class ParticipantResponse(_Model):
    participant_id: str
    display_name: str


class ParticipantNameRequest(_Model):
    display_name: str = Field(min_length=1)


class LayoutBindingResponse(_Model):
    binding_id: str
    participant_id: str
    start_us: int
    end_us: int
    x: int
    y: int
    w: int
    h: int
    coordinate_space: str


class LayoutBindingRequest(_Model):
    participant_id: str
    start_us: int
    end_us: int
    x: int
    y: int
    w: int
    h: int
    binding_id: str | None = None


class LayoutCandidatesRequest(_Model):
    time_us: int | None = None


class LayoutCandidateResponse(_Model):
    x: int
    y: int
    w: int
    h: int


class LayoutCandidatesResponse(_Model):
    picture_width: int
    picture_height: int
    candidates: list[LayoutCandidateResponse]


class ClusterSampleResponse(_Model):
    start_us: int
    end_us: int


class ClusterSummaryResponse(_Model):
    cluster_key: str
    segment_count: int
    voiced_us: int
    samples: list[ClusterSampleResponse]


class SpeakerAnalysisResponse(_Model):
    state: str
    participant_count: int
    transcript_run_id: str | None = None
    diarization_run_id: str | None = None
    assignment_run_id: str | None = None
    assignment_compatible: bool
    turns_run_id: str | None = None
    turns_match_assignment: bool
    source_present: bool
    clusters: list[ClusterSummaryResponse]
    previous_map: dict[str, str | None] | None = None
    profile_id: str
    cluster_count: int
    limitation: str


class ClusterMappingRequest(_Model):
    cluster_key: str
    participant_id: str | None = None


class ApplySpeakerMapRequest(_Model):
    diarization_run_id: str
    mappings: list[ClusterMappingRequest]


class ApplySpeakerMapResponse(_Model):
    assignment_run_id: str
    turns_run_id: str
    state: str


class OverlapRegionResponse(_Model):
    start_us: int
    end_us: int
    duration_us: int
    confidence: float
    participant_ids: list[str]


class OverlapStateResponse(_Model):
    run_id: str | None
    stale: bool
    window_start_us: int | None = None
    window_end_us: int | None = None
    profile_id: str | None = None
    regions: list[OverlapRegionResponse]


class MulticamReadinessResponse(_Model):
    turns_ready: bool
    overlap_ready: bool
    overlap_stale: bool
    layout_ready: bool
    plan_ready: bool
    plan_present: bool
    plan_stale: bool
    blocking_reason: str | None
    vision_state: str
    ffmpeg_ready: bool
    plan_start_us: int | None = None
    plan_end_us: int | None = None


class FullChoiceResponse(_Model):
    participant_id: str
    display_name: str


class ShotResponse(_Model):
    shot_id: str
    start_us: int
    end_us: int
    presentation: str
    participant_id: str | None = None
    participant_name: str | None = None
    reason: str
    automatic_presentation: str
    automatic_participant_id: str | None = None
    automatic_participant_name: str | None = None
    override_decision: str
    locked: bool
    overridden: bool
    full_choices: list[FullChoiceResponse]


class ShotPlanStateResponse(_Model):
    run_id: str | None
    stale: bool
    start_us: int | None = None
    end_us: int | None = None
    shots: list[ShotResponse]


class ShotOverrideRequest(_Model):
    shot_plan_run_id: str
    shot_id: str
    decision: str
    participant_id: str | None = None


class ExportResponse(_Model):
    job_id: str
    filename: str
    relative_path: str
    width: int | None = None
    height: int | None = None
    aspect: str | None = None
    preset_id: str | None = None
    visual_treatment: str | None = None
    sequence_id: str | None = None
    created_at: str | None = None
    status: str


class SequenceRenderReadinessResponse(_Model):
    source_program_ready: bool
    multicam_ready: bool
    source_program_reason: str | None = None
    multicam_reason: str | None = None
    ffmpeg_ready: bool


class TimelineClipResponse(_Model):
    clip_id: str
    order_index: int
    source_start_us: int
    source_end_us: int
    sequence_start_us: int | None = None


class TimelineRangeResponse(_Model):
    source_start_us: int
    source_end_us: int


class TimelineCameraResponse(_Model):
    shot_id: str
    source_start_us: int
    source_end_us: int
    presentation: str
    participant_name: str | None = None
    locked: bool


class TimelineResponse(_Model):
    sequence_id: str | None
    revision: int | None
    fingerprint: str | None
    source_start_us: int | None
    source_end_us: int | None
    duration_us: int | None
    clips: list[TimelineClipResponse]
    removed: list[TimelineRangeResponse]
    camera: list[TimelineCameraResponse]
    protected: list[TimelineRangeResponse]


class SplitClipRequest(_Model):
    sequence_id: str
    clip_id: str
    source_time_us: int


class ClipRequest(_Model):
    sequence_id: str
    clip_id: str


class ResetSequenceRequest(_Model):
    sequence_id: str


class ConversationThreadResponse(_Model):
    thread_id: str
    order_index: int
    first_turn_id: str
    last_turn_id: str
    first_word_id: str
    last_word_id: str
    title: str
    summary: str
    topic: str | None = None
    start_us: int
    end_us: int
    duration_us: int
    participant_names: list[str]


class ConversationStateResponse(_Model):
    transcript_present: bool
    turns_ready: bool
    blocking_reason: str | None = None
    provider_configured: bool
    provider_display_name: str | None = None
    provider_model_id: str | None = None
    provider_execution: str | None = None
    capability_ready: bool
    offline_blocked: bool
    network_mode: str
    local_ai_state: str | None = None
    map_present: bool
    map_stale: bool
    conversation_map_run_id: str | None = None
    threads: list[ConversationThreadResponse]


class ReelCandidateResponse(_Model):
    candidate_id: str
    order_index: int
    conversation_thread_id: str
    first_turn_id: str
    last_turn_id: str
    first_word_id: str
    last_word_id: str
    start_us: int
    end_us: int
    duration_us: int
    title: str
    summary: str
    hook: str
    thread_title: str | None = None
    participant_names: list[str]


class ReelClipResponse(_Model):
    clip_id: str
    order_index: int
    source_start_us: int
    source_end_us: int


class ReelDraftResponse(_Model):
    sequence_id: str
    display_name: str
    revision: int
    source_start_us: int
    source_end_us: int
    duration_us: int
    origin_candidate_id: str | None = None
    clips: list[ReelClipResponse]


class ReelStateResponse(_Model):
    transcript_present: bool
    turns_ready: bool
    blocking_reason: str | None = None
    provider_configured: bool
    capability_ready: bool
    offline_blocked: bool
    local_ai_state: str | None = None
    map_present: bool
    map_stale: bool
    discovery_present: bool
    discovery_stale: bool
    reel_discovery_run_id: str | None = None
    candidates: list[ReelCandidateResponse]
    dismissed_count: int = 0
    drafts: list[ReelDraftResponse]


class CreateReelDraftRequest(_Model):
    candidate_id: str


class SemanticProviderStatusResponse(_Model):
    configured: bool
    network_mode: str
    execution: str | None = None
    display_name: str | None = None
    model_id: str | None = None
    provider_id: str | None = None
    capability_ready: bool
    offline_blocked: bool
    reachable: bool | None = None
    readiness: str | None = None


class CaptionCueResponse(_Model):
    cue_id: str
    order_index: int
    first_word_id: str
    last_word_id: str
    source_start_us: int
    source_end_us: int
    sequence_start_us: int
    sequence_end_us: int
    generated_text: str
    manual_text: str | None = None
    effective_text: str


class CaptionStateResponse(_Model):
    sequence_id: str
    media_asset_id: str
    purpose: str
    status: str
    track_id: str | None = None
    revision: int | None = None
    profile: str | None = None
    transcript_analysis_run_id: str | None = None
    effective_text_fingerprint: str | None = None
    sequence_revision_at_generation: int | None = None
    stale_reasons: list[str]
    cues: list[CaptionCueResponse]


class CaptionTextRequest(_Model):
    text: str


class CaptionExportRequest(_Model):
    format: str


class CaptionExportResponse(_Model):
    export_id: str
    asset_id: str
    relative_path: str | None = None
    role: str | None = None
    source_media_asset_id: str
    sequence_id: str
    sequence_purpose: str
    sequence_revision: int
    sequence_fingerprint: str
    caption_track_id: str
    caption_track_revision: int
    transcript_analysis_run_id: str
    effective_text_fingerprint: str
    generation_profile: str
    format: str
    created_at: str
