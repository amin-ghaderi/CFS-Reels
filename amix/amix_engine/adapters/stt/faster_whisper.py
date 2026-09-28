"""faster-whisper boundary.

This module is the only place that constructs a speech model. It emits relative
integer microseconds. It does not know about projects, jobs, or proxies.
"""
from __future__ import annotations

import importlib.metadata
import math
import os
from collections.abc import Callable, Iterable
from pathlib import Path

from amix.amix_engine.adapters.stt.evidence import SttEvidence, SttEvidenceError, SttWord
from amix.amix_engine.adapters.stt.profile import TranscriptionProfile
from amix.amix_engine.adapters.stt.timing import external_seconds_to_us
from amix.amix_engine.time.clock import TimeError


def evidence_from_segments(segments: Iterable[object], info: object | None = None) -> SttEvidence:
    """Convert faster-whisper-like segments once. Word order follows the iterator."""
    words: list[SttWord] = []
    for segment_index, segment in enumerate(segments):
        produced = getattr(segment, "words", None) or []
        for token in produced:
            text = _token_text(token)
            if not text:
                continue
            start = _boundary_us(getattr(token, "start", None))
            end = _boundary_us(getattr(token, "end", None))
            if end <= start:
                raise SttEvidenceError("transcription word ends before it starts")
            words.append(SttWord(
                text=text,
                start_us=start,
                end_us=end,
                confidence=_optional_unit(getattr(token, "probability", None)),
                segment=segment_index,
            ))
    language = None
    probability = None
    if info is not None:
        raw_language = getattr(info, "language", None)
        if isinstance(raw_language, str) and raw_language.strip():
            language = raw_language.strip().lower()
        probability = _optional_unit(getattr(info, "language_probability", None))
    return SttEvidence(
        words=tuple(words),
        language=language,
        language_probability=probability,
        faster_whisper_version=_package_version("faster-whisper"),
        ctranslate2_version=_package_version("ctranslate2"),
    )


def transcribe_file(
    source: Path,
    model_path: Path,
    *,
    profile: TranscriptionProfile,
    language: str | None,
    device: str,
    compute_type: str,
    on_segment_end_us: Callable[[int], None] | None = None,
) -> SttEvidence:
    """Load one local model directory and transcribe the whole file.

    A repository id is not accepted. Offline hub flags are set before import.
    """
    if not profile.word_timestamps:
        raise SttEvidenceError("word timestamps are required")
    if not model_path.is_dir() or not (model_path / "model.bin").is_file():
        raise SttEvidenceError("speech model directory is not usable")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(model_path.resolve()),
        device=device,
        compute_type=compute_type,
        local_files_only=True,
    )
    segments, info = model.transcribe(
        str(source),
        language=language,
        task=profile.task,
        beam_size=profile.beam_size,
        vad_filter=profile.vad_filter,
        word_timestamps=True,
        temperature=list(profile.temperature),
    )
    words: list[SttWord] = []
    for index, segment in enumerate(segments):
        end = getattr(segment, "end", None)
        if on_segment_end_us is not None and end is not None:
            on_segment_end_us(external_seconds_to_us(end))
        piece = evidence_from_segments([segment], None)
        words.extend(
            SttWord(word.text, word.start_us, word.end_us, word.confidence, index)
            for word in piece.words
        )
    detected = evidence_from_segments([], info)
    return SttEvidence(
        words=tuple(words),
        language=detected.language,
        language_probability=detected.language_probability,
        faster_whisper_version=detected.faster_whisper_version,
        ctranslate2_version=detected.ctranslate2_version,
    )


def _token_text(token: object) -> str:
    raw = getattr(token, "word", None)
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def _boundary_us(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SttEvidenceError("transcription word time is missing")
    try:
        return external_seconds_to_us(value)
    except TimeError as exc:
        raise SttEvidenceError("transcription word time is not usable") from exc


def _optional_unit(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        return None
    return number


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
