"""One small poster still from an existing preview file.

Startup never calls this. A failed poster does not fail preview preparation.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing

log = logging.getLogger("amix.media")


def write_project_poster(proxy_file: Path, private: Path) -> None:
    destination = private / "cache" / "poster.jpg"
    temporary = destination.with_suffix(".jpg.part")
    try:
        tools = discover_tools()
        destination.parent.mkdir(parents=True, exist_ok=True)
        flags = {}
        if os.name == "nt":
            flags["creationflags"] = subprocess.CREATE_NO_WINDOW
        completed = subprocess.run(
            [
                str(tools.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "0.5",
                "-i",
                str(proxy_file),
                "-frames:v",
                "1",
                "-vf",
                "scale=320:-2",
                "-q:v",
                "5",
                "-y",
                str(temporary),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
            **flags,
        )
        if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            temporary.unlink(missing_ok=True)
            return
        temporary.replace(destination)
    except (OSError, subprocess.TimeoutExpired, MediaToolMissing):
        temporary.unlink(missing_ok=True)
        log.info("poster was not written")
