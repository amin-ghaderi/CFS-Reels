"""Output canvas presets. Landscape and portrait are sizes, not pipelines."""
from __future__ import annotations

from dataclasses import dataclass

PROFILE_ID = "amix.multicam.render.v1"
FRAMING_POLICY = "center_fill.v1"
FALLBACK_FPS = (30, 1)


class InvalidPreset(ValueError):
    def __init__(self) -> None:
        super().__init__(PROFILE_ID)
        self.code = "invalid_render_preset"


@dataclass(frozen=True)
class RenderPreset:
    preset_id: str
    label: str
    width: int
    height: int
    aspect: str


PRESETS: dict[str, RenderPreset] = {
    "landscape_1080": RenderPreset("landscape_1080", "Landscape 1080", 1920, 1080, "16:9"),
    "landscape_720": RenderPreset("landscape_720", "Landscape 720", 1280, 720, "16:9"),
    "portrait_1080": RenderPreset("portrait_1080", "Portrait 1080", 1080, 1920, "9:16"),
    "portrait_720": RenderPreset("portrait_720", "Portrait 720", 720, 1280, "9:16"),
}


def preset_from_id(value: object) -> RenderPreset:
    if not isinstance(value, str) or value not in PRESETS:
        raise InvalidPreset()
    return PRESETS[value]


def output_frame_rate(fps_num: int | None, fps_den: int | None) -> tuple[int, int]:
    """Average source frame rate, or 30/1 when the probe has no usable rational."""
    if isinstance(fps_num, bool) or isinstance(fps_den, bool):
        return FALLBACK_FPS
    if isinstance(fps_num, int) and isinstance(fps_den, int) and fps_num > 0 and fps_den > 0:
        return fps_num, fps_den
    return FALLBACK_FPS
