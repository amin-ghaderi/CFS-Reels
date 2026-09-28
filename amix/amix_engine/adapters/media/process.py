"""Run one media tool as an argument list. There is no shell."""
from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Callable, Protocol

from amix.amix_engine.adapters.media.errors import ProcessCancelled

_STDERR_CAP = 4000
_POLL_S = 0.05
_GRACE_S = 0.4


class CancelSignal(Protocol):
    def is_cancelled(self) -> bool:
        """True once the caller wants the process tree to stop."""


@dataclass(frozen=True)
class ProcessResult:
    code: int
    stdout: str
    stderr_tail: str


def run_process(
    args: list[str],
    cancel: CancelSignal | None,
    *,
    on_line: Callable[[str], None] | None = None,
    max_stdout: int = 2_000_000,
) -> ProcessResult:
    if not args or not isinstance(args, list):
        raise ValueError("media tools take an argument list")
    process = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        **_spawn_kwargs(),
    )
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
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
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


def _spawn_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        _taskkill(process.pid, force=False)
        try:
            process.wait(timeout=_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            _taskkill(process.pid, force=True)
        return
    import signal

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_GRACE_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def _taskkill(pid: int, *, force: bool) -> None:
    command = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, check=False)
