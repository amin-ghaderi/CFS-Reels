"""Run one media tool as an argument list. There is no shell.

A child is registered with this module in the same transition that creates it.
Cancellation and shutdown can then terminate it. There is no interval where
the OS process exists and this owner cannot find it, except inside ``Popen``
itself, which is waited out before shutdown finishes.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from collections.abc import Mapping
from typing import Callable, Protocol

from amix.amix_engine.adapters.media.errors import ProcessCancelled

_STDERR_CAP = 4000
_POLL_S = 0.05
_GRACE_S = 0.4
_lifecycle_hook: Callable[[str], None] | None = None
_owned: dict[int, subprocess.Popen] = {}
_spawning = 0
_ownership = threading.Condition(threading.Lock())


class CancelSignal(Protocol):
    def is_cancelled(self) -> bool:
        """True once the caller wants the process tree to stop."""


@dataclass(frozen=True)
class ProcessResult:
    code: int
    stdout: str
    stderr_tail: str


def set_lifecycle_hook(hook: Callable[[str], None] | None) -> None:
    """Test-only observation of spawn stages. Not a product API."""
    global _lifecycle_hook
    _lifecycle_hook = hook


def owned_pids() -> list[int]:
    with _ownership:
        return list(_owned)


def spawn_background(args: list[str]) -> subprocess.Popen:
    """Start a long-lived owned child. The caller stops it with ``stop_background``."""
    if not args or not isinstance(args, list):
        raise ValueError("processes take an argument list")
    process = _spawn_owned(args, None)
    tail = bytearray()
    lock = threading.Lock()
    process._amix_tail = tail  # type: ignore[attr-defined]
    process._amix_tail_lock = lock  # type: ignore[attr-defined]
    threading.Thread(target=_read_stderr, args=(process.stderr, tail, lock), name="amix-owned-stderr", daemon=True).start()
    threading.Thread(target=_drain, args=(process.stdout,), name="amix-owned-stdout", daemon=True).start()
    return process


def background_tail(process: subprocess.Popen) -> str:
    lock = getattr(process, "_amix_tail_lock", None)
    tail = getattr(process, "_amix_tail", bytearray())
    if lock is None:
        return ""
    with lock:
        return bytes(tail).decode("utf-8", errors="replace")


def stop_background(process: subprocess.Popen) -> None:
    _terminate_tree(process)
    _reap(process)
    _release(process)
    _close_pipes(process)


def _drain(pipe) -> None:
    try:
        if pipe is None:
            return
        while pipe.read(1024):
            continue
    finally:
        if pipe is not None:
            pipe.close()


def terminate_owned_processes(timeout_s: float) -> None:
    """Finish any spawn transition, then stop every registered child."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    announced = False
    while True:
        with _ownership:
            if not _spawning or time.monotonic() >= deadline:
                processes = list(_owned.values())
                break
            remaining = deadline - time.monotonic()
        if not announced:
            announced = True
            _note("shutdown_waiting")
        with _ownership:
            if not _spawning or time.monotonic() >= deadline:
                processes = list(_owned.values())
                break
            _ownership.wait(min(remaining, 30.0))
    for process in processes:
        _terminate_tree(process)
        _reap(process)


