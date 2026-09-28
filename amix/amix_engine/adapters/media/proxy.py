"""V1 preview proxy. One profile, argument lists only.

Profile ``amix.proxy.v1``:

- MP4 container, H.264 (libx264, veryfast, CRF 23, yuv420p)
- AAC audio at 128 kbps when the source has an audio stream
- no invented silent audio when the source is video-only
- picture fits inside 1280×720, aspect preserved, never upscaled
- even dimensions only when a scale is required
- a keyframe at least every 2 seconds
- FFmpeg's default display-rotation is left on, so phone rotation is baked
  into upright pixels. Scale uses the probed display size.
- no seek and no trim. ``-copyts`` plus zero mux delay keeps source timestamps
  as far as the MP4 muxer allows.

Timestamp policy ``container_normalized_v1``:

MP4 output may still start at container time 0. AMIX does not rebase the
source asset. Playback time maps with:

canonical_source_us = proxy_time_us - proxy_container_start_us + source_container_start_us

Missing starts count as 0 in that formula. The source asset's own times stay
as probed.
"""
from __future__ import annotations

from pathlib import Path

from amix.amix_engine.adapters.media.probe import ProbeMetadata

PROXY_PROFILE = "amix.proxy.v1"
TIMESTAMP_POLICY = "container_normalized_v1"
MAX_WIDTH = 1280
MAX_HEIGHT = 720


def preview_size(width: int, height: int) -> tuple[int, int] | None:
    """Return a scale target, or None when the source already fits and is even."""
    if width <= 0 or height <= 0:
        return None
    if width <= MAX_WIDTH and height <= MAX_HEIGHT and width % 2 == 0 and height % 2 == 0:
        return None
    if width * MAX_HEIGHT <= height * MAX_WIDTH:
        out_h = min(height, MAX_HEIGHT)
        out_w = (width * out_h) // height
    else:
        out_w = min(width, MAX_WIDTH)
        out_h = (height * out_w) // width
    out_w -= out_w % 2
    out_h -= out_h % 2
    if out_w < 2:
        out_w = 2
    if out_h < 2:
        out_h = 2
    if out_w > width or out_h > height:
        out_w = max(2, width - (width % 2))
        out_h = max(2, height - (height % 2))
    if out_w == width and out_h == height:
        return None
    return out_w, out_h


def proxy_command(ffmpeg: Path, source: Path, dest: Path, probe: ProbeMetadata) -> list[str]:
    if not probe.has_video or probe.width is None or probe.height is None:
        raise ValueError("proxy requires a probed video picture")
    args = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-copyts",
        "-i",
        str(source),
        "-map",
        "0:v:0",
    ]
    if probe.has_audio:
        args.extend(["-map", "0:a:0"])
    args.extend([
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-force_key_frames",
        "expr:gte(t,n_forced*2)",
    ])
    fitted = preview_size(probe.width, probe.height)
    if fitted is not None:
        args.extend(["-vf", f"scale={fitted[0]}:{fitted[1]}"])
    if probe.has_audio:
        args.extend(["-c:a", "aac", "-b:a", "128k"])
    args.extend([
        "-muxpreload",
        "0",
        "-muxdelay",
        "0",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(dest),
    ])
    return args


def progress_basis_points(out_time_us: int, duration_us: int | None, previous: int) -> int:
    """Monotonic 0..9999. Unknown duration does not invent a percent."""
    if duration_us is None or duration_us <= 0 or out_time_us < 0:
        return previous
    points = (out_time_us * 10000) // duration_us
    if points > 9999:
        points = 9999
    if points < previous:
        return previous
    return points


def progress_time_us(line: str) -> int | None:
    if not line.startswith("out_time_us="):
        return None
    raw = line.split("=", 1)[1].strip()
    if raw.startswith("-"):
        return None
    if not raw.isdigit():
        return None
    return int(raw)
