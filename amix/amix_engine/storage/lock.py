"""Exclusive project write lock held by an open file handle.

The lock is the OS byte/file lock. ``project.lock.json`` is only a note
(pid, host, time). A stale note does not keep the project locked after the
holding process has exited.

Two machines writing one synced folder is not supported and is not detected here.
"""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from amix.amix_engine.storage.errors import ProjectAlreadyLocked

_LOCK_BYTES = 1


class ProjectWriteLock:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._handle: IO[bytes] | None = None

    @property
    def lock_path(self) -> Path:
        return self.root / "project.lock"

    @property
    def note_path(self) -> Path:
        return self.root / "project.lock.json"

    def acquire(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+b")
        try:
            if handle.seek(0, os.SEEK_END) < _LOCK_BYTES:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _lock_handle(handle)
        except OSError as exc:
            handle.close()
            raise ProjectAlreadyLocked(
                f"project is already open for write: {self.root}"
            ) from exc
        self._handle = handle
        note = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self.note_path.write_text(json.dumps(note), encoding="utf-8")

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            _unlock_handle(handle)
        finally:
            handle.close()


def _lock_handle(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTES)
        return
    import fcntl
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTES)
        except OSError:
            pass
        return
    import fcntl
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
