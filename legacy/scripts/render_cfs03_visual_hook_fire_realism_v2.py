# Realism v2 of CFS03 fire-behind hook. Does not overwrite the approved POC or any Reel.
from __future__ import annotations

import hashlib
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
POC_MP4 = OUT_DIR / "CFS03_fire_behind_c.mp4"
POC_CMP = OUT_DIR / "CFS03_fire_behind_c_before_after.mp4"
HOOK_MP4 = OUT_DIR / "CFS03_fire_behind_c_realism_v2.mp4"
COMPARE_MP4 = OUT_DIR / "CFS03_fire_behind_c_realism_v2_before_after.mp4"
HOOK_JSON = OUT_DIR / "CFS03_fire_behind_c_realism_v2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not POC_MP4.is_file():
        raise FileNotFoundError(f"Approved POC missing: {POC_MP4}")
    poc_hash = _sha(POC_MP4)
    poc_cmp_hash = _sha(POC_CMP) if POC_CMP.is_file() else None
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
        raise RuntimeError("visual hook config is disabled")
    profile = load_profile(PROFILE)
    source = _resolve_source_video(SOURCE, HOOK_JSON)
    before_profile = PROFILE.read_bytes()
    info = render_visual_hook(
        source,
        profile,
        cfg,
        HOOK_MP4,
        before_after_path=COMPARE_MP4,
    )
    if PROFILE.read_bytes() != before_profile:
        raise RuntimeError("Framing profile was modified")
    if _sha(POC_MP4) != poc_hash:
        raise RuntimeError("Approved POC was overwritten")
    if poc_cmp_hash and _sha(POC_CMP) != poc_cmp_hash:
        raise RuntimeError("Approved POC comparison was overwritten")
    payload = {
        "kind": "visual_hook_fire_realism_v2",
        "note": "Improved fire-behind realism only. Not attached to any Reel. Does not replace the approved POC.",
        "visual_hook": cfg.as_dict(),
        "render": info,
        "preserved_poc": str(POC_MP4),
        "preserved_poc_sha256": poc_hash,
        "source_video": "data/inbox/CFS03.mp4",
        "framing_profile": "data/framing_profiles/CFS03.json",
        "vfx_assets": "local aperiodic photoreal fire/smoke plates (hash-noise tongues, no stock footage)",
        "sfx_assets": "quiet procedural ignition/flare under original dialogue",
    }
    write_json(HOOK_JSON, payload)
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
