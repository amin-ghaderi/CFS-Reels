from __future__ import annotations

import cv2
import numpy as np

from .segment import protect_mask, refine_matte_for_composite, subject_centroid


def _to_float(bgr: np.ndarray) -> np.ndarray:
    return bgr.astype(np.float32) / 255.0


def _to_u8(img: np.ndarray) -> np.ndarray:
    return np.clip(img * 255.0 + 1e-5, 0, 255).astype(np.uint8)


def _fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _hash3(ix: np.ndarray, iy: np.ndarray, iz: np.ndarray, seed: float) -> np.ndarray:
    n = np.sin((ix + seed) * 127.1 + iy * 311.7 + iz * 74.7 + seed * 19.19) * 43758.5453123
    return (n - np.floor(n)).astype(np.float32)


def noise3(x: np.ndarray, y: np.ndarray, z: np.ndarray, seed: float = 0.0) -> np.ndarray:
    """Aperiodic value noise. No wrap/roll, so 1.8s clips do not loop."""
    x0 = np.floor(x)
    y0 = np.floor(y)
    z0 = np.floor(z)
    xf = x - x0
    yf = y - y0
    zf = z - z0
    u = _fade(xf)
    v = _fade(yf)
    w = _fade(zf)
    n000 = _hash3(x0, y0, z0, seed)
    n100 = _hash3(x0 + 1, y0, z0, seed)
    n010 = _hash3(x0, y0 + 1, z0, seed)
    n110 = _hash3(x0 + 1, y0 + 1, z0, seed)
    n001 = _hash3(x0, y0, z0 + 1, seed)
    n101 = _hash3(x0 + 1, y0, z0 + 1, seed)
    n011 = _hash3(x0, y0 + 1, z0 + 1, seed)
    n111 = _hash3(x0 + 1, y0 + 1, z0 + 1, seed)
    x00 = n000 * (1 - u) + n100 * u
    x10 = n010 * (1 - u) + n110 * u
    x01 = n001 * (1 - u) + n101 * u
    x11 = n011 * (1 - u) + n111 * u
    y0i = x00 * (1 - v) + x10 * v
    y1i = x01 * (1 - v) + x11 * v
    return y0i * (1 - w) + y1i * w


def fbm3(x: np.ndarray, y: np.ndarray, z: np.ndarray, *, octaves: int = 4, seed: float = 3.0) -> np.ndarray:
    amp = 0.52
    total = 0.0
    acc = np.zeros_like(x, dtype=np.float32)
    fx, fy, fz = x, y, z
    for i in range(octaves):
        acc += amp * noise3(fx, fy, fz, seed + i * 17.3)
        total += amp
        amp *= 0.5
        fx = fx * 2.03 + 11.0
        fy = fy * 2.03 - 7.0
        fz = fz * 1.37
    return acc / max(total, 1e-6)


def _envelope(t: float, duration: float) -> float:
    attack = 0.22
    release = 0.28
    if t < attack:
        return 0.5 * (1.0 - np.cos(np.pi * t / attack))
    remain = duration - t
    if remain < release:
        return max(0.0, 0.5 * (1.0 - np.cos(np.pi * max(remain, 0.0) / release)))
    return 1.0


def _flicker(t: float, energy: float) -> float:
    wobble = 0.62 + 0.22 * noise3(np.array(t * 11.0), np.array(0.4), np.array(t * 3.1), 91.0)
    return float(np.clip(0.55 + 0.55 * energy + 0.18 * wobble, 0.35, 1.15))


