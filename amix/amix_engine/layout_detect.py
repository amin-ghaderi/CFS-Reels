"""Face candidates for the visual layout editor.

YuNet finds a face. A participant region starts larger than that face and
stays inside the picture. Nothing here writes a layout or a person name.
"""
from __future__ import annotations

from pathlib import Path

# Deterministic expansion around a face. The result is clamped to the picture.
_WIDTH_SCALE = 2.6
_HEIGHT_SCALE = 3.4
_DOWN_SHIFT = 0.45


class LayoutDetectError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def expand_face(x: float, y: float, width: float, height: float, picture_width: int, picture_height: int) -> tuple[int, int, int, int] | None:
    """Grow one face box into an editable region, or drop it when it cannot fit."""
    if picture_width <= 0 or picture_height <= 0 or width <= 0 or height <= 0:
        return None
    center_x = x + width / 2
    center_y = y + height / 2 + height * _DOWN_SHIFT
    grown_w = width * _WIDTH_SCALE
    grown_h = height * _HEIGHT_SCALE
    left = int(round(center_x - grown_w / 2))
    top = int(round(center_y - grown_h / 2))
    right = int(round(center_x + grown_w / 2))
    bottom = int(round(center_y + grown_h / 2))
    left = max(0, left)
    top = max(0, top)
    right = min(picture_width, right)
    bottom = min(picture_height, bottom)
    if right - left < 2 or bottom - top < 2:
        return None
    return left, top, right - left, bottom - top


def candidate_regions(
    faces: list[tuple[float, float, float, float]],
    picture_width: int,
    picture_height: int,
) -> list[dict[str, int]]:
    """Expanded regions in display pixels, left to right. No person is assigned."""
    regions = []
    ordered = sorted(faces, key=lambda box: (box[0], box[1], box[2], box[3]))
    for x, y, width, height in ordered:
        grown = expand_face(x, y, width, height, picture_width, picture_height)
        if grown is None:
            continue
        left, top, grown_w, grown_h = grown
        regions.append({"x": left, "y": top, "w": grown_w, "h": grown_h})
    return regions


def read_candidate_frame(ffmpeg: Path, source: Path, time_us: int, destination: Path) -> None:
    """Write one display-oriented PNG. ffmpeg applies rotation unless told not to."""
    from amix.amix_engine.adapters.media.process import run_process

    seconds = max(0, time_us) / 1_000_000
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run_process(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{seconds:.6f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-y",
            str(destination),
        ],
        None,
    )
    if result.code != 0 or not destination.is_file() or destination.stat().st_size <= 0:
        raise LayoutDetectError("layout_detect_failed", "A frame could not be read from this media.")


def detect_layout_candidates(store, asset_id: str, time_us: int | None) -> dict:
    """One source frame, the configured YuNet model, expanded regions. No identity is stored."""
    from amix.amix_engine.adapters.media.discovery import discover_tools
    from amix.amix_engine.adapters.media.errors import MediaToolMissing
    from amix.amix_engine.adapters.vision.resolver import VisionResourceError, resolve_vision_model
    from amix.amix_engine.adapters.vision.yunet import YunetDetector
    from amix.amix_engine.storage.errors import MediaMissing

    asset = store.get_media(asset_id)
    if asset.role != "master":
        raise LayoutDetectError("layout_requires_source", "Layout uses the original source media.")
    if asset.width is None or asset.height is None or asset.probed_at is None:
        raise LayoutDetectError("layout_requires_probe", "Probe this media before detecting people.")
    try:
        source = store.require_media(asset_id)
    except MediaMissing as exc:
        raise LayoutDetectError("media_missing", "The media file is missing.") from exc
    try:
        tools = discover_tools()
    except MediaToolMissing as exc:
        raise LayoutDetectError("ffmpeg_unavailable", "FFmpeg is not available.") from exc
    try:
        model = resolve_vision_model()
    except VisionResourceError:
        raise
    origin = 0 if asset.container_start_us is None else asset.container_start_us
    if time_us is None:
        duration = asset.duration_us or 0
        time_us = origin + max(0, duration // 2)
    if time_us < 0:
        raise LayoutDetectError("layout_detect_failed", "That frame is outside this media.")
    frame_path = store.private / "cache" / f"layout-{asset_id}.png"
    try:
        read_candidate_frame(tools.ffmpeg, source, int(time_us), frame_path)
        import cv2
        frame = cv2.imread(str(frame_path))
    finally:
        frame_path.unlink(missing_ok=True)
    if frame is None:
        raise LayoutDetectError("layout_detect_failed", "A frame could not be read from this media.")
    faces = YunetDetector(model.local_path).boxes(frame)
    frame_height, frame_width = frame.shape[:2]
    scaled = scale_faces_to_picture(faces, frame_width, frame_height, asset.width, asset.height)
    return {
        "picture_width": asset.width,
        "picture_height": asset.height,
        "candidates": candidate_regions(scaled, asset.width, asset.height),
    }


def scale_faces_to_picture(
    faces: list[tuple[float, float, float, float]],
    frame_width: int,
    frame_height: int,
    picture_width: int,
    picture_height: int,
) -> list[tuple[float, float, float, float]]:
    if frame_width <= 0 or frame_height <= 0:
        return []
    scale_x = picture_width / frame_width
    scale_y = picture_height / frame_height
    return [
        (x * scale_x, y * scale_y, width * scale_x, height * scale_y)
        for x, y, width, height in faces
    ]
