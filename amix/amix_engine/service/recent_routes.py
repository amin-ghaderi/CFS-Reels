"""Recent projects. Global application state, not project data."""
from __future__ import annotations

import base64

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from amix.amix_engine.appstate.store import SettingsRejected
from amix.amix_engine.service.errors import ApiError
from amix.amix_engine.service.runtime import EngineRuntime


class LocateRecentBody(BaseModel):
    path: str = Field(min_length=1)


def register_recent_routes(app: FastAPI, runtime: EngineRuntime, authorize, call) -> None:
    @app.get("/v1/runtime/recent-projects")
    def list_recent(request: Request) -> dict:
        authorize(request)
        return call(lambda: {"projects": [_view(item) for item in _store(runtime).recent_projects()]})

    @app.get("/v1/runtime/recent-projects/{project_id}/thumbnail")
    def thumbnail(project_id: str, request: Request) -> dict:
        authorize(request)
        return call(lambda: _thumbnail(runtime, project_id))

    @app.post("/v1/runtime/recent-projects/{project_id}/remove")
    def remove(project_id: str, request: Request) -> dict:
        authorize(request)
        return call(lambda: _remove(runtime, project_id))

    @app.post("/v1/runtime/recent-projects/{project_id}/locate")
    def locate(project_id: str, body: LocateRecentBody, request: Request) -> dict:
        authorize(request)
        return call(lambda: _locate(runtime, project_id, body.path))


def _store(runtime: EngineRuntime):
    if runtime.app is None:
        raise ApiError(409, "app_state_unavailable", "Application state is not available.")
    return runtime.app


def _remove(runtime: EngineRuntime, project_id: str) -> dict:
    try:
        _store(runtime).remove_recent(project_id)
    except SettingsRejected as exc:
        raise ApiError(404, exc.code, exc.message) from exc
    return {"removed": True}


def _locate(runtime: EngineRuntime, project_id: str, path: str) -> dict:
    try:
        found = _store(runtime).locate_recent(project_id, path)
    except SettingsRejected as exc:
        status = 404 if exc.code == "unknown_recent_project" else 409
        raise ApiError(status, exc.code, exc.message) from exc
    return _view(found)


def _thumbnail(runtime: EngineRuntime, project_id: str) -> dict:
    try:
        data = _store(runtime).recent_thumbnail(project_id)
    except SettingsRejected as exc:
        raise ApiError(404, exc.code, exc.message) from exc
    if data is None:
        raise ApiError(404, "thumbnail_unavailable", "No thumbnail is available.")
    return {"media_type": "image/jpeg", "data_base64": base64.b64encode(data).decode("ascii")}


def _view(item) -> dict:
    return {
        "project_id": item.project_id,
        "display_name": item.display_name,
        "root_path": item.root_path,
        "last_opened_at": item.last_opened_at,
        "availability": item.availability,
        "thumbnail": item.thumbnail,
    }
