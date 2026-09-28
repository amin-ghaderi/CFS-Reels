"""One output frame grid for a whole render.

Shot durations are not rounded one by one. Every boundary is an index on the
same origin, so the frame counts telescope.
"""
from __future__ import annotations


def frame_index(time_us: int, origin_us: int, fps_num: int, fps_den: int) -> int:
    """Half-up index of a canonical time on the render's CFR grid.

    ``(time - origin) * fps_num / (1_000_000 * fps_den)``, ties round away
    from zero. The inputs stay integers. There is no binary float.
    """
    if fps_num <= 0 or fps_den <= 0:
        raise ValueError("frame rate must be positive")
    delta = time_us - origin_us
    if delta < 0:
        raise ValueError("time is before the render origin")
    numerator = delta * fps_num
    denominator = 1_000_000 * fps_den
    quotient, remainder = divmod(numerator, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return quotient


def segment_frames(start_index: int, end_index: int) -> int:
    return end_index - start_index
