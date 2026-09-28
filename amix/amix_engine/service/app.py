"""HTTP boundary. Routes validate, call the runtime, and map errors."""
from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from amix.amix_engine import __version__
from amix.amix_engine.jobs.runner import EngineNotAccepting, UnsupportedJobKind
from amix.amix_engine.service.errors import (
    ApiError,
    InvalidProjectPath,
    ProjectAlreadyOpen,
    ProjectCloseTimeout,
    UnknownProjectHandle,
)
from amix.amix_engine.service.runtime import EngineRuntime, resolve_project_path
from amix.amix_engine.service.schemas import (
    CreateJobRequest,
    CreateProjectRequest,
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    JobResponse,
    OpenProjectRequest,
    ProjectResponse,
)
from amix.amix_engine.storage.errors import (
    InvalidJobState,
    JobSpecRejected,
    MediaMissing,
    ProjectAlreadyLocked,
    ProjectDatabaseInvalid,
    SchemaMismatch,
    UnknownJob,
)
from amix.amix_engine.storage.jobs import StoredJob

log = logging.getLogger("amix.engine")


def create_app(runtime: EngineRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        try:
            runtime.shutdown()
        except ProjectCloseTimeout:
            log.error("shutdown timed out with a project lock still held")

    app = FastAPI(title="AMIX Engine", version=__version__, lifespan=lifespan)
    app.state.runtime = runtime

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _error(400, "invalid_request", "request is invalid")

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, _exc: Exception) -> JSONResponse:
        log.error("request failed")
        return _error(500, "internal_error", "internal error")

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="amix-engine", version=__version__)

    @app.post("/v1/projects/create", response_model=ProjectResponse)
    def create_project(body: CreateProjectRequest, request: Request) -> ProjectResponse:
        _authorize(request)
        return _call(lambda: _project_view(runtime.create_project(resolve_project_path(body.path), body.name)))

    @app.post("/v1/projects/open", response_model=ProjectResponse)
    def open_project(body: OpenProjectRequest, request: Request) -> ProjectResponse:
        _authorize(request)
        return _call(lambda: _project_view(
            runtime.open_project_at(resolve_project_path(body.path), read_only=body.read_only)
        ))

    @app.get("/v1/projects/{handle}", response_model=ProjectResponse)
    def get_project(handle: str, request: Request) -> ProjectResponse:
        _authorize(request)
        return _call(lambda: _project_view(runtime.session(handle)))

    @app.post("/v1/projects/{handle}/close")
    def close_project(handle: str, request: Request) -> dict:
        _authorize(request)
        _call(lambda: runtime.close_project(handle))
        return {"closed": True}

    @app.post("/v1/projects/{handle}/jobs", response_model=JobResponse)
    def create_job(handle: str, body: CreateJobRequest, request: Request) -> JobResponse:
        _authorize(request)
        return _call(lambda: _job_view(runtime.jobs.submit(
            runtime.session(handle).store,
            body.kind,
            body.spec,
            body.media_asset_id,
        )))

    @app.get("/v1/projects/{handle}/jobs", response_model=list[JobResponse])
    def list_jobs(handle: str, request: Request) -> list[JobResponse]:
        _authorize(request)
        return _call(lambda: [
            _job_view(job) for job in runtime.session(handle).store.list_processing_jobs()
        ])

    @app.get("/v1/projects/{handle}/jobs/{job_id}", response_model=JobResponse)
    def get_job(handle: str, job_id: str, request: Request) -> JobResponse:
        _authorize(request)
        return _call(lambda: _job_view(runtime.session(handle).store.get_processing_job(job_id)))

    @app.post("/v1/projects/{handle}/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(handle: str, job_id: str, request: Request) -> JobResponse:
        _authorize(request)
        return _call(lambda: _job_view(runtime.jobs.cancel(runtime.session(handle).store, job_id)))

    @app.post("/v1/projects/{handle}/jobs/{job_id}/retry", response_model=JobResponse)
    def retry_job(handle: str, job_id: str, request: Request) -> JobResponse:
        _authorize(request)
        return _call(lambda: _job_view(runtime.jobs.retry(runtime.session(handle).store, job_id)))

    return app


def _authorize(request: Request) -> None:
    runtime: EngineRuntime = request.app.state.runtime
    header = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        raise ApiError(401, "unauthorized", "missing session token")
    presented = header[len(prefix):]
    if not secrets.compare_digest(presented, runtime.token):
        raise ApiError(401, "unauthorized", "invalid session token")


def _call(fn: Callable):
    try:
        return fn()
    except ApiError:
        raise
    except ProjectAlreadyLocked as exc:
        raise ApiError(409, "project_already_locked", "project is already open for write") from exc
    except ProjectAlreadyOpen as exc:
        raise ApiError(409, "project_already_open", "project is already open in this engine") from exc
    except ProjectCloseTimeout as exc:
        raise ApiError(409, "project_close_timeout", "project close timed out while a job was still active") from exc
    except UnknownProjectHandle as exc:
        raise ApiError(404, "unknown_project_handle", "unknown project handle") from exc
    except InvalidProjectPath as exc:
        raise ApiError(400, "invalid_project_path", str(exc)) from exc
    except SchemaMismatch as exc:
        raise ApiError(409, "schema_mismatch", "project schema is not supported for this open mode") from exc
    except MediaMissing as exc:
        raise ApiError(409, "media_missing", "media file is missing") from exc
    except UnknownJob as exc:
        raise ApiError(404, "unknown_job", "unknown job") from exc
    except InvalidJobState as exc:
        message = str(exc)
        if "read-only" in message:
            raise ApiError(409, "project_read_only", "project is open read-only") from exc
        raise ApiError(409, "invalid_job_state", "job is not in a state that allows this action") from exc
    except JobSpecRejected as exc:
        raise ApiError(400, "job_spec_rejected", "job spec contains a field that must not be stored") from exc
    except UnsupportedJobKind as exc:
        raise ApiError(400, "unsupported_job_kind", "unsupported job kind") from exc
    except EngineNotAccepting as exc:
        raise ApiError(503, "engine_shutting_down", "engine is not accepting jobs") from exc
    except ProjectDatabaseInvalid as exc:
        message = str(exc)
        if "read-only" in message:
            raise ApiError(409, "project_read_only", "project is open read-only") from exc
        if "missing project database" in message:
            raise ApiError(404, "project_not_found", "project database was not found") from exc
        raise ApiError(400, "project_database_invalid", "project database is invalid") from exc


def _project_view(session) -> ProjectResponse:
    store = session.store
    return ProjectResponse(
        handle=session.handle,
        project_id=store.project_id,
        name=store.project_name,
        read_only=store.read_only,
        schema_revision=store.alembic_revision(),
    )


def _job_view(job: StoredJob) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        media_asset_id=job.media_asset_id,
        kind=job.kind,
        status=job.status,
        progress_bp=job.progress_bp,
        spec=job.spec,
        result=job.result,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        cancel_requested=job.cancel_requested,
        attempt=job.attempt,
        resumed_from_job_id=job.resumed_from_job_id,
        interrupt_reason=job.interrupt_reason,
    )


def _error(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump())
