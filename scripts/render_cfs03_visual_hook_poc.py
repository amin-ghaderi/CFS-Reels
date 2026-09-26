# CFS03-only visual hook proof of concept. Does not attach to Reels or rewrite pipeline outputs.
from __future__ import annotations

import json
from pathlib import Path

from reels_factory.render import _resolve_source_video
from reels_factory.utils import write_json
from reels_factory.visual_hooks import parse_visual_hook, render_visual_hook
from reels_factory.visual_hooks.render import load_profile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "data" / "framing_profiles" / "CFS03.json"
SOURCE = ROOT / "data" / "inbox" / "CFS03.mp4"
OUT_DIR = ROOT / "data" / "visual_hook_tests"
HOOK_MP4 = OUT_DIR / "CFS03_fire_behind_c.mp4"
COMPARE_MP4 = OUT_DIR / "CFS03_fire_behind_c_before_after.mp4"
HOOK_JSON = OUT_DIR / "CFS03_fire_behind_c.json"


def main() -> None:
    raw = {
        "enabled": True,
        "preset": "fire_behind_subject",
        "target_speaker": "speaker_c",
        "start_time": 5064.1,
        "duration": 1.8,
        "intensity": 0.7,
        "sfx_enabled": True,
    }
    cfg = parse_visual_hook(raw)
    if cfg is None or not cfg.enabled:
        raise RuntimeError("POC visual hook config is disabled")
    profile = load_profile(PROFILE)
    source = _resolve_source_video(SOURCE, HOOK_JSON)
    before = PROFILE.read_bytes()
    info = render_visual_hook(
        source,
        profile,
        cfg,
        HOOK_MP4,
        before_after_path=COMPARE_MP4,
    )
    after = PROFILE.read_bytes()
    if before != after:
        raise RuntimeError("Framing profile was modified")
    payload = {
        "kind": "visual_hook_poc",
        "note": "Standalone proof of concept. Not attached to any Reel.",
        "visual_hook": cfg.as_dict(),
        "render": info,
        "source_video": "data/inbox/CFS03.mp4",
        "framing_profile": "data/framing_profiles/CFS03.json",
        "vfx_assets": "procedural (numpy/OpenCV fire, grain, heat shimmer); no generative faces",
        "sfx_assets": "procedural ignition (no music)",
    }
    write_json(HOOK_JSON, payload)
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
