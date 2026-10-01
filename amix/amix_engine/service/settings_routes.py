"""Global settings routes. They do not require an open project."""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing
from amix.amix_engine.appstate.catalog import catalog, find_entry
from amix.amix_engine.appstate.download import run_download
from amix.amix_engine.appstate.store import SettingsRejected
from amix.amix_engine.appstate.validate import ResourceInvalid, speech_directory, speech_identity, vision_file
from amix.amix_engine.semantic.provider import endpoint_host, is_loopback
from amix.amix_engine.semantic.registry import check_provider, provider_status
from amix.amix_engine.service.errors import ApiError
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.stt.resolver import SpeechResourceError, resolve_speech_model, speech_model_status
from amix.amix_engine.adapters.vision.resolver import vision_model_status

_ACTIVE = frozenset({"QUEUED", "RUNNING", "CANCEL_REQUESTED"})
_BUSY = {"speech": frozenset({"transcribe"}), "vision": frozenset({"detect_overlap"})}


class ImportSpeechBody(BaseModel):
    path: str = Field(min_length=1)
    display_name: str | None = None
    license_name: str | None = None
    license_url: str | None = None


class ImportVisionBody(BaseModel):
    path: str = Field(min_length=1)
    display_name: str | None = None
    version: str | None = None
    license_name: str | None = None
    license_url: str | None = None


class SelectBody(BaseModel):
    resource_id: str = Field(min_length=1)


class RemoveBody(BaseModel):
    confirm: bool = False


class NetworkBody(BaseModel):
    policy: str


class ToolsBody(BaseModel):
    directory: str | None = None


class ProviderBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    placement: str
    base_url: str = Field(min_length=1)
    model_id: str = Field(min_length=1, max_length=128)
    provider_id: str | None = None


class CredentialBody(BaseModel):
    credential_ref: str = Field(min_length=1, max_length=128)
    secret: str = Field(min_length=1, max_length=4096)


class DownloadBody(BaseModel):
    resource_id: str = Field(min_length=1)


class LocalLimitsBody(BaseModel):
    context_size: int | None = None
    threads: int | None = None


class SemanticSourceBody(BaseModel):
    source: str


def register_settings_routes(app: FastAPI, runtime: EngineRuntime, authorize, call) -> None:
    @app.get("/v1/runtime/status")
    def runtime_status(request: Request) -> dict:
        authorize(request)
        return _status(runtime)

    @app.post("/v1/runtime/speech/import")
    def import_speech(body: ImportSpeechBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _import_speech(runtime, body))

    @app.post("/v1/runtime/speech/select")
    def select_speech(body: SelectBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _select(runtime, body.resource_id))

    @app.post("/v1/runtime/resources/select")
    def select_any_resource(body: SelectBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _select(runtime, body.resource_id))

    @app.post("/v1/runtime/resources/{resource_id}/remove")
    def remove_resource(resource_id: str, body: RemoveBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _remove(runtime, resource_id, body.confirm))

    @app.post("/v1/runtime/vision/import")
    def import_vision(body: ImportVisionBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _import_vision(runtime, body))

    @app.post("/v1/runtime/vision/select")
    def select_vision(body: SelectBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _select(runtime, body.resource_id))

    @app.post("/v1/runtime/network")
    def set_network(body: NetworkBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _network(runtime, body.policy))

    @app.post("/v1/runtime/tools")
    def set_tools(body: ToolsBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _tools(runtime, body.directory))

    @app.post("/v1/runtime/providers")
    def save_provider(body: ProviderBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _save_provider(runtime, body))

    @app.post("/v1/runtime/providers/{provider_id}/select")
    def select_provider(provider_id: str, request: Request) -> dict:
        authorize(request)
        return call(lambda: _select_provider(runtime, provider_id))

    @app.post("/v1/runtime/providers/{provider_id}/remove")
    def remove_provider(provider_id: str, request: Request) -> dict:
        authorize(request)
        return call(lambda: _remove_provider(runtime, provider_id))

    @app.post("/v1/runtime/llama/import")
    def import_llama(body: ImportVisionBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _import_llama(runtime, body))

    @app.post("/v1/runtime/gguf/import")
    def import_gguf(body: ImportVisionBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _import_gguf(runtime, body))

    @app.post("/v1/runtime/local-ai/limits")
    def local_limits(body: LocalLimitsBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _local_limits(runtime, body))

    @app.post("/v1/runtime/local-ai/use")
    def use_local_ai(body: SemanticSourceBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _use_local_ai(runtime, body.source))

    @app.post("/v1/runtime/local-ai/start")
    def start_local_ai(request: Request) -> dict:
        authorize(request)
        return call(lambda: _start_local_ai(runtime))

    @app.post("/v1/runtime/local-ai/stop")
    def stop_local_ai(request: Request) -> dict:
        authorize(request)
        return call(_stop_local_ai)

    @app.post("/v1/runtime/providers/test")
    def test_provider(request: Request) -> dict:
        authorize(request)
        return call(_test_provider)

    @app.post("/v1/runtime/credentials")
    def put_credential(body: CredentialBody, request: Request) -> dict:
        authorize(request)
        if request.headers.get("x-amix-credential-write") != "1":
            raise ApiError(404, "unknown_route", "That request was not found.")
        if runtime.secrets is None:
            raise ApiError(409, "settings_unavailable", "Application settings are not available.")
        try:
            runtime.secrets.put(body.credential_ref, body.secret)
        except ValueError as exc:
            raise ApiError(400, "invalid_credential", "The credential could not be stored.") from exc
        return {"configured": True}

    @app.post("/v1/runtime/credentials/remove")
    def remove_credential(body: SelectBody, request: Request) -> dict:
        authorize(request)
        if request.headers.get("x-amix-credential-write") != "1":
            raise ApiError(404, "unknown_route", "That request was not found.")
        if runtime.secrets is None:
            raise ApiError(409, "settings_unavailable", "Application settings are not available.")
        runtime.secrets.remove(body.resource_id)
        return {"configured": False}

    @app.post("/v1/runtime/downloads")
    def start_download(body: DownloadBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _start_download(runtime, body.resource_id))

    @app.post("/v1/runtime/downloads/{job_id}/cancel")
    def cancel_download(job_id: str, request: Request) -> dict:
        authorize(request)
        return call(lambda: _cancel_download(runtime, job_id))

    @app.get("/v1/runtime/downloads/{job_id}")
    def download_status(job_id: str, request: Request) -> dict:
        authorize(request)
        return call(lambda: _download_status(runtime, job_id))


