"""Layout geometry checks. Rectangles are not stretched or rewritten."""
from __future__ import annotations

from amix.amix_engine.domain.types import LayoutBinding, ParticipantId
from amix.amix_engine.time.clock import TimeError, TimeRange

COORDINATE_SPACE = "display_pixels"


class LayoutRejected(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "invalid_layout"


def validate_layout(
    *,
    participant_id: str,
    start_us: object,
    end_us: object,
    x: object,
    y: object,
    w: object,
    h: object,
    picture_width: int | None,
    picture_height: int | None,
) -> LayoutBinding:
    if not isinstance(participant_id, str) or not participant_id.strip():
        raise LayoutRejected("Choose a participant.")
    start = _int(start_us, "start")
    end = _int(end_us, "end")
    left = _int(x, "x")
    top = _int(y, "y")
    width = _int(w, "width")
    height = _int(h, "height")
    if start < 0 or end < 0:
        raise LayoutRejected("Layout times must be canonical microseconds.")
    if start >= end:
        raise LayoutRejected("The layout range must start before it ends.")
    if left < 0 or top < 0:
        raise LayoutRejected("Layout position must stay on the picture.")
    if width <= 0 or height <= 0:
        raise LayoutRejected("Layout width and height must be positive.")
    if picture_width is not None and picture_height is not None:
        if picture_width <= 0 or picture_height <= 0:
            raise LayoutRejected("The picture size is not usable.")
        if left >= picture_width or top >= picture_height:
            raise LayoutRejected("That rectangle is outside the picture.")
    try:
        span = TimeRange(start, end)
    except TimeError as exc:
        raise LayoutRejected("The layout range must start before it ends.") from exc
    return LayoutBinding(ParticipantId(participant_id), left, top, width, height, span)


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LayoutRejected(f"Layout {name} must be an integer.")
    return value


def layout_fingerprint(records: list[dict]) -> str:
    """Exact identity of the bindings overlap and plans were measured against."""
    import hashlib
    import json

    payload = [
        {
            "coordinate_space": COORDINATE_SPACE,
            "participant_id": row["participant_id"],
            "start_us": row["start_us"],
            "end_us": row["end_us"],
            "x": row["x"],
            "y": row["y"],
            "w": row["w"],
            "h": row["h"],
        }
        for row in sorted(records, key=lambda item: (
            item["participant_id"], item["start_us"], item["end_us"], item["x"], item["y"], item["w"], item["h"],
        ))
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def protected_fingerprint(regions: list[tuple[int, int]]) -> str:
    import hashlib
    import json

    payload = [{"start_us": start, "end_us": end} for start, end in sorted(regions)]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()
