"""Deterministic caption cues from effective transcript words.

Segmentation uses word order, sentence punctuation, silence, duration, and a
word-count ceiling. It does not use the output canvas. A cue never crosses a
sequence clip, so a removed gap cannot sit inside one caption.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from amix.amix_engine.editorial.sequence import source_to_sequence_us

PROFILE_ID = "amix.caption.segment.v1"
MAX_CUE_WORDS = 12
MAX_CUE_DURATION_US = 6_000_000
GAP_BREAK_US = 800_000
_TERMINATORS = frozenset(".!?؟۔…")


class CaptionRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CaptionWord:
    word_id: str
    sequence: int
    effective_text: str
    start_us: int
    end_us: int


@dataclass(frozen=True)
class BuiltCue:
    order_index: int
    first_word_id: str
    last_word_id: str
    source_start_us: int
    source_end_us: int
    sequence_start_us: int
    sequence_end_us: int
    generated_text: str


def word_midpoint_us(start_us: int, end_us: int) -> int:
    """Integer midpoint of the half-open word interval [start_us, end_us)."""
    if end_us <= start_us:
        raise CaptionRejected("invalid_word", "A word range is empty.")
    return start_us + (end_us - start_us) // 2


def word_in_clip(word: CaptionWord, clip_start_us: int, clip_end_us: int) -> bool:
    midpoint = word_midpoint_us(word.start_us, word.end_us)
    return clip_start_us <= midpoint < clip_end_us


def ends_sentence(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return stripped[-1] in _TERMINATORS


def effective_text_fingerprint(words: list[CaptionWord]) -> str:
    payload = [
        {"word_id": word.word_id, "effective_text": word.effective_text}
        for word in sorted(words, key=lambda item: (item.sequence, item.word_id))
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_caption_text(text: str) -> str:
    """One logical line. Whitespace-only text is rejected, not stored as a hidden cue."""
    collapsed = " ".join(text.split())
    if not collapsed:
        raise CaptionRejected("invalid_caption_text", "Caption text cannot be blank.")
    return collapsed


def cue_at_source(cues: list[dict], source_us: int) -> dict | None:
    """The cue whose kept source range contains source_us, using [start_us, end_us)."""
    for cue in cues:
        if int(cue["source_start_us"]) <= source_us < int(cue["source_end_us"]):
            return cue
    return None


def build_cues(clips: list[tuple[int, int]], words: list[CaptionWord]) -> list[BuiltCue]:
    """Cues for words whose midpoint falls inside a kept clip.

    Each cue stays inside one clip. Adjacent clips are not merged.
    """
    assigned: set[str] = set()
    built: list[BuiltCue] = []
    for clip_start, clip_end in clips:
        chosen = [
            word for word in words
            if word.word_id not in assigned and word_in_clip(word, clip_start, clip_end)
        ]
        chosen.sort(key=lambda word: (word.start_us, word.sequence, word.word_id))
        for word in chosen:
            assigned.add(word.word_id)
        for group in _segment(chosen):
            text = " ".join(part for part in (word.effective_text.strip() for word in group) if part)
            if not text:
                continue
            source_start, source_end = _source_bounds(group, clip_start, clip_end)
            sequence_start, sequence_end = _sequence_span(clips, source_start, source_end)
            built.append(BuiltCue(
                order_index=len(built),
                first_word_id=group[0].word_id,
                last_word_id=group[-1].word_id,
                source_start_us=source_start,
                source_end_us=source_end,
                sequence_start_us=sequence_start,
                sequence_end_us=sequence_end,
                generated_text=text,
            ))
    return built


def stale_reasons(
    *,
    sequence_revision: int,
    sequence_revision_at_generation: int,
    transcript_run_id: str | None,
    transcript_analysis_run_id: str,
    effective_fingerprint: str | None,
    stored_fingerprint: str,
) -> list[str]:
    """Why a track no longer matches its sequence and transcript.

    Render profile, visual treatment, shot plan, and camera overrides are not inputs.
    """
    reasons: list[str] = []
    if sequence_revision != sequence_revision_at_generation:
        reasons.append("sequence_revision")
    if transcript_run_id != transcript_analysis_run_id:
        reasons.append("transcript")
    if effective_fingerprint != stored_fingerprint:
        reasons.append("effective_text")
    return reasons


def _segment(words: list[CaptionWord]) -> list[list[CaptionWord]]:
    groups: list[list[CaptionWord]] = []
    current: list[CaptionWord] = []
    for word in words:
        if not current:
            current = [word]
            if ends_sentence(word.effective_text):
                groups.append(current)
                current = []
            continue
        gap = word.start_us - current[-1].end_us
        duration = word.end_us - current[0].start_us
        if gap >= GAP_BREAK_US or len(current) >= MAX_CUE_WORDS or duration > MAX_CUE_DURATION_US:
            groups.append(current)
            current = [word]
        else:
            current.append(word)
        if ends_sentence(word.effective_text):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _source_bounds(words: list[CaptionWord], clip_start: int, clip_end: int) -> tuple[int, int]:
    start = max(words[0].start_us, clip_start)
    end = min(words[-1].end_us, clip_end)
    if end <= start:
        midpoint = word_midpoint_us(words[0].start_us, words[0].end_us)
        start = min(max(midpoint, clip_start), clip_end - 1)
        end = min(clip_end, start + 1)
    return start, end


def _sequence_span(clips: list[tuple[int, int]], source_start: int, source_end: int) -> tuple[int, int]:
    start = source_to_sequence_us(clips, source_start)
    if start is None:
        raise CaptionRejected("invalid_cue", "A caption starts outside the kept sequence.")
    end_at = source_to_sequence_us(clips, source_end)
    if end_at is None:
        previous = source_to_sequence_us(clips, source_end - 1)
        if previous is None:
            raise CaptionRejected("invalid_cue", "A caption ends outside the kept sequence.")
        end_at = previous + 1
    if end_at <= start:
        end_at = start + 1
    return start, end_at