def _store(runtime: EngineRuntime):
    if runtime.app is None:
        raise ApiError(409, "settings_unavailable", "Application settings are not available.")
    return runtime.app


def _status(runtime: EngineRuntime) -> dict:
    speech = speech_model_status()
    vision = vision_model_status()
    semantic = provider_status()
    tools = _tool_status()
    resources = []
    providers = []
    policy = semantic.get("network_mode") or "offline"
    if runtime.app is not None:
        policy = runtime.app.state().network_policy
        resources = [_public_resource(runtime, item) for item in runtime.app.resources()]
        providers = [_public_provider(runtime, item) for item in runtime.app.providers()]
    return {
        "restart_required": False,
        "network_policy": policy,
        "speech": _speech_view(speech),
        "vision": _product_state(vision.state, vision.message, vision.model_id, vision.display_name, vision.runtime),
        "semantic": semantic,
        "ffmpeg": tools["ffmpeg"],
        "ffprobe": tools["ffprobe"],
        "resources": resources,
        "semantic_source": "provider" if runtime.app is None else (runtime.app.state().semantic_source or "provider"),
        "local_ai": _local_ai_status(runtime),
        "providers": providers,
        "catalog": [
            {
                "resource_id": item.resource_id,
                "kind": item.kind,
                "display_name": item.display_name,
                "version": item.version,
                "license_name": item.license_name,
                "license_url": item.license_url,
            }
            for item in catalog()
        ],
    }


def _speech_view(speech) -> dict:
    view = _product_state(speech.state, speech.message, speech.model_id, speech.display_name, speech.runtime)
    if speech.state != "READY":
        return view
    try:
        descriptor = resolve_speech_model()
    except SpeechResourceError:
        return view
    view["device"] = descriptor.device
    view["compute_type"] = descriptor.compute_type
    view["version"] = descriptor.version
    view["identity"] = descriptor.identity
    return view


def _product_state(state: str, message: str, resource_id, display_name, runtime_name) -> dict:
    mapped = {
        "READY": "READY",
        "MODEL_MISSING": "NOT_CONFIGURED",
        "INVALID_MODEL": "INVALID",
        "RUNTIME_UNAVAILABLE": "FAILED",
    }.get(state, state)
    if state == "MODEL_MISSING" and display_name:
        mapped = "MISSING"
    return {
        "state": mapped,
        "message": message,
        "resource_id": resource_id,
        "display_name": display_name,
        "runtime": runtime_name,
    }


