"""Media and transcript routes. Probe and proxy work runs as jobs, not in the request."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request

from amix.amix_engine.playback import PlaybackDescriptor, resolve_playback
from amix.amix_engine.service.errors import ApiError
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.service.schemas import (
    LinkMediaRequest,
    MediaResponse,
    MediaStatusResponse,
    PlaybackResponse,
    RelinkMediaRequest,
    TranscriptResponse,
    TranscriptWordPage,
    TranscriptWordResponse,
    WordAtTimeResponse,
    WordTextRequest,
)
from amix.amix_engine.jobs.media import proxy_state
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
