"""SRT and WebVTT serialization from sequence-time cue boundaries."""
from __future__ import annotations


def format_srt_timestamp(us: int) -> str:
    return _format(us, ",")


def format_vtt_timestamp(us: int) -> str:
    return _format(us, ".")


def render_srt(cues: list[dict]) -> str:
    blocks = [_cue_block(index, cue, ",") for index, cue in enumerate(cues, start=1)]
    body = "\n\n".join(blocks)
    return f"{body}\n" if body else ""


def render_vtt(cues: list[dict]) -> str:
    blocks = [_cue_block(index, cue, ".") for index, cue in enumerate(cues, start=1)]
    body = "\n\n".join(blocks)
    if body:
        return f"WEBVTT\n\n{body}\n"
    return "WEBVTT\n"


def _cue_block(index: int, cue: dict, separator: str) -> str:
    start_us = int(cue["sequence_start_us"])
    end_us = int(cue["sequence_end_us"])
    start_ms = _milliseconds(start_us)
    end_ms = _milliseconds(end_us)
    if end_ms <= start_ms:
        end_ms = start_ms + 1
    text = cue["manual_text"] if cue.get("manual_text") else cue["generated_text"]
    return (
        f"{index}\n"
        f"{_from_milliseconds(start_ms, separator)} --> {_from_milliseconds(end_ms, separator)}\n"
        f"{text}"
    )


def _format(us: int, separator: str) -> str:
    return _from_milliseconds(_milliseconds(us), separator)


def _milliseconds(us: int) -> int:
    if us < 0:
        us = 0
    return (us + 500) // 1000


def _from_milliseconds(total_ms: int, separator: str) -> str:
    milliseconds = total_ms % 1000
    total_seconds = total_ms // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"
