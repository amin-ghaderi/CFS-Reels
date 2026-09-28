"""Detect overlap on 00:49:20-00:59:20. Does not rewrite turns or word speakers."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_overlap import (  # noqa: E402
    SAMPLE_FPS,
    collect_lip_activity,
    overlaps_from_activity,
)
from reels_factory.speaker_resolver_v2 import SPEAKERS  # noqa: E402
from reels_factory.utils import ts  # noqa: E402

ORIGIN = 2960.0
DURATION = 600.0
SOURCE = ROOT / "data/inbox/03.mp4"
TURNS = ROOT / "data/speakers/CFS03_49-59_turns_v3.json"
OUT = ROOT / "data/speakers/CFS03_49-59_overlaps_v3.json"
CACHE = ROOT / "data/tmp_cfs03_preview/overlap_49_59_scores.npz"

# Evaluation spans only. They are not written into the overlap regions.
CHECKS = [
    ("C solo 51:10", 3069.5, 3088.0),
    ("handoff 51:46", 3104.0, 3116.0),
    ("B solo 52:26", 3146.0, 3163.0),
    ("A solo 53:08", 3188.0, 3208.0),
    ("C late 58:40", 3520.0, 3555.0),
]


def main() -> None:
    before = TURNS.stat().st_mtime
    if CACHE.is_file():
        print("load cache", flush=True)
        data = np.load(CACHE)
        activity = {
            "origin": ORIGIN,
            "fps": SAMPLE_FPS,
            "times": data["times"],
            "scores": data["scores"],
            "audio_rms": data["audio_rms"],
        }
    else:
        print("scan", flush=True)
        activity = collect_lip_activity(SOURCE, ORIGIN, DURATION)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        np.savez(CACHE, times=activity["times"], scores=activity["scores"], audio_rms=activity["audio_rms"])
    print("frames", len(activity["times"]), flush=True)
    for name, a, b in CHECKS:
        m = (activity["times"] >= a) & (activity["times"] < b)
        means = activity["scores"][m].mean(axis=0) if m.any() else [0, 0, 0]
        hot = (activity["scores"][m] >= 4.2).mean(axis=0) if m.any() else [0, 0, 0]
        print(
            name,
            "mean",
            {k: round(float(v), 2) for k, v in zip(SPEAKERS, means)},
            "frac",
            {k: round(float(v), 2) for k, v in zip(SPEAKERS, hot)},
            flush=True,
        )
    regions, meta = overlaps_from_activity(activity)
    payload = {
        "kind": "cfs_overlap_v3",
        "source_video": "data/inbox/03.mp4",
        "range": {"start": "00:49:20.000", "end": "00:59:20.000", "start_s": ORIGIN, "end_s": ORIGIN + DURATION},
        "floor_timeline": "data/speakers/CFS03_49-59_turns_v3.json",
        "floor_timeline_modified": False,
        "method": "tight_lip_jaw_motion_plus_mixed_audio",
        "does_not_rewrite_speaker_identity": True,
        "overlap_count": len(regions),
        "overlap_duration_s": round(sum(row["duration"] for row in regions), 3),
        "meta": meta,
        "regions": regions,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("regions", len(regions), "duration", payload["overlap_duration_s"], flush=True)
    for row in regions:
        print(
            ts(row["start"]),
            ts(row["end"]),
            ",".join(row["speakers_active"]),
            row["duration"],
            row["confidence"],
            row["evidence"],
            flush=True,
        )
    print("turns_mtime_unchanged", TURNS.stat().st_mtime == before, flush=True)


if __name__ == "__main__":
    main()
