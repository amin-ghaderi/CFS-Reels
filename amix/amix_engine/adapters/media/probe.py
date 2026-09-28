"""Parse the ffprobe fields AMIX stores. The raw document is not the domain model."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from amix.amix_engine.adapters.media.errors import ProbeFailed
from amix.amix_engine.adapters.media.process import CancelSignal, run_process
from amix.amix_engine.adapters.media.timeparse import seconds_text_to_us

PROBE_CONFIG = "amix.probe.v1"


@dataclass(frozen=True)
class ProbeMetadata:
    container: str | None
    duration_us: int | None
    duration_source: str | None
    container_start_us: int | None
    bit_rate: int | None
    video_codec: str | None
    width: int | None
    height: int | None
    pixel_format: str | None
    fps_num: int | None
    fps_den: int | None
    r_fps_num: int | None
    r_fps_den: int | None
    time_base_num: int | None
    time_base_den: int | None
    video_start_us: int | None
    video_duration_us: int | None
    rotation_degrees: int | None
    audio_codec: str | None
    sample_rate: int | None
    audio_channels: int | None
    channel_layout: str | None
    audio_start_us: int | None
    audio_duration_us: int | None
    has_video: bool
    has_audio: bool


def probe_command(ffprobe: Path, media: Path) -> list[str]:
    return [
        str(ffprobe),
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media),
    ]


def execute_probe(ffprobe: Path, media: Path, cancel: CancelSignal | None = None) -> ProbeMetadata:
    result = run_process(probe_command(ffprobe, media), cancel)
    if result.code != 0:
        raise ProbeFailed("ffprobe failed")
    return parse_probe_json(result.stdout)


def parse_probe_json(text: str) -> ProbeMetadata:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProbeFailed("ffprobe did not return JSON") from exc
    if not isinstance(payload, dict):
        raise ProbeFailed("ffprobe did not return JSON")
    return parse_probe_document(payload)


def parse_probe_document(payload: dict) -> ProbeMetadata:
    streams = payload.get("streams")
    if streams is None:
        streams = []
    if not isinstance(streams, list):
        raise ProbeFailed("ffprobe streams were not a list")
    video = _first(streams, "video")
    audio = _first(streams, "audio")
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    video_duration = _time(video.get("duration")) if video else None
    audio_duration = _time(audio.get("duration")) if audio else None
    format_duration = _time(fmt.get("duration"))
    duration_us, duration_source = _select_duration(
        has_video=video is not None,
        video_us=video_duration,
        format_us=format_duration,
        audio_us=audio_duration,
    )
    fps = _rate(video.get("avg_frame_rate")) if video else None
    if fps is None and video is not None:
        fps = _rate(video.get("r_frame_rate"))
    r_fps = _rate(video.get("r_frame_rate")) if video else None
    time_base = _rate(video.get("time_base")) if video else None
    coded_width = _positive_int(video.get("width")) if video else None
    coded_height = _positive_int(video.get("height")) if video else None
    rotation = _rotation(video) if video else None
    width, height = _display_size(coded_width, coded_height, rotation)
    return ProbeMetadata(
        container=_text(fmt.get("format_name")),
        duration_us=duration_us,
        duration_source=duration_source,
        container_start_us=_time(fmt.get("start_time")),
        bit_rate=_positive_int(fmt.get("bit_rate")),
        video_codec=_text(video.get("codec_name")) if video else None,
        width=width,
        height=height,
        pixel_format=_text(video.get("pix_fmt")) if video else None,
        fps_num=None if fps is None else fps[0],
        fps_den=None if fps is None else fps[1],
        r_fps_num=None if r_fps is None else r_fps[0],
        r_fps_den=None if r_fps is None else r_fps[1],
        time_base_num=None if time_base is None else time_base[0],
        time_base_den=None if time_base is None else time_base[1],
        video_start_us=_time(video.get("start_time")) if video else None,
        video_duration_us=video_duration,
        rotation_degrees=rotation,
        audio_codec=_text(audio.get("codec_name")) if audio else None,
        sample_rate=_positive_int(audio.get("sample_rate")) if audio else None,
        audio_channels=_positive_int(audio.get("channels")) if audio else None,
        channel_layout=_text(audio.get("channel_layout")) if audio else None,
        audio_start_us=_time(audio.get("start_time")) if audio else None,
        audio_duration_us=audio_duration,
        has_video=video is not None,
        has_audio=audio is not None,
    )


def _select_duration(
    *,
    has_video: bool,
    video_us: int | None,
    format_us: int | None,
    audio_us: int | None,
) -> tuple[int | None, str | None]:
    """Pick one duration. Disagreeing sources are not averaged."""
    if has_video and video_us is not None:
        return video_us, "video"
    if format_us is not None:
        return format_us, "format"
    if audio_us is not None:
        return audio_us, "audio"
    return None, None


def _first(streams: list, codec_type: str) -> dict | None:
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == codec_type:
            return stream
    return None


def _time(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "N/A"}:
        return None
    try:
        return seconds_text_to_us(text)
    except ValueError as exc:
        raise ProbeFailed("ffprobe time was not a decimal") from exc


def _rate(value: object) -> tuple[int, int] | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "0/0", "N/A"} or "/" not in text:
        return None
    left, right = text.split("/", 1)
    if not _is_int(left) or not _is_int(right):
        return None
    numerator = int(left)
    denominator = int(right)
    if numerator <= 0 or denominator <= 0:
        return None
    return numerator, denominator


def _rotation(stream: dict) -> int | None:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    raw = tags.get("rotate")
    if raw is None:
        for item in stream.get("side_data_list") or []:
            if isinstance(item, dict) and item.get("rotation") is not None:
                raw = item.get("rotation")
                break
    if raw is None:
        return None
    return _degrees(raw)


def _degrees(raw: object) -> int | None:
    text = str(raw).strip()
    if text in {"", "N/A"}:
        return None
    try:
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        value = Decimal(text).to_integral_value(rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    degrees = int(value) % 360
    if degrees > 180:
        degrees -= 360
    return degrees


def _display_size(width: int | None, height: int | None, rotation: int | None) -> tuple[int | None, int | None]:
    if width is None or height is None:
        return width, height
    if rotation is not None and abs(rotation) % 180 == 90:
        return height, width
    return width, height


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "N/A"}:
        return None
    return text[:200]


def _positive_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not _is_int(text):
        return None
    number = int(text)
    if number <= 0:
        return None
    return number


def _is_int(text: str) -> bool:
    if text.startswith("-"):
        text = text[1:]
    return text.isdigit()
