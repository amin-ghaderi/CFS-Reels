from pathlib import Path

import numpy as np

from reels_factory.composition import (
    STACK_ORDER_916,
    compose_stacked_three,
    stacked_three_geometry,
)
from reels_factory.faces import BBox, stacked_three_tiles_filter
from reels_factory.framing import (
    ffmpeg_crops,
    layout_from_framing_profile,
    load_framing_profile,
)


PROFILE = Path("data/framing_profiles/CFS03.json")
RCLOUD = {"width": 1080, "height": 1920, "fps": 30}


def test_1080x1920_three_tile_padding():
    geo = stacked_three_geometry(1080, 1920)
    assert geo.canvas_w == 1080
    assert geo.canvas_h == 1920
    assert geo.tile_w == 1080
    assert geo.tile_h == 608
    assert geo.pad_top == 48
    assert geo.pad_bottom == 48
    assert geo.pad_top + 3 * geo.tile_h + geo.pad_bottom == 1920
    assert geo.stack_order == STACK_ORDER_916
    assert geo.y_offset("speaker_b") == 48
    assert geo.y_offset("speaker_c") == 48 + 608
    assert geo.y_offset("speaker_a") == 48 + 608 + 608


def test_compose_preserves_tile_aspect_and_equal_width():
    tiles = {
        "speaker_a": np.full((504, 896, 3), 10, dtype=np.uint8),
        "speaker_b": np.full((504, 896, 3), 80, dtype=np.uint8),
        "speaker_c": np.full((504, 896, 3), 160, dtype=np.uint8),
    }
    canvas, geo = compose_stacked_three(tiles)
    assert canvas.shape == (1920, 1080, 3)
    assert canvas[: geo.pad_top].mean() < 1
    assert canvas[-geo.pad_bottom :].mean() < 1
    top = canvas[48:656]
    mid = canvas[656:1264]
    bot = canvas[1264:1872]
    assert top.shape == (608, 1080, 3)
    assert mid.shape == (608, 1080, 3)
    assert bot.shape == (608, 1080, 3)
    assert int(top.mean()) == 80
    assert int(mid.mean()) == 160
    assert int(bot.mean()) == 10


def test_cfs03_profile_stacks_b_c_a_without_face_crop():
    data = load_framing_profile(PROFILE)
    assert data["stack_order"] == ["speaker_b", "speaker_c", "speaker_a"]
    layout = layout_from_framing_profile(data, RCLOUD)
    override = layout_from_framing_profile(
        data, RCLOUD, stack_order=["speaker_b", "speaker_a", "speaker_c"]
    )
    assert override.top == layout.top
    assert override.middle == layout.bottom
    assert override.bottom == layout.middle
    assert data["stack_order"] == ["speaker_b", "speaker_c", "speaker_a"]
    assert layout.mode == "stacked_three"
    assert layout.top == BBox(972, 24, 896, 504)
    assert layout.middle == BBox(512, 552, 896, 504)
    assert layout.bottom == BBox(52, 24, 896, 504)
    crops = ffmpeg_crops(layout.filter_complex)
    assert crops == [
        (896, 504, 972, 24),
        (896, 504, 512, 552),
        (896, 504, 52, 24),
    ]
    assert "vstack=inputs=3" in layout.filter_complex
    assert "pad=1080:1920:0:48" in layout.filter_complex
    assert "force_original_aspect_ratio=increase" not in layout.filter_complex
    assert layout.filter_complex.count("crop=1080:") == 0


def test_stacked_three_filter_uses_decrease_not_crop_fill():
    filt = stacked_three_tiles_filter(
        BBox(972, 24, 896, 504),
        BBox(512, 552, 896, 504),
        BBox(52, 24, 896, 504),
        1920,
        1080,
        1080,
        1920,
        30,
    )
    assert "force_original_aspect_ratio=decrease" in filt
    assert "scale=1080:608" in filt
    assert filt.endswith("[v]")
