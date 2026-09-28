"""Neutral speech evidence. Times here are relative integer microseconds."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

_RESULT_CAP = 32 * 1024 * 1024


class SttEvidenceError(ValueError):
    """The worker result is not usable transcript evidence."""


@dataclass(frozen=True)
class SttWord:
    text: str
    start_us: int
    end_us: int
    confidence: float | None
    segment: int


@dataclass(frozen=True)
class SttEvidence:
    words: tuple[SttWord, ...]
    language: str | None
    language_probability: float | None
    faster_whisper_version: str
    ctranslate2_version: str


def evidence_document(evidence: SttEvidence) -> dict[str, Any]:
    return {
        "language": evidence.language,
        "language_probability": evidence.language_probability,
        "faster_whisper_version": evidence.faster_whisper_version,
        "ctranslate2_version": evidence.ctranslate2_version,
        "words": [
            {
                "text": word.text,
                "start_us": word.start_us,
                "end_us": word.end_us,
                "confidence": word.confidence,
                "segment": word.segment,
            }
            for word in evidence.words
        ],
    }


def dump_evidence(evidence: SttEvidence) -> str:
    return json.dumps(evidence_document(evidence), sort_keys=True)


def load_evidence(raw: str) -> SttEvidence:
    if len(raw.encode("utf-8")) > _RESULT_CAP:
        raise SttEvidenceError("transcription result is too large")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SttEvidenceError("transcription result is not json") from exc
    return evidence_from_document(payload)


def evidence_from_document(payload: object) -> SttEvidence:
    if not isinstance(payload, dict):
        raise SttEvidenceError("transcription result is not an object")
    words_raw = payload.get("words")
    if not isinstance(words_raw, list):
        raise SttEvidenceError("transcription result has no words")
    words: list[SttWord] = []
    for item in words_raw:
        if not isinstance(item, dict):
            raise SttEvidenceError("transcription word is not an object")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SttEvidenceError("transcription word text is empty")
        start = _non_negative_int(item.get("start_us"), "start")
        end = _non_negative_int(item.get("end_us"), "end")
        if end <= start:
            raise SttEvidenceError("transcription word ends before it starts")
        segment = _non_negative_int(item.get("segment"), "segment")
        words.append(SttWord(
            text=text.strip(),
            start_us=start,
            end_us=end,
            confidence=_confidence(item.get("confidence")),
            segment=segment,
        ))
    return SttEvidence(
        words=tuple(words),
        language=_language(payload.get("language")),
        language_probability=_probability(payload.get("language_probability")),
        faster_whisper_version=_version(payload.get("faster_whisper_version")),
        ctranslate2_version=_version(payload.get("ctranslate2_version")),
    )


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SttEvidenceError(f"transcription word {label} is not an integer microsecond")
    return value


def _confidence(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        return None
    return number


def _probability(value: object) -> float | None:
    return _confidence(value)


def _language(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or len(text) > 16:
        return None
    return text


def _version(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    return value.strip()[:64]
