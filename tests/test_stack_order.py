from pathlib import Path

from reels_factory.config import load_config
from reels_factory.faces import BBox
from reels_factory.framing import layout_from_framing_profile, load_framing_profile
from reels_factory.stack_order import (
    DEFAULT_STACK,
    choose_static_stack_order,
    resolve_reel_stack_order,
    speaking_durations,
)
from reels_factory.utils import read_json


PROFILE = Path("data/framing_profiles/CFS03.json")
RCLOUD = {"width": 1080, "height": 1920, "fps": 30}
CROP_A = BBox(52, 24, 896, 504)
CROP_B = BBox(972, 24, 896, 504)
CROP_C = BBox(512, 552, 896, 504)


def test_speaking_durations_use_overlap_not_block_count():
    blocks = [
        {"speaker": "speaker_a", "start": 0.0, "end": 10.0},
        {"speaker": "speaker_b", "start": 8.0, "end": 12.0},
        {"speaker": "unknown", "start": 20.0, "end": 30.0},
    ]
    dur = speaking_durations(blocks, [(9.0, 11.0)])
    assert dur["speaker_a"] == 1.0
    assert dur["speaker_b"] == 2.0
    assert dur["speaker_c"] == 0.0
    assert dur["unknown"] == 0.0


def test_fallback_when_unknown_can_flip_rank():
    result = choose_static_stack_order(
        {"speaker_a": 0.0, "speaker_b": 31.76, "speaker_c": 51.76, "unknown": 21.9}
    )
    assert result["decision"] == "fallback"
    assert result["final_stack_order"] == list(DEFAULT_STACK)


def test_partial_dynamic_when_second_third_silent():
    result = choose_static_stack_order(
        {"speaker_a": 114.92, "speaker_b": 0.0, "speaker_c": 0.0, "unknown": 0.0}
    )
    assert result["decision"] == "partial_dynamic"
    assert result["final_stack_order"] == ["speaker_b", "speaker_a", "speaker_c"]


def test_dynamic_when_rank_is_safe():
    result = choose_static_stack_order(
        {"speaker_a": 80.0, "speaker_b": 20.0, "speaker_c": 5.0, "unknown": 1.0}
    )
    assert result["decision"] == "dynamic"
    assert result["final_stack_order"] == ["speaker_b", "speaker_a", "speaker_c"]


def test_cfs03_r01_r02_r03_expected_orders():
    cfg = load_config(Path("."))
    source = Path("data/inbox/CFS03.mp4")
    expected = {
        "CFS03.R01": ("fallback", ["speaker_b", "speaker_c", "speaker_a"]),
        "CFS03.R02": ("partial_dynamic", ["speaker_b", "speaker_a", "speaker_c"]),
        "CFS03.R03": ("fallback", ["speaker_b", "speaker_c", "speaker_a"]),
    }
    for stem, (decision, order) in expected.items():
        plan = read_json(Path("data/conversation_plans") / f"{stem}.json")
        result = resolve_reel_stack_order(source, cfg, plan, [])
        assert result["decision"] == decision, stem
        assert result["final_stack_order"] == order, stem


def test_layout_override_remaps_slots_not_crops():
    data = load_framing_profile(PROFILE)
    frozen = dict(data)
    layout = layout_from_framing_profile(
        data, RCLOUD, stack_order=["speaker_b", "speaker_a", "speaker_c"]
    )
    assert data == frozen
    assert data["stack_order"] == ["speaker_b", "speaker_c", "speaker_a"]
    assert data["speaker_a"] == {"x": 52, "y": 24, "w": 896, "h": 504}
    assert data["speaker_b"] == {"x": 972, "y": 24, "w": 896, "h": 504}
    assert data["speaker_c"] == {"x": 512, "y": 552, "w": 896, "h": 504}
    assert layout.top == CROP_B
    assert layout.middle == CROP_A
    assert layout.bottom == CROP_C
    assert layout.panel_a == CROP_A
    assert layout.panel_b == CROP_B
    assert layout.panel_c == CROP_C
