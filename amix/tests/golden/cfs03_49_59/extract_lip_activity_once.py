"""One-shot fixture extraction. Not part of the test suite.

Reads the local CFS03 master with the legacy overlap decoder and writes
compact lip/audio activity under inputs/. Imports legacy only when executed.
AMIX tests must not import this module.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
LEGACY = REPO / "legacy"
sys.path.insert(0, str(LEGACY))

from reels_factory.cfs_overlap import collect_lip_activity, overlaps_from_activity  # noqa: E402

SOURCE = LEGACY / "data" / "inbox" / "03.mp4"
EXPECTED = LEGACY / "data" / "speakers" / "CFS03_49-59_overlaps_v3.json"
OUT = Path(__file__).resolve().parent / "inputs" / "lip_activity.json"
ORIGIN = 2960.0
DURATION = 600.0


def main() -> None:
    print("decode", SOURCE, flush=True)
    activity = collect_lip_activity(SOURCE, ORIGIN, DURATION)
    regions, meta = overlaps_from_activity(activity)
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))["regions"]
    got = [(round(r["start"], 3), round(r["end"], 3), tuple(r["speakers_active"])) for r in regions]
    want = [(round(r["start"], 3), round(r["end"], 3), tuple(r["speakers_active"])) for r in expected]
    if got != want:
        raise SystemExit(f"legacy recompute mismatch\n got {got}\nwant {want}")
    import numpy as np

    scores = np.round(activity["scores"].astype(float), 5)
    rms = np.round(activity["audio_rms"].astype(float), 6)
    rounded = {
        "origin": activity["origin"],
        "fps": activity["fps"],
        "times": activity["times"],
        "scores": scores.astype(np.float32),
        "audio_rms": rms.astype(np.float32),
    }
    rounded_regions, _rounded_meta = overlaps_from_activity(rounded)
    rounded_got = [
        (round(r["start"], 3), round(r["end"], 3), tuple(r["speakers_active"]))
        for r in rounded_regions
    ]
    if rounded_got != want:
        raise SystemExit(f"rounded activity mismatch\n got {rounded_got}\nwant {want}")
    payload = {
        "role": "INPUT",
        "description": "Pre-region lip scores and mixed-audio RMS. Not overlap regions.",
        "source": "legacy/reels_factory/cfs_overlap.py::collect_lip_activity",
        "origin_seconds": ORIGIN,
        "duration_seconds": DURATION,
        "sample_fps": 8,
        "column_order": ["cfs03-a", "cfs03-b", "cfs03-c"],
        "legacy_column_order": ["speaker_a", "speaker_b", "speaker_c"],
        "audio_gate_legacy": meta["audio_gate"],
        "frame_count": int(len(activity["times"])),
        "scores": scores.tolist(),
        "audio_rms": rms.tolist(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT, "frames", payload["frame_count"], "bytes", OUT.stat().st_size, flush=True)
    print("regions", len(got), "gate", meta["audio_gate"], flush=True)


if __name__ == "__main__":
    main()
