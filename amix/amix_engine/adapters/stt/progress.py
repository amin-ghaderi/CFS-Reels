"""Transcription progress on the job scale. 10000 is reserved for activation."""
from __future__ import annotations


def transcription_progress_bp(segment_end_us: int, duration_us: int | None, previous: int) -> int:
    """Monotonic basis points from segment progress.

    Without a known duration the value stays where it is. A fabricated
    percentage is not reported. The result is never 10000.
    """
    if isinstance(previous, bool) or not isinstance(previous, int) or previous < 0:
        previous = 0
    if previous > 9999:
        previous = 9999
    if duration_us is None or isinstance(duration_us, bool) or not isinstance(duration_us, int) or duration_us <= 0:
        return previous
    if isinstance(segment_end_us, bool) or not isinstance(segment_end_us, int) or segment_end_us <= 0:
        return previous
    raw = segment_end_us * 9999 // duration_us
    if raw > 9999:
        raw = 9999
    if raw < previous:
        return previous
    return raw
