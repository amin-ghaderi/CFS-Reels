"""Coordinates job handlers on a small thread pool.

These threads orchestrate work. FFmpeg and transcription run in subprocesses.
This pool does not load speech models.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from amix.amix_engine.storage.errors import InvalidJobState
from amix.amix_engine.storage.jobs import CANCEL_REQUESTED, QUEUED, RUNNING, StoredJob
from amix.amix_engine.storage.project import ProjectStore

_ACTIVE = frozenset({QUEUED, RUNNING, CANCEL_REQUESTED})


class JobCancelled(Exception):
    """The handler observed cancellation and stopped."""


class JobFailed(Exception):
    """A handler failed with a stable code and a short message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UnsupportedJobKind(ValueError):
    """The kind is not a registered handler."""


class EngineNotAccepting(RuntimeError):
    """The engine is shutting down and will not start jobs."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise JobCancelled()


class JobContext:
    def __init__(
        self,
        store: ProjectStore,
        job_id: str,
        spec: dict,
        cancellation: CancellationToken,
        media_asset_id: str | None = None,
    ) -> None:
        self.store = store
        self.job_id = job_id
        self.spec = spec
        self.cancellation = cancellation
        self.media_asset_id = media_asset_id
        self._follow = None

    def follow_up(self, kind: str, spec: dict, media_asset_id: str | None) -> None:
        """Queue another job after this one. Direct callers can leave this unset."""
        if self._follow is None:
            return
        try:
            self._follow(kind, spec, media_asset_id)
        except EngineNotAccepting:
            return

    def report_progress(self, progress_bp: int) -> None:
        self.cancellation.raise_if_cancelled()
        self.store.set_job_progress(self.job_id, progress_bp)


class JobManager:
    def __init__(self, handlers: dict, *, max_workers: int) -> None:
        self._handlers = dict(handlers)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="amix-job")
        self._tokens: dict[str, CancellationToken] = {}
        self._guard = threading.Lock()
        self._accepting = True
        self._executor_closed = False

    def registered_kinds(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def submit(
        self,
        store: ProjectStore,
        kind: str,
        spec: dict | None = None,
        media_asset_id: str | None = None,
    ) -> StoredJob:
        if not self._accepting:
            raise EngineNotAccepting("engine is not accepting jobs")
        handler = self._handlers.get(kind)
        if handler is None:
            raise UnsupportedJobKind(kind)
        if store.read_only:
            raise InvalidJobState("project is open read-only")
        job = store.create_processing_job(kind=kind, spec=spec or {}, media_asset_id=media_asset_id)
        self._start(store, job)
        return job

    def retry(self, store: ProjectStore, job_id: str) -> StoredJob:
        if not self._accepting:
            raise EngineNotAccepting("engine is not accepting jobs")
        if store.read_only:
            raise InvalidJobState("project is open read-only")
        job = store.retry_processing_job(job_id)
        if job.kind not in self._handlers:
            raise UnsupportedJobKind(job.kind)
        self._start(store, job)
        return job

    def cancel(self, store: ProjectStore, job_id: str) -> StoredJob:
        with self._guard:
            token = self._tokens.get(job_id)
        if token is not None:
            token.request()
        return store.request_job_cancel(job_id)

    def cancel_all(self, store: ProjectStore) -> None:
        for job in store.list_processing_jobs():
            if job.status in _ACTIVE:
                self.cancel(store, job.job_id)

    def wait_until_idle(self, store: ProjectStore, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while True:
            if not self._busy(store):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def shutdown(self, stores: list[ProjectStore], timeout_s: float) -> bool:
        from amix.amix_engine.adapters.media.process import terminate_owned_processes

        self._accepting = False
        for store in stores:
            self.cancel_all(store)
        started = time.monotonic()
        terminate_owned_processes(timeout_s)
        remaining = max(0.0, timeout_s - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while time.monotonic() < deadline:
            if all(not self._busy(store) for store in stores):
                break
            time.sleep(0.01)
        if any(self._busy(store) for store in stores):
            return False
        self._close_executor()
        return True

    def _start(self, store: ProjectStore, job: StoredJob) -> None:
        token = CancellationToken()
        with self._guard:
            self._tokens[job.job_id] = token
        self._executor.submit(
            self._execute, store, job.job_id, job.kind, job.spec, token, job.media_asset_id,
        )

    def _execute(
        self,
        store: ProjectStore,
        job_id: str,
        kind: str,
        spec: dict,
        token: CancellationToken,
        media_asset_id: str | None = None,
    ) -> None:
        try:
            if token.is_cancelled() or not store.start_processing_job(job_id):
                self._stop_if_needed(store, job_id)
                return
            if token.is_cancelled():
                store.finish_job_cancelled(job_id)
                return
            context = JobContext(store, job_id, spec, token, media_asset_id)
            context._follow = lambda follow_kind, follow_spec, follow_asset: self.submit(
                store, follow_kind, follow_spec, follow_asset,
            )
            result = self._handlers[kind].run(context)
            committed = isinstance(result, dict) and result.get("activated") is True
            if token.is_cancelled() and not committed:
                store.finish_job_cancelled(job_id)
                return
            if not isinstance(result, dict):
                store.finish_job_failed(job_id, "handler_failed", "handler result must be an object")
                return
            if committed:
                result = {key: value for key, value in result.items() if key != "activated"}
            try:
                store.finish_job_succeeded(job_id, result, committed=committed)
            except InvalidJobState:
                if not committed:
                    store.finish_job_cancelled(job_id)
        except JobCancelled:
            self._stop_if_needed(store, job_id)
        except JobFailed as exc:
            try:
                store.finish_job_failed(job_id, exc.code, exc.message)
            except InvalidJobState:
                return
        except Exception as exc:
            self._fail_if_needed(store, job_id, exc)
        finally:
            with self._guard:
                self._tokens.pop(job_id, None)

    def _stop_if_needed(self, store: ProjectStore, job_id: str) -> None:
        try:
            store.finish_job_cancelled(job_id)
        except InvalidJobState:
            return

    def _fail_if_needed(self, store: ProjectStore, job_id: str, exc: Exception) -> None:
        try:
            store.finish_job_failed(job_id, "handler_failed", str(exc))
        except InvalidJobState:
            return

    def _busy(self, store: ProjectStore) -> bool:
        return any(job.status in _ACTIVE for job in store.list_processing_jobs())

    def _close_executor(self) -> None:
        if self._executor_closed:
            return
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._executor_closed = True
