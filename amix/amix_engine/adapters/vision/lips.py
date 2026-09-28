"""Lip measurement migrated from the CFS overlap proof.

Thresholds and the tight mouth band are unchanged. Crops come from layout
bindings, not from fixed tiles. A missing region or a missing face scores as
no measurable mouth and clears the previous sample, which is the proof's
behavior when landmarks are absent.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from amix.amix_engine.adapters.vision.geometry import ANALYSIS_TILE_H, ANALYSIS_TILE_W

LIP_ON = 4.2


@dataclass(frozen=True)
class FaceSample:
    w: float
    h: float
    landmarks: tuple[tuple[float, float], ...] | None


@dataclass(frozen=True)
class MouthState:
    lip: np.ndarray
    chin: np.ndarray
    upper: np.ndarray
    cy: float


def prepare_tile(frame_bgr: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray | None:
    x, y, width, height = rect
    tile = frame_bgr[y:y + height, x:x + width]
    if tile.size == 0:
        return None
    return cv2.resize(tile, (ANALYSIS_TILE_W, ANALYSIS_TILE_H), interpolation=cv2.INTER_AREA)


def gray_tile(tile_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (3, 3), 0)


def _clip(value: int, limit: int) -> int:
    return max(0, min(limit, value))


def _band(gray: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> np.ndarray | None:
    height, width = gray.shape[:2]
    xa, xb = _clip(int(x0), width), _clip(int(x1), width)
    ya, yb = _clip(int(y0), height), _clip(int(y1), height)
    if xb - xa < 8 or yb - ya < 6:
        return None
    patch = gray[ya:yb, xa:xb]
    return cv2.resize(patch, (32, 16), interpolation=cv2.INTER_AREA)


def lip_parts(gray: np.ndarray, face: FaceSample | None) -> tuple[np.ndarray, np.ndarray, np.ndarray, float] | None:
    if face is None or not face.landmarks or len(face.landmarks) < 5:
        return None
    mouth_r, mouth_l = face.landmarks[3], face.landmarks[4]
    nose = face.landmarks[2]
    cx = (mouth_r[0] + mouth_l[0]) / 2.0
    cy = (mouth_r[1] + mouth_l[1]) / 2.0
    mouth_w = max(12.0, abs(mouth_r[0] - mouth_l[0]))
    lip = _band(gray, cx - mouth_w * 0.40, cy - mouth_w * 0.16, cx + mouth_w * 0.40, cy + mouth_w * 0.20)
    chin = _band(gray, cx - mouth_w * 0.40, cy + mouth_w * 0.55, cx + mouth_w * 0.40, cy + mouth_w * 1.20)
    upper = _band(gray, cx - mouth_w * 0.40, nose[1] - mouth_w * 0.70, cx + mouth_w * 0.40, nose[1] - mouth_w * 0.08)
    if lip is None or upper is None:
        return None
    if chin is None:
        chin = np.zeros_like(lip)
    return lip, chin, upper, cy


def _motion(previous: np.ndarray | None, current: np.ndarray | None) -> float:
    if previous is None or current is None or previous.shape != current.shape:
        return 0.0
    return float(np.mean(cv2.absdiff(previous, current)))


def speech_score(previous: MouthState | None, current: tuple[np.ndarray, np.ndarray, np.ndarray, float]) -> float:
    if previous is None:
        return 0.0
    lip, chin, upper, cy = current
    if abs(cy - previous.cy) > 10.0:
        return 0.0
    lip_motion = _motion(previous.lip, lip)
    chin_motion = _motion(previous.chin, chin)
    upper_motion = _motion(previous.upper, upper)
    if chin_motion > 2.0 and chin_motion > lip_motion * 1.15:
        return 0.0
    if lip_motion < upper_motion + 1.4:
        return 0.0
    return max(0.0, lip_motion - 0.45 * upper_motion)


def score_sample(
    previous: MouthState | None,
    gray: np.ndarray | None,
    face: FaceSample | None,
) -> tuple[float, MouthState | None]:
    """One participant at one sample. No region or no face clears the state."""
    if gray is None:
        return 0.0, None
    parts = lip_parts(gray, face)
    if parts is None:
        return 0.0, None
    lip, chin, upper, cy = parts
    score = speech_score(previous, (lip, chin, upper, cy))
    return score, MouthState(lip, chin, upper, cy)


def largest_face(faces: list[FaceSample]) -> FaceSample | None:
    if not faces:
        return None
    return max(faces, key=lambda face: face.w * face.h)


def frame_rms(audio: np.ndarray, sample_index: int, sample_rate: int, sample_fps: int) -> float:
    start = sample_index * sample_rate // sample_fps
    end = min(len(audio), start + sample_rate // sample_fps)
    chunk = audio[start:end]
    if chunk.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(chunk.astype(np.float64) * chunk.astype(np.float64))))