def _source_grain(frame: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(frame, (0, 0), 0.85)
    return (frame.astype(np.float32) - blur.astype(np.float32)) / 255.0


def _screen(base: np.ndarray, add: np.ndarray) -> np.ndarray:
    return 1.0 - (1.0 - np.clip(base, 0, 1)) * (1.0 - np.clip(add, 0, 1))


def _fire_origin(matte: np.ndarray) -> tuple[float, float, float, float]:
    h, w = matte.shape[:2]
    cx, cy = subject_centroid(matte)
    bg = matte < 0.28
    left = float(bg[:, : max(1, int(w * 0.55))].mean())
    right = float(bg[:, int(w * 0.45) :].mean())
    if left >= right:
        fx = min(cx - 0.18 * w, w * 0.38)
    else:
        fx = max(cx + 0.18 * w, w * 0.62)
    fy = min(h * 0.90, cy + 0.16 * h)
    return (
        float(np.clip(fx, w * 0.16, w * 0.84)),
        float(np.clip(fy, h * 0.48, h * 0.93)),
        cx,
        cy,
    )


def _face_gate(matte: np.ndarray) -> np.ndarray:
    h, w = matte.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    gate = np.ones((h, w), dtype=np.float32)
    ys, xs = np.where(matte > 0.45)
    if xs.size:
        y_top = float(ys.min())
        y_span = max(8.0, float(ys.max() - ys.min()))
        face_y = y_top + 0.34 * y_span
        gate = np.clip((yy - face_y) / (0.10 * h), 0.0, 1.0)
        cx = float(xs.mean())
        rad = ((xx - cx) / (0.16 * w)) ** 2 + ((yy - (y_top + 0.18 * y_span)) / (0.20 * h)) ** 2
        gate = gate * np.clip(rad, 0.0, 1.0)
    return gate


def _plume_field(h: int, w: int, t: float, fx: float, fy: float, layer: str) -> np.ndarray:
    """Photoreal density: warped tongues + holes. Unique in time (no loop)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if layer == "near":
        rise, scale, warp, hole, seed = 1.15, 0.028, 18.0, 0.48, 4.0
        width, height = 0.17 * w, 0.58 * h
    elif layer == "far":
        rise, scale, warp, hole, seed = 0.62, 0.018, 22.0, 0.40, 21.0
        width, height = 0.22 * w, 0.72 * h
        fy = fy - 0.06 * h
    else:
        rise, scale, warp, hole, seed = 0.38, 0.012, 28.0, 0.32, 44.0
        width, height = 0.26 * w, 0.85 * h
        fy = fy - 0.10 * h

    nx = fbm3(xx * scale, yy * scale - t * 0.35, t * 0.55, octaves=3, seed=seed)
    ny = fbm3(xx * scale + 40.0, yy * scale - t * 0.41, t * 0.49, octaves=3, seed=seed + 8)
    xw = (xx + (nx - 0.5) * warp) * scale
    yw = (yy + (ny - 0.5) * warp * 0.65 - t * rise * 42.0) * scale
    dens = fbm3(xw * 1.6, yw * 1.9, t * 0.83, octaves=4, seed=seed + 3)
    holes = fbm3(xw * 3.1, yw * 2.4, t * 1.21, octaves=3, seed=seed + 15)
    dens = np.clip(dens * 1.75 - holes * hole * 0.72, 0.0, 1.0)

    dx = (xx - fx) / max(width, 1.0)
    rise_n = np.clip((fy - yy) / max(height, 1.0), 0.0, 1.35)
    taper = 1.0 + 1.15 * rise_n
    rad = (dx / np.maximum(taper, 0.12)) ** 2 + ((yy - fy) / max(height, 1.0)) ** 2
    envelope = np.exp(-rad * 2.35) * np.clip(1.05 - 0.38 * rise_n, 0.18, 1.0)
    edge_x = np.minimum(xx / (0.08 * w), (w - 1 - xx) / (0.08 * w))
    edge_y = np.minimum(yy / (0.06 * h), (h - 1 - yy) / (0.10 * h))
    envelope *= np.clip(np.minimum(edge_x, edge_y), 0.0, 1.0)
    field = dens * envelope
    field = np.power(np.clip(field, 0.0, 1.0), 1.12)
    return field.astype(np.float32)


def _colorize_fire(field: np.ndarray, yy: np.ndarray, fy: float, h: int) -> np.ndarray:
    height = np.clip((fy - yy) / (0.62 * h), 0.0, 1.0)
    core = np.power(field, 1.85)
    r = np.clip(field * (0.50 + 0.50 * height) + core * 0.85, 0.0, 1.0)
    g = np.clip(field * (0.18 + 0.48 * height) + core * 0.62, 0.0, 1.0)
    b = np.clip(core * (0.10 + 0.28 * height), 0.0, 1.0)
    return np.stack([b, g, r], axis=2)


def _colorize_smoke(field: np.ndarray, luma: float) -> np.ndarray:
    cool = 0.18 + 0.12 * luma
    warm = 0.10 + 0.08 * luma
    b = np.full_like(field, cool) + field * 0.05
    g = np.full_like(field, warm + 0.04)
    r = np.full_like(field, warm + 0.07)
    return np.stack([b, g, r], axis=2).astype(np.float32)


def fire_behind_realistic(
    frame: np.ndarray,
    matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    """Photoreal fire sitting on the background plane. Subject pixels stay original."""
    h, w = frame.shape[:2]
    env = _envelope(t, duration) * float(intensity)
    if env < 0.02:
        return frame
    matte = refine_matte_for_composite(frame, matte)
    src = _to_float(frame)
    fx, fy, _cx, _cy = _fire_origin(matte)
    sh, sw = max(8, h // 2), max(8, w // 2)
    scale_y, scale_x = sh / float(h), sw / float(w)
    near_s = _plume_field(sh, sw, t, fx * scale_x, fy * scale_y, "near")
    far_s = _plume_field(sh, sw, t + 0.37, fx * scale_x, (fy - 0.04 * h) * scale_y, "far")
    smoke_s = _plume_field(sh, sw, t * 0.72 + 1.9, fx * scale_x, fy * scale_y, "smoke")
    yy_s, _ = np.mgrid[0:sh, 0:sw].astype(np.float32)
    fire_near = _colorize_fire(near_s, yy_s, fy * scale_y, sh)
    fire_far = _colorize_fire(far_s * 0.72, yy_s, fy * scale_y, sh)
    luma = float(np.clip(src.mean(), 0.12, 0.85))
    smoke_col = _colorize_smoke(smoke_s, luma)

    near = cv2.resize(near_s, (w, h), interpolation=cv2.INTER_CUBIC)
    far = cv2.resize(far_s, (w, h), interpolation=cv2.INTER_CUBIC)
    smoke_a = cv2.resize(smoke_s, (w, h), interpolation=cv2.INTER_CUBIC)
    fire_n = cv2.resize(fire_near, (w, h), interpolation=cv2.INTER_CUBIC)
    fire_f = cv2.resize(fire_far, (w, h), interpolation=cv2.INTER_CUBIC)
    smoke_c = cv2.resize(smoke_col, (w, h), interpolation=cv2.INTER_CUBIC)

    # Depth: far layer softer and slightly smaller in perspective.
    fire_f = cv2.GaussianBlur(fire_f, (0, 0), 1.15)
    far = cv2.GaussianBlur(far, (0, 0), 1.05)
    fire_n = cv2.GaussianBlur(fire_n, (0, 0), 0.35)
    smoke_a = cv2.GaussianBlur(smoke_a, (0, 0), 2.1)

    occ = np.clip(1.0 - matte, 0.0, 1.0)
    near *= occ
    far *= occ
    smoke_a *= np.clip(occ + 0.08, 0.0, 1.0)
    fire_n *= occ[..., None]
    fire_f *= occ[..., None]

    energy_map = cv2.GaussianBlur(np.maximum(near, far * 0.7), (0, 0), 16.0) * env
    flicker = _flicker(t, float(np.percentile(energy_map, 90)) * 3.5)

    # Heat distortion: background above the flames only, never the face.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    above = np.clip((fy - 0.12 * h - yy) / (0.22 * h), 0.0, 1.0)
    heat = energy_map * above * occ * (1.0 - protect_mask(matte, 11))
    heat = cv2.GaussianBlur(heat, (0, 0), 3.0)
    nht = fbm3(xx * 0.04, yy * 0.04 - t * 1.4, t * 0.9, octaves=2, seed=70.0)
    mag = heat * 2.2
    map_x = np.clip(xx + (nht - 0.5) * mag, 0, w - 1).astype(np.float32)
    map_y = np.clip(yy + (np.roll(nht, 4, 1) - 0.5) * mag * 0.55, 0, h - 1).astype(np.float32)
    warped = cv2.remap(src, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    heat_mix = np.clip(heat * 1.4, 0.0, 0.55)[..., None]
    plate = src * (1.0 - heat_mix) + warped * heat_mix

    # Local warm response on background (not a global orange wash).
    warm = np.array([0.06, 0.32, 0.78], dtype=np.float32)
    light = energy_map * flicker * 0.34
    plate = plate + plate * (warm * light[..., None])
    plate = plate + warm * (energy_map * flicker * 0.08)[..., None]
    # Gentle local contrast lift near the flame bed, darker just below.
    below = np.clip((yy - fy) / (0.18 * h), 0.0, 1.0) * occ
    plate = plate * (1.0 - 0.10 * (below * energy_map * flicker)[..., None])

    smoke_alpha = np.clip(smoke_a * env * 0.38 * flicker, 0.0, 0.40)[..., None]
    plate = plate * (1.0 - smoke_alpha) + smoke_c * smoke_alpha

    # Emissive flames: add, after a local bed so they read on a bright red room.
    bed = cv2.GaussianBlur(np.maximum(near, far * 0.6), (0, 0), 10.0)
    plate = plate * (1.0 - (0.24 * bed * env * flicker)[..., None])
    far_add = fire_f * (np.clip(far * 1.15, 0.0, 1.0) * env * 0.90 * flicker)[..., None]
    near_add = fire_n * (np.clip(near * 1.35, 0.0, 1.0) * env * 1.25 * flicker)[..., None]
    plate = np.clip(plate + far_add + near_add, 0.0, 1.0)

    glow = cv2.GaussianBlur(near_add + far_add * 0.7, (0, 0), 7.0)
    plate = np.clip(plate + glow * 0.28, 0.0, 1.0)

    # Person: original pixels. Rim light only on fire-facing silhouette, not the face fill.
    person = matte[..., None]
    out = plate * (1.0 - person) + src * person
    solid = (matte > 0.35).astype(np.uint8) * 255
    eroded = cv2.erode(solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    edge = np.clip(matte - eroded.astype(np.float32) / 255.0, 0.0, 1.0)
    gate = _face_gate(matte)
    fire_side = np.clip(1.0 - np.abs(xx - fx) / (0.42 * w), 0.0, 1.0)
    rim = edge * gate * fire_side * energy_map * flicker * 0.42
    rim_col = np.array([0.10, 0.32, 0.78], dtype=np.float32)
    out = out + rim_col * rim[..., None]

    protect = protect_mask(matte, 12)[..., None]
    out = out * (1.0 - protect) + src * protect

    # Match source softness/grain on the VFX, then restore the subject interior.
    look = cv2.GaussianBlur(out, (0, 0), 0.35)
    look = look + _source_grain(frame)
    src_black = float(np.percentile(src, 2))
    look_black = float(np.percentile(look, 2))
    look = look - (look_black - src_black) * 0.65
    out = np.clip(look, 0.0, 1.0) * (1.0 - protect) + src * protect
    return _to_u8(out)
