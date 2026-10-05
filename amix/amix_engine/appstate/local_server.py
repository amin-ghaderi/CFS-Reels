"""Managed loopback llama.cpp server. Semantic tasks see only a provider endpoint.

The listening port is ephemeral and is not stored. Register-in-place files are
not copied.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from amix.amix_engine.adapters.media.process import background_tail, spawn_background, stop_background
from amix.amix_engine.appstate.validate import command_for
from amix.amix_engine.semantic.errors import SemanticError

START_TIMEOUT_S = 180.0
LOOPBACK = "127.0.0.1"
DEFAULT_CONTEXT = 16384
_DIAGNOSTIC_CAP = 400


@dataclass(frozen=True)
class LocalEndpoint:
    base_url: str
    model_id: str
    display_name: str
    runtime_version: str | None
    resource_id: str
    runtime_id: str


class LocalServerStopped(SemanticError):
    def __init__(self) -> None:
        super().__init__("local_model_stopped", "Local AI was stopped.")


class _Runtime:
    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._state = "STOPPED"
        self._message = "Local AI is stopped."
        self._diagnostic = ""
        self._endpoint: LocalEndpoint | None = None
        self._process = None
        self._booting = False
        self._generation = 0
        self._runtime_id: str | None = None
        self._model_id: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            self._observe_locked()
            return {
                "state": self._state,
                "message": self._message,
                "diagnostic": self._diagnostic if self._state == "FAILED" else "",
                "runtime_id": self._runtime_id,
                "model_id": self._model_id,
            }

    def uses(self, resource_id: str) -> bool:
        with self._lock:
            self._observe_locked()
            if self._state not in {"STARTING", "LOADING", "READY"}:
                return False
            return resource_id in {self._runtime_id, self._model_id}

    def ensure(self, store, timeout_s: float = START_TIMEOUT_S, cancel=None, origin: int | None = None) -> LocalEndpoint:
        deadline = time.monotonic() + timeout_s
        with self._lock:
            if origin is not None and origin != self._generation:
                raise LocalServerStopped()
            self._observe_locked()
            if self._matches_locked(store) and self._state == "READY" and self._endpoint is not None:
                return self._endpoint
            while self._booting:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._lock.wait(min(remaining, 0.2))
                self._observe_locked()
                if cancel is not None and cancel.is_cancelled():
                    raise LocalServerStopped()
            self._observe_locked()
            if self._matches_locked(store) and self._state == "READY" and self._endpoint is not None:
                return self._endpoint
            self._booting = True
            self._generation += 1
            generation = self._generation
            self._state = "STARTING"
            self._message = "Starting local model."
            self._diagnostic = ""
            self._endpoint = None
        try:
            return self._boot(store, generation, deadline, cancel)
        finally:
            with self._lock:
                self._booting = False
                self._lock.notify_all()

    def begin(self, store) -> None:
        with self._lock:
            self._observe_locked()
            if self._state in {"STARTING", "LOADING", "READY"}:
                return
            self._state = "STARTING"
            self._message = "Starting local model."
            self._diagnostic = ""
            generation = self._generation
        threading.Thread(target=self._begin, args=(store, generation), name="amix-local-ai", daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            process = self._process
            self._process = None
            self._endpoint = None
            self._runtime_id = None
            self._model_id = None
            self._state = "STOPPED"
            self._message = "Local AI is stopped."
            self._diagnostic = ""
            self._booting = False
            self._lock.notify_all()
        if process is not None:
            stop_background(process)

    def _begin(self, store, generation: int) -> None:
        try:
            self.ensure(store, origin=generation)
        except SemanticError:
            return

    def _boot(self, store, generation: int, deadline: float, cancel) -> LocalEndpoint:
        try:
            runtime, model, context, threads = _selection(store)
        except SemanticError as exc:
            with self._lock:
                if generation == self._generation:
                    self._state = "FAILED"
                    self._message = exc.message
                    self._diagnostic = ""
                    self._endpoint = None
            raise
        last_error = "The local model failed to start."
        last_tail = ""
        for _attempt in range(3):
            if cancel is not None and cancel.is_cancelled():
                self.stop()
                raise LocalServerStopped()
            port = _ephemeral_port()
            args = server_arguments(
                runtime.local_path,
                model.local_path,
                port,
                model.resource_id,
                context,
                threads,
            )
            process = spawn_background(args)
            with self._lock:
                if generation != self._generation:
                    stop_background(process)
                    raise LocalServerStopped()
                self._process = process
                self._runtime_id = runtime.resource_id
                self._model_id = model.resource_id
                self._state = "LOADING"
                self._message = "Loading model."
            ready = _wait_ready(process, port, deadline, cancel, generation, self)
            if ready == "ready":
                endpoint = LocalEndpoint(
                    base_url=f"http://{LOOPBACK}:{port}/v1",
                    model_id=model.resource_id,
                    display_name=model.display_name,
                    runtime_version=runtime.version,
                    resource_id=model.resource_id,
                    runtime_id=runtime.resource_id,
                )
                with self._lock:
                    if generation != self._generation:
                        stop_background(process)
                        raise LocalServerStopped()
                    self._endpoint = endpoint
                    self._state = "READY"
                    self._message = "Local AI is ready."
                    self._diagnostic = ""
                return endpoint
            last_tail = background_tail(process)
            stop_background(process)
            with self._lock:
                if self._process is process:
                    self._process = None
            if ready == "stopped":
                raise LocalServerStopped()
            last_error = failure_message(last_tail, ready)
            if ready != "bind":
                break
        with self._lock:
            if generation == self._generation:
                self._state = "FAILED"
                self._message = last_error
                self._diagnostic = _clip(last_tail)
                self._endpoint = None
        raise SemanticError("local_model_failed", last_error)

    def _matches_locked(self, store) -> bool:
        state = store.state()
        return (
            self._runtime_id == state.selected_llama_runtime_id
            and self._model_id == state.selected_gguf_model_id
            and self._runtime_id is not None
            and self._model_id is not None
        )

    def _observe_locked(self) -> None:
        process = self._process
        if process is None or process.poll() is None:
            return
        if self._state in {"STARTING", "LOADING", "READY"}:
            tail = background_tail(process)
            self._state = "FAILED"
            self._message = failure_message(tail, "exit")
            self._diagnostic = _clip(tail)
            self._endpoint = None
            stop_background(process)
            self._process = None


_runtime = _Runtime()


def desktop_thread_count() -> int:
    """Leave two logical processors for the engine and the desktop when the machine has them.

    llama.cpp's own default uses every logical processor. On this class of machine that
    saturates the CPU for the whole prefill and the engine misses its read deadline.
    """
    logical = os.cpu_count() or 2
    reserve = 2 if logical > 2 else 1
    return max(1, logical - reserve)


def server_arguments(executable: str, model_path: str, port: int, alias: str, context: int | None, threads: int | None) -> list[str]:
    from pathlib import Path

    if not isinstance(port, int) or port <= 0 or port > 65535:
        raise SemanticError("local_model_failed", "The local model failed to start.")
    chosen = desktop_thread_count() if threads is None else int(threads)
    args = [
        "-m", model_path,
        "--host", LOOPBACK,
        "--port", str(port),
        "--alias", alias,
        "--parallel", "1",
        "-t", str(chosen),
        "-c", str(DEFAULT_CONTEXT if context is None else int(context)),
    ]
    return command_for(Path(executable), args)


def failure_message(tail: str, reason: str) -> str:
    lowered = tail.lower()
    if "out of memory" in lowered or "failed to allocate" in lowered:
        return "This computer does not have enough memory for this model."
    if "unknown model architecture" in lowered or "unknown architecture" in lowered:
        return "This model is not supported by the selected runtime."
    if reason == "timeout":
        return "The local model took too long to load."
    if "gguf" in lowered and ("invalid" in lowered or "magic" in lowered):
        return "This file is not a usable GGUF model."
    return "The local model failed to start."


def local_server_snapshot() -> dict:
    return _runtime.snapshot()


def local_server_uses(resource_id: str) -> bool:
    return _runtime.uses(resource_id)


def ensure_local_server(store, timeout_s: float = START_TIMEOUT_S, cancel=None) -> LocalEndpoint:
    return _runtime.ensure(store, timeout_s, cancel)


def begin_local_server(store) -> None:
    _runtime.begin(store)


def stop_local_server() -> None:
    _runtime.stop()


def reset_local_server_for_tests() -> None:
    stop_local_server()


def _selection(store):
    state = store.state()
    runtime = store.resource(state.selected_llama_runtime_id or "")
    model = store.resource(state.selected_gguf_model_id or "")
    if runtime is None or runtime.kind != "llama_runtime" or model is None or model.kind != "gguf":
        raise SemanticError("local_model_missing", "Choose a llama.cpp runtime and a GGUF model.")
    from pathlib import Path

    if not Path(runtime.local_path).is_file() or not Path(model.local_path).is_file():
        raise SemanticError("local_model_missing", "The selected local model is missing.")
    return runtime, model, state.local_context_size, state.local_threads


def _ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


def _wait_ready(process, port: int, deadline: float, cancel, generation: int, runtime: _Runtime) -> str:
    url = f"http://{LOOPBACK}:{port}/v1/models"
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_cancelled():
            return "stopped"
        with runtime._lock:
            if generation != runtime._generation:
                return "stopped"
        if process.poll() is not None:
            tail = background_tail(process).lower()
            if "address already in use" in tail or "failed to bind" in tail:
                return "bind"
            return "exit"
        if _models_ready(url):
            return "ready"
        time.sleep(0.05)
    return "timeout"


def _models_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def _clip(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:_DIAGNOSTIC_CAP]
