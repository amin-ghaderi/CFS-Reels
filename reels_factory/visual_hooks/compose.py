from __future__ import annotations

import numpy as np

from .config import VisualHookConfig
from .presets import PRESETS, apply_preset
from .segment import SubjectSegmenter, mattes_for_frames, protect_mask


def apply_hook_frames(
    frames: list[np.ndarray],
    config: VisualHookConfig,
    *,
    fps: float = 30.0,
    segmenter: SubjectSegmenter | None = None,
    progress=None,
) -> tuple[list[np.ndarray], list[np.ndarray], str]:
    if not frames:
        return [], [], "none"
    spec = PRESETS[config.preset]
    method = "none"
    if spec["needs_matte"]:
        if config.preset == "fire_behind_subject":
            if segmenter is None or segmenter.max_side < 560:
                segmenter = SubjectSegmenter(max_side=560)
            method = segmenter.method
            mattes = mattes_for_frames(
                frames,
                segmenter,
                key_stride=1,
                smooth=0.42,
                refine=True,
                progress=progress,
            )
        else:
            segmenter = segmenter or SubjectSegmenter()
            method = segmenter.method
            mattes = mattes_for_frames(frames, segmenter, progress=progress)
    else:
        h, w = frames[0].shape[:2]
        mattes = [np.zeros((h, w), dtype=np.float32) for _ in frames]
    hooked: list[np.ndarray] = []
    for i, (frame, matte) in enumerate(zip(frames, mattes)):
        t = i / float(fps)
        hooked.append(
            apply_preset(config.preset, frame, matte, t, config.duration, config.intensity)
        )
    return hooked, mattes, method


def foreground_unchanged(original: np.ndarray, hooked: np.ndarray, matte: np.ndarray, *, atol: int = 2) -> float:
    """Fraction of protected interior pixels that match the source frame."""
    protect = protect_mask(matte) > 0.85
    if int(protect.sum()) < 16:
        return 1.0
    delta = np.max(np.abs(original.astype(np.int16) - hooked.astype(np.int16)), axis=2)
    ok = delta[protect] <= atol
    return float(ok.mean())
