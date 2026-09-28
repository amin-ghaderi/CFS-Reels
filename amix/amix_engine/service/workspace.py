"""Media and transcript routes. Probe and proxy work runs as jobs, not in the request."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Request

from amix.amix_engine.editorial.sequence import (
    SequenceRejected,
    create_sequence,
    remove_clip,
    reset_sequence,
    split_clip,
    timeline_snapshot,
)
from amix.amix_engine.layout import COORDINATE_SPACE, LayoutRejected, validate_layout
from amix.amix_engine.multicam.effective import OverrideRejected, describe_shots, set_shot_override
from amix.amix_engine.multicam.profile import PRESETS
from amix.amix_engine.playback import PlaybackDescriptor, resolve_playback
from amix.amix_engine.service.errors import ApiError
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.service.schemas import (
    ApplySpeakerMapRequest,
    ApplySpeakerMapResponse,
    ClusterSampleResponse,
    ClusterSummaryResponse,
    LayoutBindingRequest,
    LayoutBindingResponse,
    LinkMediaRequest,
    MediaResponse,
    MediaStatusResponse,
    ParticipantNameRequest,
    ParticipantResponse,
    PlaybackResponse,
    RelinkMediaRequest,
    SpeakerAnalysisResponse,
    TranscriptResponse,
    TranscriptWordPage,
    TranscriptWordResponse,
    WordAtTimeResponse,
    WordTextRequest,
    MulticamReadinessResponse,
    OverlapRegionResponse,
    OverlapStateResponse,
    ExportResponse,
    ShotOverrideRequest,
    ShotPlanStateResponse,
    ShotResponse,
    SplitClipRequest,
    ClipRequest,
    ResetSequenceRequest,
    TimelineResponse,
)
from amix.amix_engine.speakers import SpeakerMapRejected, apply_cluster_map, speaker_status
from amix.amix_engine.jobs.media import proxy_state
from amix.amix_engine.multicam.apply import multicam_readiness
from amix.amix_engine.storage.errors import NoActiveTranscript
from amix.amix_engine.storage.kinds import DEFAULT_MEDIA_ROLE, MEDIA_ROLES, WORD_PAGE_LIMIT
from amix.amix_engine.storage.project import ProjectStore, StoredMedia, TranscriptWordView


def register_workspace_routes(app: FastAPI, runtime: EngineRuntime, authorize, call) -> None:
    @app.get("/v1/projects/{handle}/media", response_model=list[MediaResponse])
    def list_media(handle: str, request: Request) -> list[MediaResponse]:
        authorize(request)
        return call(lambda: _listed(runtime, handle))

    @app.post("/v1/projects/{handle}/media", response_model=MediaResponse)
    def link_media(handle: str, body: LinkMediaRequest, request: Request) -> MediaResponse:
        authorize(request)
        return call(lambda: _link(runtime, handle, body.path, body.role))

    @app.get("/v1/projects/{handle}/media/{asset_id}", response_model=MediaResponse)
    def get_media(handle: str, asset_id: str, request: Request) -> MediaResponse:
        authorize(request)
        return call(lambda: _one(runtime, handle, asset_id))

    @app.get("/v1/projects/{handle}/media/{asset_id}/status", response_model=MediaStatusResponse)
    def media_status(handle: str, asset_id: str, request: Request) -> MediaStatusResponse:
        authorize(request)
        return call(lambda: _status(runtime, handle, asset_id))

    @app.post("/v1/projects/{handle}/media/{asset_id}/relink", response_model=MediaResponse)
    def relink_media(handle: str, asset_id: str, body: RelinkMediaRequest, request: Request) -> MediaResponse:
        authorize(request)
        return call(lambda: _relink(runtime, handle, asset_id, body.path))

    @app.get("/v1/projects/{handle}/media/{asset_id}/transcript", response_model=TranscriptResponse)
    def active_transcript(handle: str, asset_id: str, request: Request) -> TranscriptResponse:
        authorize(request)
        return call(lambda: _transcript(runtime, handle, asset_id))

    @app.get(
        "/v1/projects/{handle}/media/{asset_id}/transcript/words/{offset}/{limit}",
        response_model=TranscriptWordPage,
    )
    def transcript_words(handle: str, asset_id: str, offset: int, limit: int, request: Request) -> TranscriptWordPage:
        authorize(request)
        return call(lambda: _words(runtime, handle, asset_id, offset, limit))

    @app.get(
        "/v1/projects/{handle}/media/{asset_id}/transcript/word-at/{time_us}",
        response_model=WordAtTimeResponse,
    )
    def word_at_time(handle: str, asset_id: str, time_us: str, request: Request) -> WordAtTimeResponse:
        authorize(request)
        return call(lambda: _word_at(runtime, handle, asset_id, time_us))

    @app.get("/v1/projects/{handle}/media/{asset_id}/playback", response_model=PlaybackResponse)
    def playback(handle: str, asset_id: str, request: Request) -> PlaybackResponse:
        authorize(request)
        return call(lambda: _playback(runtime, handle, asset_id))

    @app.post("/v1/projects/{handle}/media/{asset_id}/words/{word_id}/text", response_model=TranscriptWordResponse)
    def correct_word(handle: str, asset_id: str, word_id: str, body: WordTextRequest, request: Request) -> TranscriptWordResponse:
        authorize(request)
        return call(lambda: _correct(runtime, handle, asset_id, word_id, body.text))

    @app.post("/v1/projects/{handle}/media/{asset_id}/words/{word_id}/text/clear", response_model=TranscriptWordResponse)
    def clear_word(handle: str, asset_id: str, word_id: str, request: Request) -> TranscriptWordResponse:
        authorize(request)
        return call(lambda: _clear(runtime, handle, asset_id, word_id))

    @app.get("/v1/projects/{handle}/participants", response_model=list[ParticipantResponse])
    def list_participants(handle: str, request: Request) -> list[ParticipantResponse]:
        authorize(request)
        return call(lambda: _participants(runtime, handle))

    @app.post("/v1/projects/{handle}/participants", response_model=ParticipantResponse)
    def create_participant(handle: str, body: ParticipantNameRequest, request: Request) -> ParticipantResponse:
        authorize(request)
        return call(lambda: _create_participant(runtime, handle, body.display_name))

    @app.post("/v1/projects/{handle}/participants/{participant_id}/rename", response_model=ParticipantResponse)
    def rename_participant(
        handle: str, participant_id: str, body: ParticipantNameRequest, request: Request,
    ) -> ParticipantResponse:
        authorize(request)
        return call(lambda: _rename_participant(runtime, handle, participant_id, body.display_name))

    @app.get("/v1/projects/{handle}/media/{asset_id}/layout", response_model=list[LayoutBindingResponse])
    def list_layout(handle: str, asset_id: str, request: Request) -> list[LayoutBindingResponse]:
        authorize(request)
        return call(lambda: _layout(runtime, handle, asset_id))

    @app.post("/v1/projects/{handle}/media/{asset_id}/layout", response_model=LayoutBindingResponse)
    def add_layout(handle: str, asset_id: str, body: LayoutBindingRequest, request: Request) -> LayoutBindingResponse:
        authorize(request)
        return call(lambda: _add_layout(runtime, handle, asset_id, body))

    @app.get("/v1/projects/{handle}/media/{asset_id}/speaker-analysis", response_model=SpeakerAnalysisResponse)
    def describe_speakers(handle: str, asset_id: str, request: Request) -> SpeakerAnalysisResponse:
        authorize(request)
        return call(lambda: _describe_speakers(runtime, handle, asset_id))

    @app.post("/v1/projects/{handle}/media/{asset_id}/speaker-map", response_model=ApplySpeakerMapResponse)
    def apply_speaker_map(
        handle: str, asset_id: str, body: ApplySpeakerMapRequest, request: Request,
    ) -> ApplySpeakerMapResponse:
        authorize(request)
        return call(lambda: _apply_map(runtime, handle, asset_id, body))

    @app.get("/v1/projects/{handle}/media/{asset_id}/overlap", response_model=OverlapStateResponse)
    def overlap_state(handle: str, asset_id: str, request: Request) -> OverlapStateResponse:
        authorize(request)
        return call(lambda: _overlap_state(runtime, handle, asset_id))

    @app.get("/v1/projects/{handle}/media/{asset_id}/multicam", response_model=MulticamReadinessResponse)
    def multicam_state(handle: str, asset_id: str, request: Request) -> MulticamReadinessResponse:
        authorize(request)
        return call(lambda: _multicam_state(runtime, handle, asset_id))

    @app.get("/v1/projects/{handle}/media/{asset_id}/shot-plan", response_model=ShotPlanStateResponse)
    def shot_plan_state(handle: str, asset_id: str, request: Request) -> ShotPlanStateResponse:
        authorize(request)
        return call(lambda: _shot_plan_state(runtime, handle, asset_id))

    @app.post("/v1/projects/{handle}/media/{asset_id}/shot-overrides", response_model=ShotPlanStateResponse)
    def save_shot_override(handle: str, asset_id: str, body: ShotOverrideRequest, request: Request) -> ShotPlanStateResponse:
        authorize(request)
        return call(lambda: _save_override(runtime, handle, asset_id, body))

    @app.get("/v1/projects/{handle}/media/{asset_id}/exports", response_model=list[ExportResponse])
    def list_exports(handle: str, asset_id: str, request: Request) -> list[ExportResponse]:
        authorize(request)
        return call(lambda: _exports(runtime, handle, asset_id))

    @app.get("/v1/projects/{handle}/media/{asset_id}/timeline", response_model=TimelineResponse)
    def timeline_state(handle: str, asset_id: str, request: Request) -> TimelineResponse:
        authorize(request)
        return call(lambda: _timeline(runtime, handle, asset_id))

    @app.post("/v1/projects/{handle}/media/{asset_id}/sequence", response_model=TimelineResponse)
    def create_edit(handle: str, asset_id: str, request: Request) -> TimelineResponse:
        authorize(request)
        return call(lambda: _create_edit(runtime, handle, asset_id))

    @app.post("/v1/projects/{handle}/media/{asset_id}/sequence/split", response_model=TimelineResponse)
    def split_sequence_clip(handle: str, asset_id: str, body: SplitClipRequest, request: Request) -> TimelineResponse:
        authorize(request)
        return call(lambda: _split_edit(runtime, handle, asset_id, body))

    @app.post("/v1/projects/{handle}/media/{asset_id}/sequence/remove", response_model=TimelineResponse)
    def remove_sequence_clip(handle: str, asset_id: str, body: ClipRequest, request: Request) -> TimelineResponse:
        authorize(request)
        return call(lambda: _remove_edit(runtime, handle, asset_id, body))

    @app.post("/v1/projects/{handle}/media/{asset_id}/sequence/reset", response_model=TimelineResponse)
    def reset_edit(handle: str, asset_id: str, body: ResetSequenceRequest, request: Request) -> TimelineResponse:
        authorize(request)
        return call(lambda: _reset_edit(runtime, handle, asset_id, body))


def _store(runtime: EngineRuntime, handle: str) -> ProjectStore:
    return runtime.session(handle).store


def _link(runtime: EngineRuntime, handle: str, path: str, role: str) -> MediaResponse:
    store = _store(runtime, handle)
    chosen = _existing_file(path)
    if role not in MEDIA_ROLES:
        raise ApiError(400, "invalid_media_role", "media role is not recognized")
    stat = chosen.stat()
    asset_id = store.add_media_asset(
        display_name=chosen.name,
        role=role or DEFAULT_MEDIA_ROLE,
        location_kind="external",
        external_path=str(chosen),
        byte_size=stat.st_size,
        file_mtime_ns=stat.st_mtime_ns,
    )
    return _media_view(store, store.get_media(asset_id))


def _relink(runtime: EngineRuntime, handle: str, asset_id: str, path: str) -> MediaResponse:
    store = _store(runtime, handle)
    chosen = _existing_file(path)
    stat = chosen.stat()
    asset = store.relink_external(
        asset_id,
        str(chosen),
        byte_size=stat.st_size,
        display_name=chosen.name,
        file_mtime_ns=stat.st_mtime_ns,
    )
    return _media_view(store, asset)


def _one(runtime: EngineRuntime, handle: str, asset_id: str) -> MediaResponse:
    store = _store(runtime, handle)
    return _media_view(store, store.get_media(asset_id))


def _status(runtime: EngineRuntime, handle: str, asset_id: str) -> MediaStatusResponse:
    store = _store(runtime, handle)
    return MediaStatusResponse(asset_id=asset_id, status=store.media_status(asset_id))


def _transcript(runtime: EngineRuntime, handle: str, asset_id: str) -> TranscriptResponse:
    described = _store(runtime, handle).active_transcript(asset_id)
    if described is None:
        return TranscriptResponse(active=False, media_asset_id=asset_id)
    return TranscriptResponse(
        active=True,
        transcript_id=described.transcript_id,
        analysis_run_id=described.analysis_run_id,
        media_asset_id=described.media_asset_id,
        language=described.language,
        word_count=described.word_count,
    )


def _words(runtime: EngineRuntime, handle: str, asset_id: str, offset: int, limit: int) -> TranscriptWordPage:
    if offset < 0 or limit < 1 or limit > WORD_PAGE_LIMIT:
        raise ApiError(400, "invalid_word_page", "word page is out of range")
    store = _store(runtime, handle)
    described, words = store.page_active_words(asset_id, offset, limit)
    return TranscriptWordPage(
        offset=offset,
        limit=limit,
        word_count=described.word_count,
        words=[_word_view(word) for word in words],
    )


def _word_at(runtime: EngineRuntime, handle: str, asset_id: str, time_us: str) -> WordAtTimeResponse:
    if not time_us.isdigit():
        raise ApiError(400, "invalid_time", "time is out of range")
    value = int(time_us)
    if value > 2**63 - 1:
        raise ApiError(400, "invalid_time", "time is out of range")
    hit = _store(runtime, handle).word_at_time(asset_id, value)
    if hit is None:
        return WordAtTimeResponse(found=False)
    return WordAtTimeResponse(
        found=True,
        word_id=hit.word_id,
        sequence=hit.sequence,
        start_us=hit.start_us,
        end_us=hit.end_us,
    )


def _playback(runtime: EngineRuntime, handle: str, asset_id: str) -> PlaybackResponse:
    return _playback_view(resolve_playback(_store(runtime, handle), asset_id))


def _playback_view(described: PlaybackDescriptor) -> PlaybackResponse:
    return PlaybackResponse(
        source_media_asset_id=described.source_media_asset_id,
        playable=described.playable,
        status=described.status,
        warning=described.warning,
        playback_media_asset_id=described.playback_media_asset_id,
        profile=described.profile,
        resolved_path=described.resolved_path,
        playback_duration_us=described.playback_duration_us,
        source_duration_us=described.source_duration_us,
        source_container_start_us=described.source_container_start_us,
        proxy_container_start_us=described.proxy_container_start_us,
        canonical_origin_us=described.canonical_origin_us,
        timestamp_policy=described.timestamp_policy,
        byte_size=described.byte_size,
        file_mtime_ns=described.file_mtime_ns,
        container=described.container,
        mime=described.mime,
        source_present=described.source_present,
    )


def _correct(runtime: EngineRuntime, handle: str, asset_id: str, word_id: str, text: str) -> TranscriptWordResponse:
    store = _store(runtime, handle)
    described = store.active_transcript(asset_id)
    if described is None:
        raise NoActiveTranscript(asset_id)
    cleaned = text.strip()
    if not cleaned:
        raise ApiError(400, "invalid_word_text", "word text cannot be blank")
    store.correct_word_text(word_id, cleaned, scope_id=described.analysis_run_id)
    return _word_view(store.active_word_view(asset_id, word_id))


def _clear(runtime: EngineRuntime, handle: str, asset_id: str, word_id: str) -> TranscriptWordResponse:
    store = _store(runtime, handle)
    if store.active_transcript(asset_id) is None:
        raise NoActiveTranscript(asset_id)
    store.clear_word_text(word_id)
    return _word_view(store.active_word_view(asset_id, word_id))


def _existing_file(path: str) -> Path:
    try:
        chosen = Path(path)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "invalid_media_path", "choose an existing media file") from exc
    if not chosen.is_absolute() or not chosen.is_file():
        raise ApiError(400, "invalid_media_path", "choose an existing media file")
    if not chosen.name or chosen.name in {".", ".."}:
        raise ApiError(400, "invalid_media_path", "choose an existing media file")
    return chosen


def _listed(runtime: EngineRuntime, handle: str) -> list[MediaResponse]:
    store = _store(runtime, handle)
    jobs = store.list_processing_jobs()
    return [_media_view(store, asset, jobs) for asset in store.list_media_assets()]


def _media_view(store: ProjectStore, asset: StoredMedia, jobs: list | None = None) -> MediaResponse:
    job_rows = store.list_processing_jobs() if jobs is None else jobs
    derivative = None if asset.role == "proxy" else store.find_proxy(asset.asset_id)
    source_size, source_mtime = store.observed_file(asset.asset_id)
    proxy_present = derivative is not None and store.media_status(derivative.asset_id) == "present"
    return MediaResponse(
        asset_id=asset.asset_id,
        role=asset.role,
        display_name=asset.display_name,
        location_kind=asset.location_kind,
        relative_path=asset.relative_path,
        external_path=asset.external_path,
        byte_size=asset.byte_size,
        duration_us=asset.duration_us,
        width=asset.width,
        height=asset.height,
        fps_num=asset.fps_num,
        fps_den=asset.fps_den,
        container=asset.container,
        container_start_us=asset.container_start_us,
        video_codec=asset.video_codec,
        audio_codec=asset.audio_codec,
        sample_rate=asset.sample_rate,
        audio_channels=asset.audio_channels,
        channel_layout=asset.channel_layout,
        rotation_degrees=asset.rotation_degrees,
        probed_at=asset.probed_at,
        source_media_asset_id=asset.source_media_asset_id,
        proxy_state=proxy_state(
            asset,
            derivative,
            job_rows,
            source_size=source_size,
            source_mtime_ns=source_mtime,
            proxy_file_present=proxy_present,
        ),
        proxy_asset_id=None if derivative is None else derivative.asset_id,
        status=store.media_status(asset.asset_id),
    )


def _word_view(word: TranscriptWordView) -> TranscriptWordResponse:
    return TranscriptWordResponse(
        word_id=word.word_id,
        sequence=word.sequence,
        effective_text=word.effective_text,
        machine_text=word.machine_text,
        start_us=word.start_us,
        end_us=word.end_us,
        confidence=word.confidence,
        text_corrected=word.text_corrected,
        participant_id=word.participant_id,
        participant_name=word.participant_name,
    )


_LIMITATION = (
    "This profile separates exactly three anonymous clusters. "
    "It does not identify people, and it does not support another speaker count."
)


def _display_name(value: str) -> str:
    text = value.strip()
    if not text or len(text) > 80:
        raise ApiError(400, "invalid_participant_name", "Enter a participant name.")
    return text


def _participants(runtime: EngineRuntime, handle: str) -> list[ParticipantResponse]:
    store = _store(runtime, handle)
    return [
        ParticipantResponse(participant_id=item_id, display_name=name)
        for item_id, name, _order in store.list_participants()
    ]


def _create_participant(runtime: EngineRuntime, handle: str, display_name: str) -> ParticipantResponse:
    store = _store(runtime, handle)
    name = _display_name(display_name)
    participant_id = str(uuid.uuid4())
    order = len(store.list_participants())
    store.add_participant(participant_id, name, sort_order=order)
    return ParticipantResponse(participant_id=participant_id, display_name=name)


def _rename_participant(
    runtime: EngineRuntime, handle: str, participant_id: str, display_name: str,
) -> ParticipantResponse:
    store = _store(runtime, handle)
    name = _display_name(display_name)
    try:
        store.rename_participant(participant_id, name)
    except Exception as exc:
        message = str(exc)
        if message.startswith("unknown participant"):
            raise ApiError(404, "unknown_participant", "That participant is not in this project.") from exc
        raise
    return ParticipantResponse(participant_id=participant_id, display_name=name)


def _layout(runtime: EngineRuntime, handle: str, asset_id: str) -> list[LayoutBindingResponse]:
    store = _store(runtime, handle)
    names = {item_id: name for item_id, name, _order in store.list_participants()}
    rows = []
    for record in store.list_layout_records(asset_id):
        if record["participant_id"] not in names:
            continue
        rows.append(_layout_view(record))
    return rows


def _add_layout(runtime: EngineRuntime, handle: str, asset_id: str, body: LayoutBindingRequest) -> LayoutBindingResponse:
    store = _store(runtime, handle)
    asset = store.get_media(asset_id)
    known = {item_id for item_id, _name, _order in store.list_participants()}
    if body.participant_id not in known:
        raise ApiError(404, "unknown_participant", "That participant is not in this project.")
    try:
        binding = validate_layout(
            participant_id=body.participant_id,
            start_us=body.start_us,
            end_us=body.end_us,
            x=body.x,
            y=body.y,
            w=body.w,
            h=body.h,
            picture_width=asset.width,
            picture_height=asset.height,
        )
    except LayoutRejected as exc:
        raise ApiError(400, exc.code, str(exc)) from exc
    binding_id = store.add_layout_binding(asset_id, binding)
    saved = next(row for row in store.list_layout_records(asset_id) if row["binding_id"] == binding_id)
    return _layout_view(saved)


def _layout_view(record: dict) -> LayoutBindingResponse:
    return LayoutBindingResponse(
        binding_id=record["binding_id"],
        participant_id=record["participant_id"],
        start_us=record["start_us"],
        end_us=record["end_us"],
        x=record["x"],
        y=record["y"],
        w=record["w"],
        h=record["h"],
        coordinate_space=COORDINATE_SPACE,
    )


def _describe_speakers(runtime: EngineRuntime, handle: str, asset_id: str) -> SpeakerAnalysisResponse:
    store = _store(runtime, handle)
    store.get_media(asset_id)
    status = speaker_status(store, asset_id)
    return _speaker_view(status)


def _apply_map(runtime: EngineRuntime, handle: str, asset_id: str, body: ApplySpeakerMapRequest) -> ApplySpeakerMapResponse:
    store = _store(runtime, handle)
    store.get_media(asset_id)
    mapping = {item.cluster_key: item.participant_id for item in body.mappings}
    if len(mapping) != len(body.mappings):
        raise ApiError(400, "incomplete_cluster_map", "Map every cluster, including Unknown.")
    try:
        assignment_id, turn_id = apply_cluster_map(store, asset_id, body.diarization_run_id, mapping)
    except SpeakerMapRejected as exc:
        status = 404 if exc.code in {"no_active_transcript", "unknown_diarization", "unknown_participant"} else 400
        raise ApiError(status, exc.code, exc.message) from exc
    status = speaker_status(store, asset_id)
    return ApplySpeakerMapResponse(
        assignment_run_id=assignment_id,
        turns_run_id=turn_id,
        state=status["state"],
    )


def _speaker_view(status: dict) -> SpeakerAnalysisResponse:
    return SpeakerAnalysisResponse(
        state=status["state"],
        participant_count=status["participant_count"],
        transcript_run_id=status["transcript_run_id"],
        diarization_run_id=status["diarization_run_id"],
        assignment_run_id=status["assignment_run_id"],
        assignment_compatible=status["assignment_compatible"],
        turns_run_id=status["turns_run_id"],
        turns_match_assignment=status["turns_match_assignment"],
        source_present=status["source_present"],
        clusters=[
            ClusterSummaryResponse(
                cluster_key=item["cluster_key"],
                segment_count=item["segment_count"],
                voiced_us=item["voiced_us"],
                samples=[ClusterSampleResponse(**sample) for sample in item["samples"]],
            )
            for item in status["clusters"]
        ],
        previous_map=status["previous_map"],
        profile_id=status["profile_id"],
        cluster_count=status["cluster_count"],
        limitation=_LIMITATION,
    )


def _multicam_state(runtime: EngineRuntime, handle: str, asset_id: str) -> MulticamReadinessResponse:
    ready = multicam_readiness(_store(runtime, handle), asset_id)
    return MulticamReadinessResponse(
        turns_ready=ready["turns_ready"],
        overlap_ready=ready["overlap_ready"],
        overlap_stale=ready["overlap_stale"],
        layout_ready=ready["layout_ready"],
        plan_ready=ready["plan_ready"],
        plan_present=ready["plan_present"],
        plan_stale=ready["plan_stale"],
        blocking_reason=ready["blocking_reason"],
        vision_state=ready["vision_state"],
        ffmpeg_ready=ready["ffmpeg_ready"],
        plan_start_us=ready["plan_start_us"],
        plan_end_us=ready["plan_end_us"],
    )


def _overlap_state(runtime: EngineRuntime, handle: str, asset_id: str) -> OverlapStateResponse:
    store = _store(runtime, handle)
    ready = multicam_readiness(store, asset_id)
    run_id = ready["overlap_run_id"]
    if run_id is None:
        return OverlapStateResponse(run_id=None, stale=False, regions=[])
    record = store.analysis_record(run_id)
    return OverlapStateResponse(
        run_id=run_id,
        stale=ready["overlap_stale"],
        window_start_us=record["window_start_us"],
        window_end_us=record["window_end_us"],
        profile_id=record["config"].get("profile_id"),
        regions=[
            OverlapRegionResponse(
                start_us=region.start_us,
                end_us=region.end_us,
                duration_us=region.end_us - region.start_us,
                confidence=region.confidence,
                participant_ids=[person.value for person in region.participant_ids],
            )
            for region in store.load_overlaps(run_id)
        ],
    )


def _shot_plan_state(runtime: EngineRuntime, handle: str, asset_id: str) -> ShotPlanStateResponse:
    described = describe_shots(_store(runtime, handle), asset_id)
    return _shot_plan_view(described)


def _save_override(
    runtime: EngineRuntime, handle: str, asset_id: str, body: ShotOverrideRequest,
) -> ShotPlanStateResponse:
    store = _store(runtime, handle)
    try:
        set_shot_override(
            store, asset_id, body.shot_plan_run_id, body.shot_id, body.decision, body.participant_id,
        )
    except OverrideRejected as exc:
        status = 404 if exc.code in {"unknown_shot", "unknown_shot_plan", "unknown_participant"} else 400
        raise ApiError(status, exc.code, exc.message) from exc
    return _shot_plan_view(describe_shots(store, asset_id))


def _shot_plan_view(described: dict) -> ShotPlanStateResponse:
    return ShotPlanStateResponse(
        run_id=described["run_id"],
        stale=described["stale"],
        start_us=described["start_us"],
        end_us=described["end_us"],
        shots=[
            ShotResponse(
                shot_id=shot["shot_id"],
                start_us=shot["start_us"],
                end_us=shot["end_us"],
                presentation=shot["presentation"],
                participant_id=shot["participant_id"],
                participant_name=shot["participant_name"],
                reason=shot["reason"],
                automatic_presentation=shot["automatic_presentation"],
                automatic_participant_id=shot["automatic_participant_id"],
                automatic_participant_name=shot["automatic_participant_name"],
                override_decision=shot["override_decision"],
                locked=shot["locked"],
                overridden=shot["overridden"],
                full_choices=shot["full_choices"],
            )
            for shot in described["shots"]
        ],
    )


def _exports(runtime: EngineRuntime, handle: str, asset_id: str) -> list[ExportResponse]:
    store = _store(runtime, handle)
    store.get_media(asset_id)
    rows = []
    for job in store.list_processing_jobs():
        if job.kind != "render_multicam" or job.media_asset_id != asset_id:
            continue
        if job.status != "succeeded" or not isinstance(job.result, dict):
            continue
        preset_id = job.result.get("preset_id")
        preset = PRESETS.get(preset_id) if isinstance(preset_id, str) else None
        relative = job.result.get("relative_path")
        rows.append(ExportResponse(
            job_id=job.job_id,
            filename=str(relative).rsplit("/", 1)[-1] if isinstance(relative, str) else job.job_id,
            relative_path=relative if isinstance(relative, str) else "",
            width=job.result.get("width"),
            height=job.result.get("height"),
            aspect=None if preset is None else preset.aspect,
            preset_id=preset_id if isinstance(preset_id, str) else None,
            created_at=job.finished_at,
            status=job.status,
        ))
    return rows


def _timeline(runtime: EngineRuntime, handle: str, asset_id: str) -> TimelineResponse:
    store = _store(runtime, handle)
    store.get_media(asset_id)
    return TimelineResponse.model_validate(timeline_snapshot(store, asset_id))


def _create_edit(runtime: EngineRuntime, handle: str, asset_id: str) -> TimelineResponse:
    store = _store(runtime, handle)
    try:
        create_sequence(store, asset_id)
    except SequenceRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return _timeline(runtime, handle, asset_id)


def _split_edit(runtime: EngineRuntime, handle: str, asset_id: str, body: SplitClipRequest) -> TimelineResponse:
    store = _store(runtime, handle)
    _sequence_asset(store, asset_id, body.sequence_id)
    try:
        split_clip(store, body.sequence_id, body.clip_id, body.source_time_us)
    except SequenceRejected as exc:
        status = 404 if exc.code in {"unknown_clip", "unknown_sequence"} else 400
        raise ApiError(status, exc.code, exc.message) from exc
    return _timeline(runtime, handle, asset_id)


def _remove_edit(runtime: EngineRuntime, handle: str, asset_id: str, body: ClipRequest) -> TimelineResponse:
    store = _store(runtime, handle)
    _sequence_asset(store, asset_id, body.sequence_id)
    try:
        remove_clip(store, body.sequence_id, body.clip_id)
    except SequenceRejected as exc:
        status = 404 if exc.code in {"unknown_clip", "unknown_sequence"} else 400
        raise ApiError(status, exc.code, exc.message) from exc
    return _timeline(runtime, handle, asset_id)


def _reset_edit(runtime: EngineRuntime, handle: str, asset_id: str, body: ResetSequenceRequest) -> TimelineResponse:
    store = _store(runtime, handle)
    _sequence_asset(store, asset_id, body.sequence_id)
    try:
        reset_sequence(store, body.sequence_id)
    except SequenceRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return _timeline(runtime, handle, asset_id)


def _sequence_asset(store, asset_id: str, sequence_id: str) -> None:
    current = store.load_editorial_sequence(asset_id)
    if current is None or current["sequence_id"] != sequence_id:
        raise ApiError(404, "unknown_sequence", "That sequence is not in this project.")

