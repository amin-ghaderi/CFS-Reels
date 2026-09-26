"""Final visual verification gate for the offline 16:9 multicam director.

The resolved speaker timeline is the prior. Before a floor change is
locked into the shot plan, this gate measures lip and jaw motion on the
three fixed tiles around the boundary. A clear contradiction may override
the resolved label for the camera plan only. It never rewrites the
resolved speaker file.

Evidence order:
1. Clear synchronized mouth and jaw activity
2. Conversational turn structure
3. Resolved speaker timeline
4. Transcript continuity
5. Neighboring labels

Hands, nods, posture, and smiles are not enough to override.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .faces import CachedYunet, ensure_yunet_model
from .speaker_resolver_v2 import SPEAKERS, TILES, _speech_delta, crop_tile, _patches

# A lead has to be obvious. Close mouth scores keep the resolved label.
STRONG_MOUTH = 2.5
STRONG_RATIO = 1.7


def measure_mouth_window(
    cap: cv2.VideoCapture,
    detector: CachedYunet,
    start: float,
    end: float,
    *,
    samples: int = 5,
) -> dict[str, float]:
    """Median mouth-minus-upper-face motion for each tile inside [start, end]."""
    span = max(0.2, end - start)
    times = [start + span * (i + 1) / (samples + 1) for i in range(samples)]
    excess = {key: [] for key in SPEAKERS}
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t * 1000.0))
        ok, frame_a = cap.read()
        if not ok or frame_a is None:
            continue
        for _ in range(2):
            if not cap.grab():
                break
        ok, frame_b = cap.retrieve()
        if not ok or frame_b is None:
            continue
        for key, box in TILES.items():
            delta = _speech_delta(
                _patches(crop_tile(frame_a, box), detector),
                _patches(crop_tile(frame_b, box), detector),
            )
            excess[key].append(0.0 if delta is None else float(delta[0] - delta[1]))
    return {
        key: round(float(np.median(vals)), 3) if vals else 0.0
        for key, vals in excess.items()
    }


def verify_identity(resolved: str, mouth: dict[str, float]) -> dict:
    """Accept the resolved speaker unless another tile is clearly speaking."""
    ranked = sorted(SPEAKERS, key=lambda key: float(mouth.get(key) or 0.0), reverse=True)
    best, second = ranked[0], ranked[1]
    best_v = float(mouth.get(best) or 0.0)
    second_v = float(mouth.get(second) or 0.0)
    resolved_v = float(mouth.get(resolved) or 0.0)
    ratio = best_v / second_v if second_v > 0.35 else (8.0 if best_v >= STRONG_MOUTH else 1.0)
    ahead_of_resolved = best != resolved and best_v >= STRONG_MOUTH and (
        resolved_v <= 1.0 or best_v >= max(resolved_v * STRONG_RATIO, resolved_v + 1.5)
    )
    # A second tile that is almost as active is not a smile or a nod.
    # It blocks a single-person override and leaves the choice to the edit.
    pair_is_ambiguous = second_v >= 2.0 and ratio < 1.45 and second != resolved
    if ahead_of_resolved and not pair_is_ambiguous:
        return {
            "verified_active_speaker": best,
            "visual_override": True,
            "reason": (
                f"Clear mouth and jaw activity is on {best} ({best_v:.2f}) "
                f"while {resolved} is {resolved_v:.2f}. The resolved label is not used for the camera."
            ),
        }
    if ahead_of_resolved and pair_is_ambiguous:
        return {
            "verified_active_speaker": best,
            "visual_override": True,
            "ambiguous": True,
            "reason": (
                f"{resolved} is not the speaking mouth ({resolved_v:.2f}). "
                f"{best} leads at {best_v:.2f}, with {second} also at {second_v:.2f}. "
                "The resolved label is not shown as the single speaker."
            ),
        }
    return {
        "verified_active_speaker": resolved,
        "visual_override": False,
        "reason": (
            f"Resolved {resolved} stands. Mouth A={mouth.get('speaker_a', 0):.2f} "
            f"B={mouth.get('speaker_b', 0):.2f} C={mouth.get('speaker_c', 0):.2f}."
        ),
    }


def open_verifier(video: Path) -> tuple[cv2.VideoCapture, CachedYunet]:
    model = ensure_yunet_model()
    if model is None:
        raise RuntimeError("YuNet face model is required for visual verification")
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {video}")
    return cap, CachedYunet(model, score_threshold=0.5)


def verify_boundary(
    cap: cv2.VideoCapture,
    detector: CachedYunet,
    boundary: float,
    resolved: str,
    *,
    before: float = 1.0,
    after: float = 1.5,
) -> dict:
    """Identity is decided on the 1.5s after the boundary.

    The second before is recorded so the handoff is visible, but the
    outgoing speaker must not veto someone who starts speaking after the cut.
    """
    pre = measure_mouth_window(cap, detector, boundary - before, boundary)
    post = measure_mouth_window(cap, detector, boundary, boundary + after)
    verdict = verify_identity(resolved, post)
    verdict["mouth_activity"] = post
    verdict["mouth_before"] = pre
    verdict["resolved_speaker"] = resolved
    verdict["boundary"] = round(boundary, 3)
    return verdict
