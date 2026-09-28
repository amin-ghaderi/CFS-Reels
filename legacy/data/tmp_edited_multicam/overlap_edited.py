"""Overlap on Edited.mp4 program regions only. Thresholds stay as shipped."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_overlap import collect_lip_activity, overlaps_from_activity

SOURCE = ROOT / "data" / "inbox" / "Edited.mp4"
MAP = ROOT / "data" / "director_tests" / "Edited_editability_map.json"
OUT = ROOT / "data" / "speakers" / "Edited.overlaps_v3.json"
CACHE = ROOT / "data" / "tmp_edited_multicam" / "overlap_cache"


def activity_for(start: float, end: float) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"r_{int(start * 10):07d}.npz"
    if path.is_file():
        print("load", path.name, flush=True)
        data = np.load(path)
        return {
            "origin": start,
            "fps": 8,
            "times": data["times"],
            "scores": data["scores"],
            "audio_rms": data["audio_rms"],
        }
    print(f"scan {start:.1f}-{end:.1f}", flush=True)
    activity = collect_lip_activity(SOURCE, start, end - start)
    np.savez(
        path,
        times=activity["times"],
        scores=activity["scores"],
        audio_rms=activity["audio_rms"],
    )
    return activity


def pieces(start: float, end: float) -> list[tuple[float, float]]:
    rows = []
    cursor = start
    while cursor < end - 0.5:
        stop = min(end, cursor + 600.0)
        rows.append((cursor, stop))
        cursor = stop
    return rows


def main() -> None:
    edit = json.loads(MAP.read_text(encoding="utf-8"))
    regions = []
    meta = None
    for row in edit["directable"]:
        for start, end in pieces(float(row["start"]), float(row["end"])):
            activity = activity_for(start, end)
            found, meta = overlaps_from_activity(activity)
            regions.extend(found)
            print("piece overlaps", len(found), flush=True)
    regions.sort(key=lambda item: item["start"])
    merged = []
    for region in regions:
        if merged and region["start"] - merged[-1]["end"] <= 0.75:
            prev = merged[-1]
            prev["end"] = region["end"]
            prev["duration"] = round(prev["end"] - prev["start"], 3)
            names = list(dict.fromkeys(prev["speakers_active"] + region["speakers_active"]))
            prev["speakers_active"] = [name for name in ("speaker_a", "speaker_b", "speaker_c") if name in names]
            prev["confidence"] = round(max(prev["confidence"], region["confidence"]), 3)
            continue
        merged.append(dict(region))
    regions = [row for row in merged if row["duration"] >= 2.5]
    payload = {
        "kind": "cfs_overlap_v3",
        "source_video": "data/inbox/Edited.mp4",
        "timeline": "Edited.mp4",
        "raw_source_timestamps_used": False,
        "floor_timeline": "data/speakers/Edited.turns_v3.json",
        "floor_timeline_modified": False,
        "learned_on": "DIRECTABLE_PROGRAM only",
        "method": "tight_lip_jaw_motion_plus_mixed_audio",
        "does_not_rewrite_speaker_identity": True,
        "overlap_count": len(regions),
        "overlap_duration_s": round(sum(r["duration"] for r in regions), 3),
        "meta": meta,
        "regions": regions,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("overlaps", len(regions), "duration", payload["overlap_duration_s"], flush=True)
    print("OVERLAP_DONE", flush=True)


if __name__ == "__main__":
    main()
