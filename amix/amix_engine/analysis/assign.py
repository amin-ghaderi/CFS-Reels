"""Word-to-participant assignment.

Behavior migrated from:
legacy/reels_factory/cfs_audio_diarize_poc.py::assign_word
"""
from __future__ import annotations

from amix.amix_engine.domain.types import (
    DiarizationSegment,
    ParticipantId,
    SpeakerAssignment,
    Word,
)

# Legacy: best overlap must cover this fraction of the word, and the
# runner-up must stay under this fraction of the winner.
MAJORITY_FRACTION = 0.55
TIE_RATIO = 0.75
MIN_WORD_SECONDS = 0.02


def _seconds(us: int) -> float:
    """Millisecond grid as a float second, matching legacy ``round(t, 3)`` values."""
    return (us // 1000) / 1000.0


def assign_word(
    word: Word,
    segments: list[DiarizationSegment],
    cluster_map: dict[str, ParticipantId | None],
) -> SpeakerAssignment:
    start = _seconds(word.start_us)
    end = _seconds(word.end_us)
    duration = max(MIN_WORD_SECONDS, end - start)
    totals: dict[ParticipantId | None, float] = {}
    for segment in segments:
        overlap = min(end, _seconds(segment.end_us)) - max(start, _seconds(segment.start_us))
        if overlap <= 0:
            continue
        who = cluster_map.get(segment.cluster_id)
        totals[who] = totals.get(who, 0.0) + overlap
    if not totals:
        return SpeakerAssignment(word.word_id, None)
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    best_who, best = ranked[0]
    if best_who is None or best < duration * MAJORITY_FRACTION:
        return SpeakerAssignment(word.word_id, None)
    if len(ranked) > 1 and ranked[1][1] >= best * TIE_RATIO:
        return SpeakerAssignment(word.word_id, None)
    return SpeakerAssignment(word.word_id, best_who)


def assign_words(
    words: list[Word],
    segments: list[DiarizationSegment],
    cluster_map: dict[str, ParticipantId | None],
) -> list[SpeakerAssignment]:
    return [assign_word(word, segments, cluster_map) for word in words]