def _public_resource(runtime: EngineRuntime, item) -> dict:
    return {
        "resource_id": item.resource_id,
        "kind": item.kind,
        "display_name": item.display_name,
        "version": item.version,
        "ownership": item.ownership,
        "origin": item.origin,
        "license_name": item.license_name,
        "license_url": item.license_url,
        "identity": item.identity,
        "runtime": item.runtime,
        "status": item.status,
        "byte_size": item.byte_size,
        "architecture": item.architecture,
        "semantic_compatibility": item.semantic_compatibility or "unknown",
        "selected": item.resource_id in {
            runtime.app.state().selected_speech_id,
            runtime.app.state().selected_vision_id,
            runtime.app.state().selected_llama_runtime_id,
            runtime.app.state().selected_gguf_model_id,
        },
    }


def _public_provider(runtime: EngineRuntime, item) -> dict:
    configured = False
    if runtime.secrets is not None and item.credential_ref:
        configured = runtime.secrets.configured(item.credential_ref)
    return {
        "provider_id": item.provider_id,
        "display_name": item.display_name,
        "placement": item.placement,
        "base_url": item.base_url,
        "model_id": item.model_id,
        "credential_ref": item.credential_ref,
        "credential_configured": configured,
        "selected": runtime.app.state().semantic_source != "managed_local" and runtime.app.state().selected_provider_id == item.provider_id,
    }


def _tool_status() -> dict:
    configured = False
    if runtime_has_saved_tools():
        configured = True
    try:
        tools = discover_tools()
    except MediaToolMissing:
        state = "INVALID" if configured else "MISSING"
        empty = {"state": state, "version": None, "message": "FFmpeg tools are not available."}
        return {"ffmpeg": empty, "ffprobe": dict(empty)}
    return {
        "ffmpeg": {"state": "READY", "version": _short_version(tools.ffmpeg_version), "message": "FFmpeg is ready."},
        "ffprobe": {"state": "READY", "version": _short_version(tools.ffprobe_version), "message": "FFprobe is ready."},
    }


def _short_version(line: str | None) -> str | None:
    if not line:
        return None
    parts = line.split()
    if "version" in parts:
        index = parts.index("version") + 1
        if index < len(parts):
            return parts[index].split("-", 1)[0]
    return parts[0]


def runtime_has_saved_tools() -> bool:
    from amix.amix_engine.appstate.bind import bound_store
    store = bound_store()
    if store is None:
        return False
    return bool(store.state().ffmpeg_directory)


def _import_speech(runtime: EngineRuntime, body: ImportSpeechBody) -> dict:
    store = _store(runtime)
    folder = Path(body.path)
    try:
        speech_directory(folder)
    except ResourceInvalid as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    saved = store.add_resource(
        kind="speech",
        display_name=body.display_name or folder.name,
        local_path=str(folder.resolve()),
        ownership="registered",
        origin="import",
        identity=speech_identity(folder),
        runtime="faster-whisper",
        license_name=body.license_name,
        license_url=body.license_url,
        byte_size=(folder / "model.bin").stat().st_size,
    )
    return {"resource_id": saved.resource_id, "restart_required": False}


def _import_vision(runtime: EngineRuntime, body: ImportVisionBody) -> dict:
    store = _store(runtime)
    file = Path(body.path)
    try:
        vision_file(file)
    except ResourceInvalid as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    from amix.amix_engine.appstate.validate import file_identity
    saved = store.add_resource(
        kind="vision",
        display_name=body.display_name or "YuNet",
        local_path=str(file.resolve()),
        ownership="registered",
        origin="import",
        identity=file_identity(file),
        runtime="opencv",
        version=body.version,
        license_name=body.license_name,
        license_url=body.license_url,
        byte_size=file.stat().st_size,
    )
    return {"resource_id": saved.resource_id, "restart_required": False}


def _select(runtime: EngineRuntime, resource_id: str) -> dict:
    store = _store(runtime)
    try:
        store.select_resource(resource_id)
    except SettingsRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return {"restart_required": False}


