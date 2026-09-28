"""Convert one external speech timestamp into canonical source microseconds.

faster-whisper reports seconds relative to the decoded media beginning.
Those values are floats. This module is the only place that reads them.
Later code adds the source container start as an integer and keeps integers.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math

from amix.amix_engine.time.clock import TimeError

_MICRO = Decimal(1_000_000)
CANONICAL_ORIGIN_RULE = "source_container_start_us"


def external_seconds_to_us(value: str | int | float | Decimal) -> int:
    """Nearest integer microsecond. Each external second value is converted once."""
    if isinstance(value, bool) or value is None:
        raise TimeError("speech time is missing")
    if isinstance(value, Decimal):
        decimal = value
    elif isinstance(value, int):
        decimal = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise TimeError("speech time is not finite")
        decimal = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise TimeError("speech time is missing")
        decimal = Decimal(text)
    else:
        raise TimeError("speech time is not a number")
    if not decimal.is_finite() or decimal < 0:
        raise TimeError("speech time is negative")
    microseconds = (decimal * _MICRO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(microseconds)


def canonical_source_us(relative_us: int, source_container_start_us: int | None) -> int:
    """Place a relative word on the source media timeline.

    A missing container start is zero. The start is added. It is not subtracted,
    and a playback or proxy origin is not an input.
    """
    if isinstance(relative_us, bool) or not isinstance(relative_us, int) or relative_us < 0:
        raise TimeError("relative speech time must be a non-negative int")
    if source_container_start_us is None:
        origin = 0
    elif isinstance(source_container_start_us, bool) or not isinstance(source_container_start_us, int):
        raise TimeError("source container start must be int microseconds")
    elif source_container_start_us < 0:
        raise TimeError("source container start is negative")
    else:
        origin = source_container_start_us
    return origin + relative_us
