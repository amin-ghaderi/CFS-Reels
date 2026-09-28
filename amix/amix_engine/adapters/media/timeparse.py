"""Convert ffprobe decimal-second text into integer microseconds.

The text is parsed with Decimal. Binary floats are not used.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_MICRO = Decimal(1_000_000)


def seconds_text_to_us(text: str) -> int:
    """Round half away from zero to the nearest microsecond."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise ValueError("time text is not a decimal") from exc
    if not value.is_finite():
        raise ValueError("time text is not finite")
    scaled = (value * _MICRO).to_integral_value(rounding=ROUND_HALF_UP)
    return int(scaled)