def _remove(runtime: EngineRuntime, resource_id: str, confirm: bool) -> dict:
    store = _store(runtime)
    found = store.resource(resource_id)
    if found is None:
        raise ApiError(404, "unknown_resource", "That resource is not installed.")
    state = store.state()
    selected = {
        "speech": state.selected_speech_id,
        "vision": state.selected_vision_id,
        "llama_runtime": state.selected_llama_runtime_id,
        "gguf": state.selected_gguf_model_id,
    }.get(found.kind)
    from amix.amix_engine.appstate.local_server import local_server_uses
    if local_server_uses(resource_id):
        raise ApiError(409, "resource_in_use", "Stop local AI before removing this resource.")
    if selected == resource_id and _busy(runtime, found.kind):
        raise ApiError(409, "resource_in_use", "This resource is in use. Wait for the current job to finish.")
    if found.ownership == "managed" and not confirm:
        raise ApiError(400, "confirmation_required", "Confirm removal of an AMIX-managed resource.")
    try:
        removed = store.delete_resource(resource_id)
    except SettingsRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    if removed.ownership == "managed":
        _delete_managed(store.root, Path(removed.local_path))
    return {"removed": True}


def _delete_managed(root: Path, path: Path) -> None:
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:
        return
    if base not in resolved.parents and resolved != base:
        return
    target = resolved if resolved.is_dir() else resolved.parent
    if base not in target.parents:
        return
    shutil.rmtree(target, ignore_errors=True)


def _busy(runtime: EngineRuntime, kind: str) -> bool:
    wanted = _BUSY.get(kind, frozenset())
    for store in runtime.open_stores():
        for job in store.list_processing_jobs():
            if job.kind in wanted and job.status in _ACTIVE:
                return True
    return False


def _network(runtime: EngineRuntime, policy: str) -> dict:
    store = _store(runtime)
    try:
        store.set_network_policy(policy)
    except SettingsRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return {"network_policy": policy, "restart_required": False}


def _tools(runtime: EngineRuntime, directory: str | None) -> dict:
    store = _store(runtime)
    if directory is not None and directory.strip():
        root = Path(directory.strip())
        names = ("ffmpeg.exe", "ffprobe.exe") if __import__("os").name == "nt" else ("ffmpeg", "ffprobe")
        if not (root / names[0]).is_file() or not (root / names[1]).is_file():
            raise ApiError(400, "invalid_media_tools", "Choose a folder that contains both FFmpeg and FFprobe.")
        store.set_ffmpeg_directory(str(root))
    else:
        store.set_ffmpeg_directory(None)
    return {"restart_required": False}


def _save_provider(runtime: EngineRuntime, body: ProviderBody) -> dict:
    store = _store(runtime)
    if endpoint_host(body.base_url) is None:
        raise ApiError(400, "invalid_provider", "The provider address is not valid.")
    local = is_loopback(body.base_url)
    if body.placement == "local" and not local:
        raise ApiError(400, "invalid_provider", "A local provider must use a loopback address.")
    if body.placement == "remote" and local:
        raise ApiError(400, "invalid_provider", "A remote provider cannot use a loopback address.")
    if body.placement not in {"local", "remote"}:
        raise ApiError(400, "invalid_provider", "That provider placement is not available.")
    try:
        saved = store.save_provider(
            display_name=body.display_name,
            placement=body.placement,
            base_url=body.base_url,
            model_id=body.model_id,
            provider_id=body.provider_id,
        )
    except SettingsRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return {
        "provider_id": saved.provider_id,
        "credential_ref": saved.credential_ref,
        "restart_required": False,
    }


def _select_provider(runtime: EngineRuntime, provider_id: str) -> dict:
    store = _store(runtime)
    try:
        store.select_provider(provider_id)
    except SettingsRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return {"restart_required": False}


def _remove_provider(runtime: EngineRuntime, provider_id: str) -> dict:
    store = _store(runtime)
    try:
        removed = store.delete_provider(provider_id)
    except SettingsRejected as exc:
        raise ApiError(404, exc.code, exc.message) from exc
    if runtime.secrets is not None and removed.credential_ref:
        runtime.secrets.remove(removed.credential_ref)
    return {"removed": True}


def _import_llama(runtime: EngineRuntime, body: ImportVisionBody) -> dict:
    from amix.amix_engine.appstate.validate import file_identity, llama_executable
    store = _store(runtime)
    try:
        executable, version = llama_executable(Path(body.path))
    except ResourceInvalid as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    saved = store.add_resource(
        kind="llama_runtime",
        display_name=body.display_name or "llama.cpp",
        local_path=str(executable.resolve()),
        ownership="registered",
        origin="import",
        identity=file_identity(executable),
        runtime="llama.cpp",
        version=version,
        license_name=body.license_name,
        license_url=body.license_url,
        byte_size=executable.stat().st_size,
    )
    return {"resource_id": saved.resource_id, "restart_required": False}