def run_process(
    args: list[str],
    cancel: CancelSignal | None,
    *,
    on_line: Callable[[str], None] | None = None,
    max_stdout: int = 2_000_000,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    if not args or not isinstance(args, list):
        raise ValueError("media tools take an argument list")
    process = _spawn_owned(args, cancel, env)
    stdout_lines: Queue[bytes | None] = Queue()
    stderr_tail = bytearray()
    stderr_lock = threading.Lock()
    stdout_thread = threading.Thread(
        target=_read_stdout,
        args=(process.stdout, stdout_lines),
        name="amix-media-stdout",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_stderr,
        args=(process.stderr, stderr_tail, stderr_lock),
        name="amix-media-stderr",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    collected: list[str] = []
    collected_bytes = 0
    killed = False
    try:
        while True:
            if cancel is not None and cancel.is_cancelled() and not killed:
                _terminate_tree(process)
                killed = True
            try:
                line = stdout_lines.get(timeout=_POLL_S)
            except Empty:
                if process.poll() is not None and stdout_lines.empty():
                    break
                continue
            if line is None:
                break
            text = line.decode("utf-8", errors="replace")
            if on_line is not None:
                on_line(text.rstrip("\r\n"))
            else:
                collected_bytes += len(line)
                if collected_bytes > max_stdout:
                    _terminate_tree(process)
                    raise OSError("media tool output exceeded the capture limit")
                collected.append(text)
        code = process.wait(timeout=2)
    finally:
        if process.poll() is None:
            _terminate_tree(process)
            _reap(process)
        _release(process)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        with stderr_lock:
            tail = bytes(stderr_tail).decode("utf-8", errors="replace")
    if killed:
        raise ProcessCancelled()
    return ProcessResult(code=code, stdout="".join(collected), stderr_tail=tail[-_STDERR_CAP:])


def _read_stdout(pipe, lines: Queue[bytes | None]) -> None:
    try:
        if pipe is not None:
            for line in iter(pipe.readline, b""):
                lines.put(line)
    finally:
        lines.put(None)
        if pipe is not None:
            pipe.close()


def _read_stderr(pipe, tail: bytearray, lock: threading.Lock) -> None:
    try:
        if pipe is None:
            return
        while True:
            chunk = pipe.read(1024)
            if not chunk:
                break
            with lock:
                tail.extend(chunk)
                if len(tail) > _STDERR_CAP:
                    del tail[: len(tail) - _STDERR_CAP]
    finally:
        if pipe is not None:
            pipe.close()


def _note(stage: str) -> None:
    hook = _lifecycle_hook
    if hook is not None:
        hook(stage)


def _begin_spawn() -> None:
    global _spawning
    with _ownership:
        _spawning += 1


def _end_spawn() -> None:
    global _spawning
    with _ownership:
        _spawning -= 1
        if _spawning == 0:
            _ownership.notify_all()


def _register(process: subprocess.Popen) -> None:
    with _ownership:
        _owned[process.pid] = process


def _release(process: subprocess.Popen) -> None:
    with _ownership:
        current = _owned.get(process.pid)
        if current is process:
            _owned.pop(process.pid, None)


def _spawn_owned(
    args: list[str],
    cancel: CancelSignal | None,
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen:
    """Create the child and register it before returning to the caller."""
    _begin_spawn()
    process: subprocess.Popen | None = None
    try:
        _note("before_spawn")
        if cancel is not None and cancel.is_cancelled():
            raise ProcessCancelled()
        kwargs = _spawn_kwargs()
        if env is not None:
            kwargs["env"] = dict(env)
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **kwargs,
        )
        _register(process)
        _note("after_register")
        if cancel is not None and cancel.is_cancelled():
            _terminate_tree(process)
            _reap(process)
            _close_pipes(process)
            _release(process)
            process = None
            raise ProcessCancelled()
        return process
    except ProcessCancelled:
        raise
    except Exception:
        if process is not None:
            _terminate_tree(process)
            _reap(process)
            _close_pipes(process)
            _release(process)
        raise
    finally:
        _end_spawn()


def _reap(process: subprocess.Popen) -> None:
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return


def _close_pipes(process: subprocess.Popen) -> None:
    for pipe in (process.stdout, process.stderr, process.stdin):
        if pipe is None:
            continue
        try:
            pipe.close()
        except OSError:
            continue


def _spawn_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_tree(process: subprocess.Popen) -> None:
    """Stop one process tree. A second caller is a no-op once it has exited."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        _taskkill(process.pid, force=False)
        try:
            process.wait(timeout=_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                _taskkill(process.pid, force=True)
        return
    import signal

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    try:
        process.wait(timeout=_GRACE_S)
    except subprocess.TimeoutExpired:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            return


def _taskkill(pid: int, *, force: bool) -> None:
    command = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, check=False)
