"""Display-pixel crops and the video filter that matches probed rotation.

Layout bindings use the probed display size. Decoded frames are rotated to
that size before a crop is read. Encoded size is not mixed in silently.
"""
from __future__ import annotations

from amix.amix_engine.domain.types import LayoutBinding, ParticipantId

# The lip thresholds were measured after each crop was resampled to this tile.
ANALYSIS_TILE_W = 448
ANALYSIS_TILE_H = 252
SAMPLE_FPS = 8


def display_video_filter(rotation_degrees: int | None, sample_fps: int = SAMPLE_FPS) -> str:
    """FFmpeg filter that emits display-oriented frames at the sample cadence.

    Callers pass ``-noautorotate`` so this filter is the only rotation.
    """
    steps = [f"fps={sample_fps}"]
    if rotation_degrees is not None:
        rotation = int(rotation_degrees) % 360
        if rotation == 90:
            steps.append("transpose=1")
        elif rotation == 270:
            steps.append("transpose=2")
        elif rotation == 180:
            steps.append("hflip,vflip")
    return ",".join(steps)


def seek_offset_seconds(window_start_us: int, container_start_us: int) -> str:
    """File seek for a canonical window start. Three decimal places, like the proof."""
    delta = window_start_us - container_start_us
    if delta < 0:
        raise ValueError("analysis window starts before the source")
    sign = "-" if delta < 0 else ""
    millis = delta // 1000
    return f"{sign}{millis // 1000}.{millis % 1000:03d}"


def duration_seconds(start_us: int, end_us: int) -> str:
    span = end_us - start_us
    if span <= 0:
        raise ValueError("analysis window is empty")
    millis = span // 1000
    return f"{millis // 1000}.{millis % 1000:03d}"


def clip_rect(frame_w: int, frame_h: int, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    if frame_w <= 0 or frame_h <= 0 or w <= 0 or h <= 0:
        return None
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(frame_w, x + w)
    y1 = min(frame_h, y + h)
    if x1 - x0 < 8 or y1 - y0 < 6:
        return None
    return x0, y0, x1 - x0, y1 - y0


def binding_at(bindings: list[LayoutBinding], participant_id: ParticipantId, time_us: int) -> LayoutBinding | None:
    """The region that contains this canonical time.

    More than one match is ambiguous. That participant is left without a
    region for the sample instead of blending rectangles.
    """
    matches = [
        binding for binding in bindings
        if binding.participant_id == participant_id and binding.span.contains(time_us)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def participants_in_window(bindings: list[LayoutBinding], start_us: int, end_us: int) -> tuple[ParticipantId, ...]:
    found: list[ParticipantId] = []
    for binding in bindings:
        if binding.span.end_us <= start_us or binding.span.start_us >= end_us:
            continue
        if binding.participant_id not in found:
            found.append(binding.participant_id)
    return tuple(sorted(found, key=lambda item: item.value))
