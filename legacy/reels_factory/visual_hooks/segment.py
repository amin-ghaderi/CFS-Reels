from __future__ import annotations

import numpy as np
import cv2


def _grabcut_alpha(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    border = max(6, min(h, w) // 14)
    mask[:border, :] = cv2.GC_BGD
    mask[-border:, :] = cv2.GC_BGD
    mask[:, :border] = cv2.GC_BGD
    mask[:, -border:] = cv2.GC_BGD
    cv2.ellipse(
        mask,
        (w // 2, int(h * 0.48)),
        (max(8, int(w * 0.34)), max(8, int(h * 0.44))),
        0,
        0,
        360,
        int(cv2.GC_FGD),
        -1,
    )
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, mask, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = cv2.medianBlur(fg, 5)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
    dist = cv2.distanceTransform(fg, cv2.DIST_L2, 3)
    return np.clip(dist / 3.0, 0.0, 1.0).astype(np.float32)


class SubjectSegmenter:
    """Local human matting. Prefers rembg u2net_human_seg; GrabCut fallback."""

    def __init__(self, max_side: int = 384):
        self.max_side = int(max_side)
        self.method = "grabcut"
        self._session = None
        self._remove = None
        try:
            from rembg import new_session, remove
        except ImportError:
            return
        for model in ("u2net_human_seg", "u2net"):
            try:
                self._session = new_session(model)
                self._remove = remove
                self.method = f"rembg:{model}"
                break
            except Exception:
                continue

    def alpha(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        scale = min(1.0, self.max_side / float(max(h, w)))
        if scale < 0.999:
            small = cv2.resize(
                bgr,
                (max(8, int(round(w * scale))), max(8, int(round(h * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            small = bgr
        matte = self._alpha_small(small)
        if matte.shape[:2] != (h, w):
            matte = cv2.resize(matte, (w, h), interpolation=cv2.INTER_LINEAR)
        return np.clip(matte, 0.0, 1.0).astype(np.float32)

    def _alpha_small(self, bgr: np.ndarray) -> np.ndarray:
        if self._session is not None and self._remove is not None:
            from PIL import Image

            rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            cut = self._remove(rgb, session=self._session)
            arr = np.array(cut)
            if arr.ndim == 3 and arr.shape[2] >= 4:
                return (arr[:, :, 3].astype(np.float32) / 255.0)
        return _grabcut_alpha(bgr)


def interpolate_alpha(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    return ((1.0 - t) * a + t * b).astype(np.float32)


def temporal_smooth(prev: np.ndarray | None, current: np.ndarray, alpha: float = 0.62) -> np.ndarray:
    if prev is None:
        return current
    return (alpha * current + (1.0 - alpha) * prev).astype(np.float32)


def refine_matte_for_composite(bgr: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Feathered, slightly dilated matte for hair/cloth edges. Does not change RGB."""
    h, w = alpha.shape[:2]
    solid = (alpha > 0.38).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    solid = cv2.morphologyEx(solid, cv2.MORPH_CLOSE, kernel)
    hair = cv2.dilate(solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    dist_in = cv2.distanceTransform(hair, cv2.DIST_L2, 3)
    dist_out = cv2.distanceTransform(255 - hair, cv2.DIST_L2, 3)
    feather = 5.0
    signed = dist_in - dist_out
    refined = np.clip(0.5 + signed / (2.0 * feather), 0.0, 1.0).astype(np.float32)
    refined = cv2.GaussianBlur(refined, (0, 0), 1.1)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.clip(np.sqrt(gx * gx + gy * gy) * 2.2, 0.0, 1.0)
    # Keep image-edge detail (hair) instead of a smeared cut.
    refined = refined * (0.35 + 0.65 * mag) + cv2.GaussianBlur(refined, (0, 0), 2.2) * (0.65 - 0.65 * mag)
    # Edge decontamination: pull semi-transparent pixels toward opaque if they sit on dark clothing.
    edge = (refined > 0.12) & (refined < 0.88)
    dark = gray < 0.22
    refined = np.where(edge & dark, np.clip(refined + 0.22, 0.0, 1.0), refined)
    return np.clip(refined, 0.0, 1.0).astype(np.float32)


def mattes_for_frames(
    frames: list[np.ndarray],
    segmenter: SubjectSegmenter,
    *,
    key_stride: int = 2,
    smooth: float = 0.62,
    progress=None,
    refine: bool = False,
) -> list[np.ndarray]:
    n = len(frames)
    if n == 0:
        return []
    keys = sorted(set(list(range(0, n, max(1, int(key_stride)))) + [n - 1]))
    computed: dict[int, np.ndarray] = {}
    for i, idx in enumerate(keys):
        computed[idx] = segmenter.alpha(frames[idx])
        if progress is not None:
            progress(i + 1, len(keys))
    out: list[np.ndarray] = []
    prev = None
    for i in range(n):
        if i in computed:
            matte = computed[i]
        else:
            lo = max(k for k in keys if k <= i)
            hi = min(k for k in keys if k >= i)
            t = 0.0 if hi == lo else (i - lo) / float(hi - lo)
            matte = interpolate_alpha(computed[lo], computed[hi], t)
        if refine:
            matte = refine_matte_for_composite(frames[i], matte)
        prev = temporal_smooth(prev, matte, smooth)
        out.append(prev)
    return out


def protect_mask(matte: np.ndarray, erode_px: int = 7) -> np.ndarray:
    """Interior of the subject that must stay pixel-identical to the source."""
    k = max(1, int(erode_px))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    solid = (matte > 0.55).astype(np.uint8) * 255
    eroded = cv2.erode(solid, kernel)
    return (eroded.astype(np.float32) / 255.0)


def subject_centroid(matte: np.ndarray) -> tuple[float, float]:
    ys, xs = np.where(matte > 0.45)
    h, w = matte.shape[:2]
    if xs.size < 32:
        return w * 0.5, h * 0.55
    return float(xs.mean()), float(ys.mean())
