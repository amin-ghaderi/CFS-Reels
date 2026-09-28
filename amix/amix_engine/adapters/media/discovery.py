"""Locate ffmpeg and ffprobe for development. This does not download them.

Order, and only this order:

1. ``AMIX_FFMPEG`` and ``AMIX_FFPROBE`` when either is set. A set variable must
   name an existing file. If only one is set, the other name is taken from the
   same directory. A wrong explicit path is an error. It does not fall through
   to PATH.
2. ``amix/tools/ffmpeg`` and ``amix/tools/ffprobe`` (``.exe`` on Windows) when
   both files exist.
3. ``ffmpeg`` and ``ffprobe`` on PATH.

Packaged builds can replace this function with sidecar paths. Media jobs call
it in one place.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from amix.amix_engine.adapters.media.errors import MediaToolMissing
from amix.amix_engine.adapters.media.process import run_process

_ENV_FFMPEG = "AMIX_FFMPEG"
_ENV_FFPROBE = "AMIX_FFPROBE"


@dataclass(frozen=True)
class MediaTools:
    ffmpeg: Path
    ffprobe: Path
    ffmpeg_version: str
    ffprobe_version: str


def discover_tools(environ: dict[str, str] | None = None, *, root: Path | None = None) -> MediaTools:
    env = os.environ if environ is None else environ
    pair = _from_env(env) or _from_tools_dir(root) or _from_path()
    if pair is None:
        raise MediaToolMissing("FFmpeg tools are not available.")
    ffmpeg, ffprobe = pair
    return MediaTools(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        ffmpeg_version=_version(ffmpeg),
        ffprobe_version=_version(ffprobe),
    )


def _from_env(env: dict[str, str]) -> tuple[Path, Path] | None:
    ffmpeg_text = env.get(_ENV_FFMPEG, "").strip()
    ffprobe_text = env.get(_ENV_FFPROBE, "").strip()
    if not ffmpeg_text and not ffprobe_text:
        return None
    ffmpeg = Path(ffmpeg_text) if ffmpeg_text else None
    ffprobe = Path(ffprobe_text) if ffprobe_text else None
    if ffmpeg is not None and ffprobe is None:
        ffprobe = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
    if ffprobe is not None and ffmpeg is None:
        ffmpeg = ffprobe.with_name("ffmpeg.exe" if ffprobe.suffix.lower() == ".exe" else "ffmpeg")
    if ffmpeg is None or ffprobe is None or not ffmpeg.is_file() or not ffprobe.is_file():
        raise MediaToolMissing("FFmpeg tools are not available.")
    return ffmpeg, ffprobe


def _from_tools_dir(root: Path | None) -> tuple[Path, Path] | None:
    base = root if root is not None else Path(__file__).resolve().parents[3]
    names = ("ffmpeg.exe", "ffprobe.exe") if os.name == "nt" else ("ffmpeg", "ffprobe")
    ffmpeg = base / "tools" / names[0]
    ffprobe = base / "tools" / names[1]
    if ffmpeg.is_file() and ffprobe.is_file():
        return ffmpeg, ffprobe
    return None


def _from_path() -> tuple[Path, Path] | None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return None
    return Path(ffmpeg), Path(ffprobe)


def _version(executable: Path) -> str:
    try:
        result = run_process([str(executable), "-hide_banner", "-version"], cancel=None, max_stdout=4000)
    except OSError:
        return "unknown"
    if result.code != 0:
        return "unknown"
    line = result.stdout.splitlines()[0].strip() if result.stdout else ""
    return line[:200] or "unknown"
