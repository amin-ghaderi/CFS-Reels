"""Deterministic framing inside a layout region or the whole source frame.

CENTER_FILL crops the largest exact-aspect rectangle and then scales.
FIT keeps the whole picture and pads. Neither path stretches.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from amix.amix_engine.domain.types import LayoutBinding, ParticipantId


class FramingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Crop:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class FittedPicture:
    width: int
    height: int
    pad_x: int
    pad_y: int


def center_fill(x: int, y: int, width: int, height: int, out_w: int, out_h: int) -> Crop:
    """Largest even crop inside the region with exactly the output aspect."""
    if min(width, height, out_w, out_h) <= 0:
        raise FramingError("region_too_small", "The participant region cannot fill this output.")
    divisor = math.gcd(out_w, out_h)
    unit_w = out_w // divisor
    unit_h = out_h // divisor
    scale = min(width // unit_w, height // unit_h)
    while scale > 0 and ((scale * unit_w) % 2 or (scale * unit_h) % 2):
        scale -= 1
    if scale < 1:
        raise FramingError("region_too_small", "The participant region cannot fill this output.")
    crop_w = scale * unit_w
    crop_h = scale * unit_h
    crop_x = _even_origin(x + (width - crop_w) // 2, crop_w, x, width)
    crop_y = _even_origin(y + (height - crop_h) // 2, crop_h, y, height)
    return Crop(crop_x, crop_y, crop_w, crop_h)


def fit_picture(src_w: int, src_h: int, out_w: int, out_h: int) -> FittedPicture:
    """Whole source picture inside the canvas. Leftover pixels are padding."""
    if min(src_w, src_h, out_w, out_h) <= 0:
        raise FramingError("region_too_small", "The source frame has no picture size.")
    if out_w * src_h <= out_h * src_w:
        fitted_w = out_w - (out_w % 2)
        fitted_h = (fitted_w * src_h) // src_w
    else:
        fitted_h = out_h - (out_h % 2)
        fitted_w = (fitted_h * src_w) // src_h
    fitted_w -= fitted_w % 2
    fitted_h -= fitted_h % 2
    if fitted_w < 2 or fitted_h < 2:
        raise FramingError("region_too_small", "The fitted picture is empty.")
    return FittedPicture(fitted_w, fitted_h, (out_w - fitted_w) // 2, (out_h - fitted_h) // 2)


def covering_segments(
    bindings: list[LayoutBinding],
    participant_id: ParticipantId,
    start_us: int,
    end_us: int,
) -> list[tuple[int, int, LayoutBinding]] | None:
    """Split a shot where the participant's region changes.

    Adjacent bindings are kept. A gap or two bindings on the same instant
    rejects the range instead of guessing a rectangle.
    """
    relevant = [
        binding for binding in bindings
        if binding.participant_id == participant_id
        and binding.span.end_us > start_us
        and binding.span.start_us < end_us
    ]
    cuts = {start_us, end_us}
    for binding in relevant:
        if start_us < binding.span.start_us < end_us:
            cuts.add(binding.span.start_us)
        if start_us < binding.span.end_us < end_us:
            cuts.add(binding.span.end_us)
    ordered = sorted(cuts)
    pieces: list[tuple[int, int, LayoutBinding]] = []
    for left, right in zip(ordered, ordered[1:]):
        matches = [
            binding for binding in relevant
            if binding.span.start_us <= left and right <= binding.span.end_us
        ]
        if len(matches) != 1:
            return None
        pieces.append((left, right, matches[0]))
    return pieces


def _even_origin(origin: int, size: int, region_origin: int, region_size: int) -> int:
    limit = region_origin + region_size
    if origin % 2 == 0 and origin >= region_origin and origin + size <= limit:
        return origin
    for candidate in (origin - (origin % 2), origin - (origin % 2) + 2):
        if candidate >= region_origin and candidate + size <= limit:
            return candidate
    return origin