def _import_gguf(runtime: EngineRuntime, body: ImportVisionBody) -> dict:
    from amix.amix_engine.appstate.validate import file_identity, gguf_file
    store = _store(runtime)
    file = Path(body.path)
    try:
        version, architecture = gguf_file(file)
    except ResourceInvalid as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    saved = store.add_resource(
        kind="gguf",
        display_name=body.display_name or file.stem or "Local model",
        local_path=str(file.resolve()),
        ownership="registered",
        origin="import",
        identity=file_identity(file),
        runtime="llama.cpp",
        version=str(version),
        architecture=architecture,
        license_name=body.license_name,
        license_url=body.license_url,
        byte_size=file.stat().st_size,
        semantic_compatibility="unknown",
    )
    return {"resource_id": saved.resource_id, "restart_required": False}


def _local_limits(runtime: EngineRuntime, body: LocalLimitsBody) -> dict:
    store = _store(runtime)
    try:
        store.set_local_limits(body.context_size, body.threads)
    except SettingsRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return {"restart_required": False}


def _use_local_ai(runtime: EngineRuntime, source: str) -> dict:
    store = _store(runtime)
    try:
        store.set_semantic_source(source)
    except SettingsRejected as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    return {"semantic_source": source, "restart_required": False}


def _start_local_ai(runtime: EngineRuntime) -> dict:
    from amix.amix_engine.appstate.local_server import begin_local_server
    store = _store(runtime)
    if store.state().semantic_source != "managed_local":
        try:
            store.set_semantic_source("managed_local")
        except SettingsRejected as exc:
            raise ApiError(400, exc.code, exc.message) from exc
    begin_local_server(store)
    return {"restart_required": False, "local_ai": _local_ai_status(runtime)}


def _stop_local_ai() -> dict:
    from amix.amix_engine.appstate.local_server import stop_local_server
    stop_local_server()
    return {"restart_required": False}


def _local_ai_status(runtime: EngineRuntime) -> dict:
    from amix.amix_engine.appstate.local_server import local_server_snapshot
    snapshot = local_server_snapshot()
    if runtime.app is None:
        return {**snapshot, "selected": False, "context_size": None, "threads": None}
    state = runtime.app.state()
    return {
        **snapshot,
        "selected": state.semantic_source == "managed_local",
        "context_size": state.local_context_size,
        "threads": state.local_threads,
    }


def _test_provider() -> dict:
    from amix.amix_engine.appstate.bind import bound_store
    from amix.amix_engine.appstate.local_server import begin_local_server, local_server_snapshot
    store = bound_store()
    if store is not None and store.state().semantic_source == "managed_local":
        begin_local_server(store)
        return {"local_ai": local_server_snapshot(), "reachable": None}
    try:
        return check_provider()
    except Exception as exc:
        code = getattr(exc, "code", "semantic_provider_unavailable")
        message = getattr(exc, "message", "The semantic provider could not be reached.")
        raise ApiError(400, code, message) from exc


def _start_download(runtime: EngineRuntime, resource_id: str) -> dict:
    store = _store(runtime)
    if find_entry(resource_id) is None:
        raise ApiError(400, "unknown_resource", "That download is not in the catalog.")
    if store.state().network_policy != "network_enabled":
        raise ApiError(400, "offline_provider_forbidden", "Offline mode does not download resources.")
    job_id = store.create_resource_job("install_resource", resource_id)
    cancel = threading.Event()
    runtime._download_cancels[job_id] = cancel
    threading.Thread(
        target=run_download,
        args=(store, job_id, cancel.is_set),
        name=f"amix-download-{job_id[:8]}",
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "QUEUED"}


def _cancel_download(runtime: EngineRuntime, job_id: str) -> dict:
    store = _store(runtime)
    job = store.resource_job(job_id)
    if job is None:
        raise ApiError(404, "unknown_job", "That download is no longer available.")
    token = runtime._download_cancels.get(job_id)
    if token is not None:
        token.set()
    if job["status"] == "QUEUED":
        store.update_resource_job(job_id, status="CANCELLED", error_code="cancelled", error_message="The download was cancelled.")
    return {"status": "CANCELLED"}


def _download_status(runtime: EngineRuntime, job_id: str) -> dict:
    store = _store(runtime)
    job = store.resource_job(job_id)
    if job is None:
        raise ApiError(404, "unknown_job", "That download is no longer available.")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress_bp": job["progress_bp"],
        "error_code": job["error_code"],
        "error_message": job["error_message"],
    }
