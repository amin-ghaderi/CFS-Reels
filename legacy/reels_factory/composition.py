from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

STACK_ORDER_916 = ("speaker_b", "speaker_c", "speaker_a")
DEFAULT_CANVAS = (1080, 1920)
DEFAULT_TILE_ASPECT = 16 / 9
DEFAULT_PAD_COLOR = (0, 0, 0)


@dataclass(frozen=True)
class StackedThreeGeometry:
    canvas_w: int
    canvas_h: int
    tile_w: int
    tile_h: int
    pad_top: int
    pad_bottom: int
    n_tiles: int
    stack_order: tuple[str, ...]
    pad_color: str = "black"

    @property
    def stacked_h(self) -> int:
        return self.tile_h * self.n_tiles

    def y_offset(self, key: str) -> int:
        y = self.pad_top
        for name in self.stack_order:
            if name == key:
                return y
            y += self.tile_h
        raise KeyError(key)


def stacked_three_geometry(
    canvas_w: int = DEFAULT_CANVAS[0],
    canvas_h: int = DEFAULT_CANVAS[1],
    *,
    n_tiles: int = 3,
    tile_aspect: float = DEFAULT_TILE_ASPECT,
    stack_order: tuple[str, ...] = STACK_ORDER_916,
    pad_color: str = "black",
) -> StackedThreeGeometry:
    """Integer 9:16 stack of full 16:9 tiles with even leftover padding.

    Three 1080-wide 16:9 tiles are 608px tall; 3*608 = 1824, so 96px remains
    and is split 48/48 top/bottom. Tiles sit flush; leftover is outer pad only.
    """
    if canvas_w < 2 or canvas_h < 2 or n_tiles < 1:
        raise ValueError("canvas and tile count must be positive")
    tile_w = int(canvas_w)
    tile_h = int(round(tile_w / float(tile_aspect)))
    if tile_h % 2:
        tile_h += 1
    stacked = tile_h * n_tiles
    remainder = canvas_h - stacked
    if remainder < 0:
        raise ValueError(
            f"{n_tiles} tiles of {tile_w}x{tile_h} exceed canvas {canvas_w}x{canvas_h}"
        )
    pad_top = remainder // 2
    pad_bottom = remainder - pad_top
    order = tuple(stack_order) if stack_order else STACK_ORDER_916
    if len(order) != n_tiles:
        raise ValueError("stack_order length must match n_tiles")
    return StackedThreeGeometry(
        canvas_w=tile_w,
        canvas_h=int(canvas_h),
        tile_w=tile_w,
        tile_h=tile_h,
        pad_top=pad_top,
        pad_bottom=pad_bottom,
        n_tiles=n_tiles,
        stack_order=order,
        pad_color=pad_color,
    )


def _bgr(color: tuple[int, int, int] | str) -> tuple[int, int, int]:
    if isinstance(color, str):
        return DEFAULT_PAD_COLOR
    return (int(color[0]), int(color[1]), int(color[2]))


def scale_tile_no_stretch(tile: np.ndarray, tile_w: int, tile_h: int) -> np.ndarray:
    """Fit the full tile into tile_w x tile_h. No crop. No aspect distortion.

    Integer 16:9 → 1080x608 is a half-pixel rasterization (607.5 → 608). Any
    leftover inside the slot is centered padding, never a face crop.
    """
    if tile.ndim != 3 or tile.shape[2] < 3:
        raise ValueError("tile must be an HxWxC image")
    src_h, src_w = tile.shape[:2]
    if src_w < 2 or src_h < 2:
        raise ValueError("tile is empty")
    scale = min(tile_w / src_w, tile_h / src_h)
    out_w = max(1, int(round(src_w * scale)))
    out_h = max(1, int(round(src_h * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LANCZOS4
    fitted = cv2.resize(tile, (out_w, out_h), interpolation=interp)
    if out_w == tile_w and out_h == tile_h:
        return fitted
    canvas = np.zeros((tile_h, tile_w, tile.shape[2]), dtype=tile.dtype)
    x = (tile_w - out_w) // 2
    y = (tile_h - out_h) // 2
    canvas[y : y + out_h, x : x + out_w] = fitted
    return canvas


def compose_stacked_three(
    tiles: dict[str, np.ndarray],
    *,
    canvas_w: int = DEFAULT_CANVAS[0],
    canvas_h: int = DEFAULT_CANVAS[1],
    pad_bgr: tuple[int, int, int] = DEFAULT_PAD_COLOR,
    stack_order: tuple[str, ...] = STACK_ORDER_916,
) -> tuple[np.ndarray, StackedThreeGeometry]:
    geo = stacked_three_geometry(
        canvas_w, canvas_h, n_tiles=len(stack_order), stack_order=stack_order
    )
    missing = [key for key in geo.stack_order if key not in tiles]
    if missing:
        raise KeyError(f"missing tiles: {missing}")
    canvas = np.full((geo.canvas_h, geo.canvas_w, 3), _bgr(pad_bgr), dtype=np.uint8)
    for key in geo.stack_order:
        scaled = scale_tile_no_stretch(tiles[key][:, :, :3], geo.tile_w, geo.tile_h)
        y = geo.y_offset(key)
        canvas[y : y + geo.tile_h, 0 : geo.tile_w] = scaled
    return canvas, geo


def crop_xywh(frame: np.ndarray, box: dict) -> np.ndarray:
    h, w = frame.shape[:2]
    x = max(0, int(round(box["x"])))
    y = max(0, int(round(box["y"])))
    bw = max(1, int(round(box["w"])))
    bh = max(1, int(round(box["h"])))
    x1 = min(w, x + bw)
    y1 = min(h, y + bh)
    patch = frame[y:y1, x:x1]
    if patch.size == 0:
        raise ValueError(f"empty crop {box}")
    return patch
