"""Canonical AMIX media time: int microseconds, half-open ranges.

Zero is the source container presentation timeline. Nothing in this module
rebases a window to zero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


class TimeError(ValueError):
    """A timestamp or range violated the canonical clock."""


def round_half_away_from_zero(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


def legacy_seconds_to_us(value: str | int | float) -> int:
    """Convert a legacy millisecond-resolution second value to microseconds.

    Preferred input is decimal text. A JSON number that arrived as ``float``
    is converted once: nearest whole millisecond, then ``ms * 1000``.
    A JSON integer is a whole number of seconds.

    ``round(seconds, 3) * 1000`` is not used. It yields milliseconds and a float.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TimeError("empty timestamp")
        milliseconds = _milliseconds(Decimal(text))
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TimeError(f"unsupported timestamp type: {type(value).__name__}")
    elif isinstance(value, int):
        milliseconds = value * 1000
    else:
        if not math.isfinite(value):
            raise TimeError("timestamp is not finite")
        milliseconds = round_half_away_from_zero(value * 1000.0)
    return milliseconds * 1000


def _milliseconds(value: Decimal) -> int:
    quantized = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return int(quantized * 1000)


@dataclass(frozen=True, order=True)
class TimeRange:
    """Half-open interval ``[start_us, end_us)`` on one source timeline."""

    start_us: int
    end_us: int

    def __post_init__(self) -> None:
        if isinstance(self.start_us, bool) or isinstance(self.end_us, bool):
            raise TimeError("range bounds must be int microseconds")
        if not isinstance(self.start_us, int) or not isinstance(self.end_us, int):
            raise TimeError("range bounds must be int microseconds")
        if self.end_us < self.start_us:
            raise TimeError("range end is before start")

    @property
    def duration_us(self) -> int:
        return self.end_us - self.start_us

    def contains(self, t_us: int) -> bool:
        return self.start_us <= t_us < self.end_us

    def intersects(self, other: TimeRange) -> bool:
        return self.start_us < other.end_us and other.start_us < self.end_us

    def overlap_us(self, other: TimeRange) -> int:
        return max(0, min(self.end_us, other.end_us) - max(self.start_us, other.start_us))

    def intersection(self, other: TimeRange) -> TimeRange | None:
        start = max(self.start_us, other.start_us)
        end = min(self.end_us, other.end_us)
        if end <= start:
            return None
        return TimeRange(start, end)
