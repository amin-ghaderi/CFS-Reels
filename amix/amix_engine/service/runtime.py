"""Process-local projects and jobs. Routes call this layer, not SQLAlchemy."""
from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from amix.amix_engine.jobs.handlers import ProjectIntegrityCheck
from amix.amix_engine.jobs.media import GenerateProxyJob, MediaProbeJob
from amix.amix_engine.jobs.diarize import DiarizeAudioJob
from amix.amix_engine.jobs.multicam import BuildMulticamPlanJob
from amix.amix_engine.jobs.conversation import MapConversationJob
from amix.amix_engine.jobs.reels import DiscoverReelsJob
from amix.amix_engine.jobs.render import RenderMulticamJob, RenderSequenceJob
from amix.amix_engine.jobs.overlap import DetectOverlapJob
from amix.amix_engine.jobs.transcribe import TranscribeJob
from amix.amix_engine.jobs.runner import JobManager
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.errors import (
    InvalidProjectPath,
    ProjectAlreadyOpen,
    ProjectCloseTimeout,
    UnknownProjectHandle,
)
from amix.amix_engine.storage.project import ProjectStore, create_project, open_project

log = logging.getLogger("amix.engine")


class TokenRedactor(logging.Filter):
    """Drop the session token and authorization material from log lines."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        lowered = message.lower()
        if "authorization" in lowered or "bearer " in lowered or (self._token and self._token in message):
            record.msg = "[redacted]"
            record.args = ()
        return True


@dataclass
class OpenSession:
    handle: str
    store: ProjectStore
    path_key: str


class EngineRuntime:
    def __init__(
        self,
        config: ServiceConfig,
        *,
        token: str | None = None,
        extra_handlers: dict | None = None,
    ) -> None:
        self.config = config
        self.token = token or config.session_token or secrets.token_urlsafe(32)
        handlers: dict = {
            ProjectIntegrityCheck.kind: ProjectIntegrityCheck(),
            MediaProbeJob.kind: MediaProbeJob(),
            GenerateProxyJob.kind: GenerateProxyJob(),
            TranscribeJob.kind: TranscribeJob(),
            DiarizeAudioJob.kind: DiarizeAudioJob(),
            DetectOverlapJob.kind: DetectOverlapJob(),
            BuildMulticamPlanJob.kind: BuildMulticamPlanJob(),
            RenderMulticamJob.kind: RenderMulticamJob(),
            RenderSequenceJob.kind: RenderSequenceJob(),
            MapConversationJob.kind: MapConversationJob(),
            DiscoverReelsJob.kind: DiscoverReelsJob(),
        }
        for kind, handler in (extra_handlers or {}).items():
            if kind in handlers:
                raise ValueError(f"handler already registered: {kind}")
            handlers[kind] = handler
        self.jobs = JobManager(handlers, max_workers=config.worker_count)
        self._sessions: dict[str, OpenSession] = {}
        self._by_path: dict[str, str] = {}
        self._guard = threading.Lock()
        self._shut_down = False
        log.addFilter(TokenRedactor(self.token))

    def create_project(self, path: Path, name: str) -> OpenSession:
        self._require_running()
        key = _path_key(path)
        with self._guard:
            self._reject_if_open(key)
        store = create_project(path, name)
        return self._adopt(store, key)

    def open_project_at(self, path: Path, *, read_only: bool = False) -> OpenSession:
        self._require_running()
        key = _path_key(path)
        with self._guard:
            self._reject_if_open(key)
        store = open_project(path, read_only=read_only)
        return self._adopt(store, key)

    def session(self, handle: str) -> OpenSession:
        with self._guard:
            found = self._sessions.get(handle)
        if found is None:
            raise UnknownProjectHandle(handle)
        return found

    def close_project(self, handle: str) -> None:
        found = self.session(handle)
        self.jobs.cancel_all(found.store)
        if not self.jobs.wait_until_idle(found.store, self.config.shutdown_timeout_s):
            raise ProjectCloseTimeout(handle)
        with self._guard:
            self._sessions.pop(handle, None)
            if self._by_path.get(found.path_key) == handle:
                self._by_path.pop(found.path_key, None)
        found.store.close()
        log.info("closed project %s handle %s", found.store.project_id, handle)

    def shutdown(self) -> None:
        with self._guard:
            if self._shut_down:
                return
            sessions = list(self._sessions.values())
        if not self.jobs.shutdown([item.store for item in sessions], self.config.shutdown_timeout_s):
            raise ProjectCloseTimeout("shutdown")
        for item in sessions:
            item.store.close()
        with self._guard:
            self._sessions.clear()
            self._by_path.clear()
            self._shut_down = True

    def _adopt(self, store: ProjectStore, key: str) -> OpenSession:
        handle = secrets.token_hex(16)
        session = OpenSession(handle=handle, store=store, path_key=key)
        with self._guard:
            if self._shut_down or key in self._by_path:
                store.close()
                if key in self._by_path:
                    raise ProjectAlreadyOpen(self._by_path[key])
                raise ProjectCloseTimeout("shutdown")
            self._sessions[handle] = session
            self._by_path[key] = handle
        log.info("opened project %s handle %s", store.project_id, handle)
        return session

    def _reject_if_open(self, key: str) -> None:
        existing = self._by_path.get(key)
        if existing is not None:
            raise ProjectAlreadyOpen(existing)

    def _require_running(self) -> None:
        if self._shut_down:
            raise ProjectCloseTimeout("shutdown")


def resolve_project_path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise InvalidProjectPath("project path is empty or malformed")
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise InvalidProjectPath("project path is empty or malformed") from exc


def _path_key(path: Path) -> str:
    return str(path.resolve())
