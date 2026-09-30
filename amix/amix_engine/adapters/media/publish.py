"""Publish a complete file under its final name.

Readers that see the destination must see the full payload. The temporary
sibling is not the marker. ``Path.write_text`` is not used: it truncates the
destination before the bytes land, so a poller can observe an empty file.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path


def publish_text(path: Path | str, text: str) -> None:
    """Write ``text`` and replace ``path`` only after the bytes are flushed."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = text if text.endswith("\n") else f"{text}\n"
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _replace(source: Path, destination: Path) -> None:
    """Atomically publish ``source`` as ``destination``.

    Windows refuses the replace while another handle still has the destination
    open. That is a sharing violation, not a partial write, so the retry waits
    only for that handle to close.
    """
    for attempt in range(40):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.002)


def publish_pid(path: Path | str, pid: int) -> None:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("a pid marker needs a process id")
    publish_text(path, str(pid))


def read_pid(path: Path | str) -> int | None:
    """Return a complete pid, or None when the marker is absent.

    An empty or partial file is not a pid. Atomic publication means the
    final path does not appear in that state.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    text = text.strip()
    if not text.isdigit():
        return None
    return int(text)
