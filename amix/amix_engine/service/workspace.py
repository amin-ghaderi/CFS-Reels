"""Media and transcript routes. These read the project store; they do not probe media."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request

from amix.amix_engine.service.errors import ApiError
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.service.schemas import (
    LinkMediaRequest,
    MediaResponse,
    MediaStatusResponse,
    RelinkMediaRequest,
    TranscriptResponse,
    TranscriptWordPage,
    TranscriptWordResponse,
    WordTextRequest,
)
from amix.amix_engine.storage.errors import NoActiveTranscript
from amix.amix_engine.storage.kinds import DEFAULT_MEDIA_ROLE, MEDIA_ROLES, WORD_PAGE_LIMIT
from amix.amix_engine.storage.project import ProjectStore, StoredMedia, TranscriptWordView


def register_workspace_routes(app: FastAPI, runtime: EngineRuntime, authorize, call) -> None:
    @app.get("/v1/projects/{handle}/media", response_model=list[MediaResponse])
    def list_media(handle: str, request: Request) -> list[MediaResponse]:
        authorize(request)
        return call(lambda: [_media_view(store, asset) for store, asset in _assets(runtime, handle)])

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


def _assets(runtime: EngineRuntime, handle: str):
    store = _store(runtime, handle)
    return [(store, asset) for asset in store.list_media_assets()]


def _link(runtime: EngineRuntime, handle: str, path: str, role: str) -> MediaResponse:
    store = _store(runtime, handle)
    chosen = _existing_file(path)
    if role not in MEDIA_ROLES:
        raise ApiError(400, "invalid_media_role", "media role is not recognized")
    asset_id = store.add_media_asset(
        display_name=chosen.name,
        role=role or DEFAULT_MEDIA_ROLE,
        location_kind="external",
        external_path=str(chosen),
        byte_size=chosen.stat().st_size,
    )
    return _media_view(store, store.get_media(asset_id))


def _relink(runtime: EngineRuntime, handle: str, asset_id: str, path: str) -> MediaResponse:
    store = _store(runtime, handle)
    chosen = _existing_file(path)
    asset = store.relink_external(
        asset_id,
        str(chosen),
        byte_size=chosen.stat().st_size,
        display_name=chosen.name,
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


def _media_view(store: ProjectStore, asset: StoredMedia) -> MediaResponse:
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
