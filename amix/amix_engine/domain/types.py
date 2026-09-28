"""Value objects used by the Phase 2 deterministic core.

Identities are participant ids. Legacy tile letters stay in the fixture adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from amix.amix_engine.time.clock import TimeRange


@dataclass(frozen=True, order=True)
class ParticipantId:
    value: str

    def __post_init__(self) -> None:
        if not self.value or not isinstance(self.value, str):
            raise ValueError("participant id must be a non-empty string")


@dataclass(frozen=True)
class Word:
    word_id: str
    start_us: int
    end_us: int
    text: str


@dataclass(frozen=True)
class DiarizationSegment:
    start_us: int
    end_us: int
    cluster_id: str


@dataclass(frozen=True)
class SpeakerAssignment:
    word_id: str
    participant_id: ParticipantId | None


@dataclass(frozen=True)
class Turn:
    turn_id: str
    participant_id: ParticipantId | None
    start_us: int
    end_us: int
    word_ids: tuple[str, ...]

    @property
    def word_count(self) -> int:
        return len(self.word_ids)


@dataclass(frozen=True)
class LayoutBinding:
    """One participant occupying one source rectangle for a time span."""

    participant_id: ParticipantId
    x: int
    y: int
    w: int
    h: int
    span: TimeRange

    def covers(self, start_us: int, end_us: int) -> bool:
        return self.span.start_us <= start_us and end_us <= self.span.end_us


@dataclass(frozen=True)
class LipActivitySeries:
    """Precomputed per-frame lip scores. No pixels.

    ``scores[frame][column]`` follows ``participant_ids``.
    Frame ``i`` is at ``origin_us + i * sample_period_us`` on the source timeline.
    """

    origin_us: int
    sample_period_us: int
    participant_ids: tuple[ParticipantId, ...]
    scores: tuple[tuple[float, ...], ...]
    audio_rms: tuple[float, ...]

    def __post_init__(self) -> None:
        width = len(self.participant_ids)
        if self.sample_period_us <= 0:
            raise ValueError("sample period must be positive")
        if len(self.audio_rms) != len(self.scores):
            raise ValueError("audio and score rows differ in length")
        for row in self.scores:
            if len(row) != width:
                raise ValueError("a score row does not match the participant columns")


@dataclass(frozen=True)
class OverlapRegion:
    start_us: int
    end_us: int
    participant_ids: tuple[ParticipantId, ...]
    confidence: float


@dataclass(frozen=True)
class ProtectedRegion:
    span: TimeRange


class Presentation(Enum):
    FULL = "full"
    UNTOUCHED_WIDE = "untouched_wide"
    PROTECTED_MASTER = "protected_master"


@dataclass(frozen=True)
class Shot:
    start_us: int
    end_us: int
    presentation: Presentation
    participant_id: ParticipantId | None
    floor_participant_id: ParticipantId | None
    reason: str

    def __post_init__(self) -> None:
        if self.presentation is Presentation.FULL and self.participant_id is None:
            raise ValueError("a full shot needs a participant")
        if self.presentation is not Presentation.FULL and self.participant_id is not None:
            raise ValueError("only a full shot frames a participant")
        if self.end_us <= self.start_us:
            raise ValueError("shot range is empty")


@dataclass(frozen=True)
class ShotPlan:
    span: TimeRange
    shots: tuple[Shot, ...]
