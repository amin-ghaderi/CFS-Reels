"""Neutral lip-activity samples. This module does not build overlap regions."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from amix.amix_engine.adapters.vision.geometry import binding_at, clip_rect
from amix.amix_engine.adapters.vision.lips import (
    FaceSample,
    largest_face,
    gray_tile,
    prepare_tile,
    score_sample,
    frame_rms,
)
from amix.amix_engine.domain.types import LayoutBinding, LipActivitySeries, ParticipantId

AUDIO_RATE = 16000
SAMPLE_FPS = 8


class FrameGeometryError(ValueError):
    """Decoded frame size is not the probed display size."""


class FaceDetector:
    def detect(self, frame: np.ndarray) -> list[FaceSample]:
        raise NotImplementedError


def measure_frames(
    frames: Iterable[np.ndarray],
    audio: np.ndarray,
    bindings: list[LayoutBinding],
    participants: tuple[ParticipantId, ...],
    *,
    origin_us: int,
    sample_period_us: int,
    detector: FaceDetector,
    width: int,
    height: int,
) -> LipActivitySeries:
    """Score each frame and drop it. Missing layout is no measurable mouth."""
    states: dict[ParticipantId, object] = {person: None for person in participants}
    rects: dict[ParticipantId, tuple[int, int, int, int] | None] = {person: None for person in participants}
    scores: list[tuple[float, ...]] = []
    rms: list[float] = []
    for index, frame in enumerate(frames):
        if frame.ndim != 3 or frame.shape[0] != height or frame.shape[1] != width or frame.shape[2] != 3:
            raise FrameGeometryError("decoded frame does not match the display size")
        time_us = origin_us + index * sample_period_us
        row: list[float] = []
        for person in participants:
            binding = binding_at(bindings, person, time_us)
            rect = None if binding is None else clip_rect(width, height, binding.x, binding.y, binding.w, binding.h)
            if rect != rects[person]:
                states[person] = None
                rects[person] = rect
            if rect is None:
                states[person] = None
                row.append(0.0)
                continue
            tile = prepare_tile(frame, rect)
            gray = None if tile is None else gray_tile(tile)
            face = None if tile is None else largest_face(detector.detect(tile))
            score, states[person] = score_sample(states[person], gray, face)
            row.append(float(score))
        scores.append(tuple(row))
        rms.append(frame_rms(audio, index, AUDIO_RATE, SAMPLE_FPS))
    return LipActivitySeries(
        origin_us,
        sample_period_us,
        participants,
        tuple(scores),
        tuple(rms),
    )
