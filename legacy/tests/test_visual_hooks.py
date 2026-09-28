from pathlib import Path

import numpy as np

from reels_factory.framing import load_framing_profile
from reels_factory.visual_hooks import (
    PRESET_NAMES,
    apply_hook_frames,
    foreground_unchanged,
    frozen_crop,
    parse_visual_hook,
    visual_hook_enabled,
)
from reels_factory.visual_hooks.config import clamp_duration
from reels_factory.visual_hooks.presets import apply_preset
from reels_factory.visual_hooks.segment import protect_mask


PROFILE = Path("data/framing_profiles/CFS03.json")


def _ellipse_matte(h=80, w=120) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    rad = ((xx - w * 0.5) / (w * 0.22)) ** 2 + ((yy - h * 0.48) / (h * 0.38)) ** 2
    return np.clip(1.2 - rad, 0.0, 1.0).astype(np.float32)


def test_missing_or_disabled_hook_leaves_pipeline_untouched():
    assert parse_visual_hook(None) is None
    assert parse_visual_hook({}) is None
    assert visual_hook_enabled({}) is False
    assert visual_hook_enabled({"visual_hook": {"enabled": False, "preset": "fire_behind_subject"}}) is False
    cfg = parse_visual_hook({"enabled": False, "preset": "fire_behind_subject", "target_speaker": "speaker_c"})
    assert cfg is not None and cfg.enabled is False


def test_enabled_config_fields():
    cfg = parse_visual_hook({
        "enabled": True,
        "preset": "fire_behind_subject",
        "target_speaker": "speaker_c",
        "duration": 1.2,
        "intensity": 0.7,
        "sfx_enabled": True,
        "start_time": 5064.1,
    })
    assert cfg is not None
    assert cfg.enabled is True
    assert cfg.preset == "fire_behind_subject"
    assert cfg.target_speaker == "speaker_c"
    assert cfg.duration == 1.2
    assert cfg.intensity == 0.7
    assert cfg.sfx_enabled is True
    assert visual_hook_enabled({"visual_hook": cfg.as_dict()}) is True


def test_duration_clamp_and_preset_list():
    assert clamp_duration(0.2) == 0.8
    assert clamp_duration(9.0) == 2.5
    assert set(PRESET_NAMES) == {
        "fire_behind_subject",
        "glass_crack",
        "smoke_hit",
        "electric_spark",
        "light_burst",
        "impact_shake",
    }


def test_frozen_cfs03_speaker_c_crop_unchanged():
    profile = load_framing_profile(PROFILE)
    assert frozen_crop(profile, "speaker_c") == (512, 552, 896, 504)
    assert profile["speaker_c"] == {"x": 512, "y": 552, "w": 896, "h": 504}


def test_fire_behind_keeps_protected_subject_pixels():
    rng = np.random.default_rng(0)
    h, w = 90, 140
    frame = rng.integers(20, 200, size=(h, w, 3), dtype=np.uint8)
    matte = _ellipse_matte(h, w)
    hooked = apply_preset("fire_behind_subject", frame, matte, 0.4, 1.2, 0.8)
    assert hooked.shape == frame.shape
    protect = protect_mask(matte, 14) > 0.85
    if int(protect.sum()) >= 16:
        delta = np.max(np.abs(frame.astype(np.int16) - hooked.astype(np.int16)), axis=2)
        assert float((delta[protect] <= 3).mean()) >= 0.97
    bg = matte < 0.2
    bg_delta = np.mean(np.abs(frame[bg].astype(np.int16) - hooked[bg].astype(np.int16)))
    fg_delta = np.mean(np.abs(frame[protect].astype(np.int16) - hooked[protect].astype(np.int16)))
    assert bg_delta > fg_delta
    assert bg_delta > 4


def test_all_presets_run_on_synthetic_frame():
    rng = np.random.default_rng(1)
    frame = rng.integers(10, 220, size=(64, 96, 3), dtype=np.uint8)
    matte = _ellipse_matte(64, 96)
    cfg = parse_visual_hook({
        "enabled": True,
        "preset": "smoke_hit",
        "target_speaker": "speaker_a",
        "duration": 1.0,
        "intensity": 0.6,
        "sfx_enabled": False,
    })
    assert cfg is not None
    from reels_factory.visual_hooks.config import VisualHookConfig

    for name in PRESET_NAMES:
        hook = VisualHookConfig(
            enabled=True,
            preset=name,
            target_speaker="speaker_c",
            start_time=0.0,
            duration=1.0,
            intensity=0.7,
            sfx_enabled=False,
        )
        out, _, _ = apply_hook_frames([frame, frame, frame], hook, fps=30)
        assert len(out) == 3
        assert out[0].shape == frame.shape
