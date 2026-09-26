from __future__ import annotations

import math

import cv2
import numpy as np

from .fire_realism import fire_behind_realistic
from .segment import protect_mask, subject_centroid


def _to_float(bgr: np.ndarray) -> np.ndarray:
    return bgr.astype(np.float32) / 255.0


def _to_u8(img: np.ndarray) -> np.ndarray:
    return np.clip(img * 255.0, 0, 255).astype(np.uint8)


def _envelope(t: float, duration: float) -> float:
    attack = 0.12
    release = 0.22
    if t < attack:
        return t / attack
    remain = duration - t
    if remain < release:
        return max(0.0, remain / release)
    return 1.0


def _value_noise(h: int, w: int, t: float, seed: int, scale: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    gh = max(4, int(h / scale) + 3)
    gw = max(4, int(w / scale) + 3)
    grid = rng.random((gh, gw)).astype(np.float32)
    oy = (t * 38.0) % scale
    field = cv2.resize(grid, (w, h), interpolation=cv2.INTER_CUBIC)
    shift = int(oy) % max(1, h)
    return np.roll(field, -shift, axis=0)


def _fbm(h: int, w: int, t: float, seed: int) -> np.ndarray:
    n = np.zeros((h, w), dtype=np.float32)
    amp = 0.55
    total = 0.0
    for i, scale in enumerate((28.0, 14.0, 7.0, 3.5)):
        n += amp * _value_noise(h, w, t * (1.0 + 0.35 * i), seed + i * 17, scale)
        total += amp
        amp *= 0.52
    return n / max(total, 1e-6)


def _fire_lut() -> np.ndarray:
    x = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    b = np.clip(4.0 * (x - 0.72), 0.0, 1.0)
    g = np.clip(1.15 * np.power(np.clip(x - 0.12, 0.0, 1.0), 0.85), 0.0, 1.0)
    r = np.clip(0.15 + 1.2 * np.power(x, 0.55), 0.0, 1.0)
    # BGR
    return np.stack([b, g * 0.55 + 0.45 * x, r], axis=1)


_FIRE_LUT = _fire_lut()


def _scene_luma(frame: np.ndarray, matte: np.ndarray) -> float:
    bg = frame[matte < 0.25]
    if bg.size < 16:
        return 0.45
    y = 0.114 * bg[:, 0] + 0.587 * bg[:, 1] + 0.299 * bg[:, 2]
    return float(np.clip(y.mean() / 255.0, 0.12, 0.85))


def _grain(frame: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(frame, (0, 0), 1.1)
    return (frame.astype(np.float32) - blur.astype(np.float32)) / 255.0


def _plume_mask(
    h: int,
    w: int,
    cx: float,
    cy: float,
    intensity: float,
    *,
    width_frac: float = 0.22,
    height_frac: float = 0.62,
) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base_y = min(h * 0.94, cy)
    dx = (xx - cx) / (w * (width_frac + 0.08 * intensity))
    rise = np.clip((base_y - yy) / (h * 0.82), 0.0, 1.25)
    width = 1.0 + 0.95 * rise
    rad = (dx / np.maximum(width, 0.12)) ** 2 + ((yy - base_y) / (h * height_frac)) ** 2
    mask = np.exp(-rad * (2.1 - 0.5 * intensity))
    mask *= np.clip(1.1 - 0.28 * rise, 0.22, 1.0)
    edge_x = np.minimum(xx / (0.07 * w), (w - 1 - xx) / (0.07 * w))
    edge_y = np.minimum(yy / (0.05 * h), (h - 1 - yy) / (0.07 * h))
    mask *= np.clip(np.minimum(edge_x, edge_y), 0.0, 1.0)
    return mask


def _visible_behind_origin(matte: np.ndarray, cx: float, cy: float) -> tuple[float, float]:
    """Put the plume in visible background next to the subject, not under the body."""
    h, w = matte.shape[:2]
    bg = matte < 0.28
    left = bg[:, : max(1, int(w * 0.55))].mean()
    right = bg[:, int(w * 0.45) :].mean()
    if left >= right:
        fx = min(cx - 0.16 * w, w * 0.40)
    else:
        fx = max(cx + 0.16 * w, w * 0.60)
    fy = min(h * 0.88, cy + 0.18 * h)
    return float(np.clip(fx, w * 0.18, w * 0.82)), float(np.clip(fy, h * 0.45, h * 0.92))


def fire_behind(
    frame: np.ndarray,
    matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    return fire_behind_realistic(frame, matte, t, duration, intensity)


def smoke_hit(
    frame: np.ndarray,
    matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    h, w = frame.shape[:2]
    env = _envelope(t, duration) * intensity
    if env < 0.01:
        return frame
    src = _to_float(frame)
    cx, cy = subject_centroid(matte)
    noise = _fbm(h, w, t * 0.7, seed=29)
    plume = _plume_mask(h, w, cx, cy + h * 0.04, intensity * 0.9)
    field = cv2.GaussianBlur(np.clip(noise * plume, 0.0, 1.0), (0, 0), 3.2)
    smoke = np.dstack([
        0.22 + 0.18 * field,
        0.24 + 0.16 * field,
        0.26 + 0.14 * field,
    ])
    luma = _scene_luma(frame, matte)
    smoke *= (0.5 + 0.8 * luma)
    a = (field * env * 0.85)[..., None]
    behind = src * (1.0 - a) + smoke * a
    person = matte[..., None]
    out = behind * (1.0 - person) + src * person
    protect = protect_mask(matte)[..., None]
    out = out * (1.0 - protect) + src * protect
    return _to_u8(out)


def light_burst(
    frame: np.ndarray,
    matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    h, w = frame.shape[:2]
    flash = math.exp(-((t - 0.18) ** 2) / (2 * 0.07 ** 2)) * intensity
    if flash < 0.02:
        return frame
    src = _to_float(frame)
    cx, cy = subject_centroid(matte)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rad = np.sqrt(((xx - cx) / (0.42 * w)) ** 2 + ((yy - cy) / (0.55 * h)) ** 2)
    glow = np.clip(1.0 - rad, 0.0, 1.0) ** 1.6
    glow = cv2.GaussianBlur(glow, (0, 0), 8.0)
    color = np.array([0.75, 0.88, 1.0], dtype=np.float32)
    a = (glow * flash * 0.75)[..., None]
    behind = np.clip(src + color * a, 0.0, 1.0)
    person = matte[..., None]
    out = behind * (1.0 - person) + src * person
    edge = np.clip(matte - protect_mask(matte, 9), 0, 1)
    out = out + color * (edge * flash * 0.22)[..., None]
    protect = protect_mask(matte)[..., None]
    out = out * (1.0 - protect) + src * protect
    return _to_u8(out)


def _crack_map(h: int, w: int, seed: int = 41) -> np.ndarray:
    rng = np.random.default_rng(seed)
    canvas = np.zeros((h, w), dtype=np.uint8)
    cx, cy = w * 0.52, h * 0.42
    for _ in range(9):
        angle = float(rng.uniform(-math.pi, math.pi))
        x, y = cx, cy
        length = int(rng.uniform(0.28, 0.62) * max(h, w))
        pts = []
        for _step in range(length):
            x += math.cos(angle)
            y += math.sin(angle)
            angle += float(rng.normal(0, 0.08))
            if 0 <= x < w and 0 <= y < h:
                pts.append((int(x), int(y)))
            else:
                break
        if len(pts) > 2:
            cv2.polylines(canvas, [np.array(pts, np.int32)], False, 255, 1, cv2.LINE_AA)
            if rng.random() > 0.4:
                mid = pts[len(pts) // 2]
                bangle = angle + float(rng.choice([-1, 1])) * 0.9
                bx, by = float(mid[0]), float(mid[1])
                branch = []
                for _step in range(int(length * 0.35)):
                    bx += math.cos(bangle)
                    by += math.sin(bangle)
                    bangle += float(rng.normal(0, 0.1))
                    if 0 <= bx < w and 0 <= by < h:
                        branch.append((int(bx), int(by)))
                if len(branch) > 2:
                    cv2.polylines(canvas, [np.array(branch, np.int32)], False, 200, 1, cv2.LINE_AA)
    return canvas.astype(np.float32) / 255.0


def glass_crack(
    frame: np.ndarray,
    matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    h, w = frame.shape[:2]
    reveal = min(1.0, t / 0.28) * intensity
    if reveal < 0.02:
        return frame
    src = _to_float(frame)
    cracks = _crack_map(h, w)
    # grow from center
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt(((xx - w * 0.52) / w) ** 2 + ((yy - h * 0.42) / h) ** 2)
    grow = np.clip((reveal * 1.15 - dist) / 0.12, 0.0, 1.0)
    lines = cv2.GaussianBlur(cracks * grow, (0, 0), 0.6)
    # keep cracks mostly off the protected face/body
    bg = 1.0 - matte
    lines = lines * (0.25 + 0.75 * bg)
    dark = lines[..., None] * np.array([0.15, 0.16, 0.18])
    out = src * (1.0 - 0.72 * lines[..., None]) + dark
    # slight refraction along cracks
    mag = lines * 2.4
    map_x = np.clip(xx + (cv2.Sobel(lines, cv2.CV_32F, 1, 0, ksize=3)) * mag, 0, w - 1)
    map_y = np.clip(yy + (cv2.Sobel(lines, cv2.CV_32F, 0, 1, ksize=3)) * mag, 0, h - 1)
    warped = cv2.remap(src, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    mix = np.clip(lines * 0.65, 0, 1)[..., None]
    out = out * (1.0 - mix) + warped * mix
    protect = protect_mask(matte, 9)[..., None]
    out = out * (1.0 - protect) + src * protect
    return _to_u8(out)


def electric_spark(
    frame: np.ndarray,
    matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    h, w = frame.shape[:2]
    pulse = 0.5 + 0.5 * math.sin(t * 42.0)
    burst = math.exp(-(((t % 0.45) - 0.06) ** 2) / (2 * 0.018 ** 2))
    env = burst * pulse * intensity
    if env < 0.04:
        return frame
    src = _to_float(frame)
    cx, cy = subject_centroid(matte)
    rng = np.random.default_rng(int(t * 40) + 7)
    canvas = np.zeros((h, w), dtype=np.float32)
    origin = (int(cx + w * 0.18), int(cy - h * 0.05))
    for _ in range(4):
        x, y = float(origin[0]), float(origin[1])
        angle = float(rng.uniform(-0.9, 0.9))
        pts = []
        for _step in range(int(0.22 * max(h, w))):
            x += math.cos(angle) * 2.2
            y += math.sin(angle) * 2.2
            angle += float(rng.normal(0, 0.35))
            if 0 <= x < w and 0 <= y < h:
                pts.append((int(x), int(y)))
        if len(pts) > 2:
            cv2.polylines(canvas, [np.array(pts, np.int32)], False, 1.0, 1, cv2.LINE_AA)
    glow = cv2.GaussianBlur(canvas, (0, 0), 1.4)
    color = np.array([1.0, 0.92, 0.55], dtype=np.float32)
    a = (glow * env * 0.95) * (1.0 - protect_mask(matte, 6))
    out = np.clip(src + color * a[..., None], 0.0, 1.0)
    protect = protect_mask(matte)[..., None]
    out = out * (1.0 - protect) + src * protect
    return _to_u8(out)


def impact_shake(
    frame: np.ndarray,
    _matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    h, w = frame.shape[:2]
    hit = math.exp(-((t - 0.08) ** 2) / (2 * 0.05 ** 2)) + 0.25 * math.exp(-t * 3.5)
    amp = 10.0 * intensity * hit
    dx = amp * math.sin(t * 58.0)
    dy = amp * 0.55 * math.cos(t * 71.0)
    matrix = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
    shaken = cv2.warpAffine(frame, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return shaken
