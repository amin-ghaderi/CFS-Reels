"""Shot plan for 00:49:20-00:59:20 using turns_v3 plus an overlap layer.

Does not rewrite turns, word speakers, or the previous diarized render.
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_offline_multicam_16x9 import filter_for, shot_type
from reels_factory.utils import parse_timestamp, ts

_spec = importlib.util.spec_from_file_location(
    "diarized_plan",
    ROOT / "data/tmp_cfs03_preview/build_offline_49_59_diarized_turns_v1_plan.py",
)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

ORIGIN = base.ORIGIN
END = base.END
NAMED = base.NAMED


def snap_edge(t: float, words: list[dict], *, toward: str) -> float:
    """Move a cut onto a nearby word edge so the wide shot does not start late."""
    for word in words:
        start = float(word["start"])
        end = float(word["end"])
        if start <= t <= end:
            if toward == "start" and 0 <= t - start <= 0.40:
                return start
            if toward == "end" and 0 <= end - t <= 0.40:
                return end
            return t
    return t


def prepare_overlaps(raw: list[dict], words: list[dict]) -> list[dict]:
    prepared = []
    for row in raw:
        if row.get("kind", "overlap") not in {"overlap", "group_reaction"}:
            continue
        start = max(ORIGIN, snap_edge(float(row["start"]), words, toward="start"))
        end = min(END, snap_edge(float(row["end"]), words, toward="end"))
        if end - start < 1.0:
            continue
        item = dict(row)
        item["shot_start"] = start
        item["shot_end"] = end
        prepared.append(item)
    prepared.sort(key=lambda row: row["shot_start"])
    merged = []
    for row in prepared:
        if merged and row["shot_start"] - merged[-1]["shot_end"] <= 0.75:
            prev = merged[-1]
            prev["shot_end"] = max(prev["shot_end"], row["shot_end"])
            names = list(dict.fromkeys(prev["speakers_active"] + row["speakers_active"]))
            prev["speakers_active"] = [name for name in ("speaker_a", "speaker_b", "speaker_c") if name in names]
            if prev.get("kind") != row.get("kind"):
                prev["kind"] = "overlap"
            continue
        merged.append(row)
    return merged


def overlay(shots: list[dict], overlaps: list[dict]) -> list[dict]:
    cuts = {ORIGIN, END}
    for shot in shots:
        cuts.add(shot["_start"])
        cuts.add(shot["_end"])
    for row in overlaps:
        cuts.add(row["shot_start"])
        cuts.add(row["shot_end"])
    bounds = sorted(cuts)
    out = []
    for left, right in zip(bounds, bounds[1:]):
        if right - left < 0.03:
            continue
        mid = (left + right) / 2.0
        host = None
        for shot in shots:
            if shot["_start"] <= mid < shot["_end"] or (abs(mid - END) < 0.001 and abs(shot["_end"] - END) < 0.001):
                host = shot
                break
        if host is None:
            continue
        row = next((item for item in overlaps if item["shot_start"] <= mid < item["shot_end"]), None)
        if row is None:
            wide = host["shot_type"] == "ORIGINAL_WIDE"
            out.append(base.piece(
                left, right,
                None if wide else host["dominant"],
                host["active_speaker"],
                host["reason"],
                host["note"],
            ))
            continue
        owner = host["active_speaker"]
        kind = row.get("kind") or "overlap"
        reason = "group_reaction" if kind == "group_reaction" else "overlap"
        speakers = row["speakers_active"]
        others = [name for name in speakers if name != owner]
        note = (
            f"{reason} {ts(row['shot_start'])} to {ts(row['shot_end'])}: "
            f"{', '.join(speakers)}. Floor owner from turns_v3 is {owner}. "
            "Speaker labels are not changed."
        )
        shot = base.piece(left, right, None, owner, reason, note)
        shot["other_visible_speakers"] = others
        shot["secondary"] = others
        shot["overlap_confidence"] = row.get("confidence")
        out.append(shot)
    return _merge(out)


def _merge(shots: list[dict]) -> list[dict]:
    merged = []
    for shot in shots:
        prev = merged[-1] if merged else None
        same_picture = (
            prev is not None
            and prev["shot_type"] == "ORIGINAL_WIDE"
            and shot["shot_type"] == "ORIGINAL_WIDE"
            and abs(parse_timestamp(prev["end"]) - shot["_start"]) < 0.05
        )
        same = (
            prev is not None
            and prev["shot_type"] == shot["shot_type"]
            and prev["reason"] == shot["reason"]
            and prev["dominant"] == shot["dominant"]
            and abs(parse_timestamp(prev["end"]) - shot["_start"]) < 0.05
        )
        if not same and not same_picture:
            merged.append(shot)
            continue
        prev["end"] = shot["end"]
        prev["_end"] = shot["_end"]
        prev["duration_s"] = round(prev["_end"] - prev["_start"], 3)
        prev["note"] = prev["note"] + " " + shot["note"]
        extra = [name for name in shot.get("other_visible_speakers") or [] if name not in prev["other_visible_speakers"]]
        prev["other_visible_speakers"].extend(extra)
        prev["secondary"] = list(prev["other_visible_speakers"])
    return merged


def main() -> None:
    turns_path = ROOT / "data/speakers/CFS03_49-59_turns_v3.json"
    turns_mtime = turns_path.stat().st_mtime
    turns = json.loads(turns_path.read_text(encoding="utf-8"))["turns"]
    words = json.loads((ROOT / "data/speakers/CFS03_49-59_words_with_speakers.json").read_text(encoding="utf-8"))["words"]
    overlap_doc = json.loads((ROOT / "data/speakers/CFS03_49-59_overlaps_v3.json").read_text(encoding="utf-8"))
    floors, stats = base.build_floors(turns, words)
    shots = base.floors_to_shots(floors)
    overlaps = prepare_overlaps(overlap_doc["regions"], words)
    shots = overlay(shots, overlaps)
    shots, skipped = base.insert_reactions(shots)
    shots = _merge(shots)

    problems = []
    for i, shot in enumerate(shots):
        limit = 1.0 if shot["reason"] in {"overlap", "group_reaction"} else 2.0
        if shot["duration_s"] < limit:
            problems.append(f"short {shot['duration_s']} at {shot['start']}")
        if i and shot["start"] != shots[i - 1]["end"]:
            problems.append(f"gap at {shot['start']}")
        filt = filter_for(shot)
        if shot["shot_type"] == "ORIGINAL_WIDE":
            if any(token in filt for token in ("crop", "scale", "gblur", "overlay")):
                problems.append(f"wide filter at {shot['start']}")
        elif "crop=" not in filt or "scale=1920:1080" not in filt:
            problems.append(f"full filter at {shot['start']}")
        if shot["shot_type"] not in {"FULL_A", "FULL_B", "FULL_C", "ORIGINAL_WIDE"}:
            problems.append(f"banned {shot['shot_type']}")
    if shots[0]["start"] != "00:49:20.000" or shots[-1]["end"] != "00:59:20.000":
        problems.append("range")
    total = round(sum(shot["duration_s"] for shot in shots), 3)
    if abs(total - 600.0) > 0.05:
        problems.append(f"duration {total}")

    wides = []
    for shot in shots:
        if shot["shot_type"] != "ORIGINAL_WIDE":
            continue
        if shot["reason"] == "overlap":
            why = "OVERLAP"
        elif shot["reason"] == "group_reaction":
            why = "GROUP_REACTION"
        else:
            why = "OTHER_EXISTING_EDITORIAL_REASON"
        wides.append({
            "start": shot["start"],
            "end": shot["end"],
            "duration_s": shot["duration_s"],
            "reason": why,
            "floor_owner": shot["active_speaker"],
            "note": shot["note"],
        })

    timing = []
    for row in overlaps:
        wide = next((
            shot for shot in shots
            if shot["shot_type"] == "ORIGINAL_WIDE"
            and shot["_start"] <= row["shot_start"] + 0.2
            and shot["_end"] >= row["shot_end"] - 0.2
        ), None)
        if wide is None:
            timing.append({"overlap_start": ts(row["shot_start"]), "wide": None})
            continue
        wide_start = parse_timestamp(wide["start"])
        wide_end = parse_timestamp(wide["end"])
        nxt = next((shot for shot in shots if shot["_start"] >= wide_end - 0.02), None)
        timing.append({
            "overlap_detected_start": ts(float(row["start"])),
            "overlap_detected_end": ts(float(row["end"])),
            "wide_start": wide["start"],
            "wide_end": wide["end"],
            "wide_begins_after_overlap_s": round(wide_start - float(row["start"]), 3),
            "returns_to": None if nxt is None else nxt["shot_type"],
            "return_after_overlap_end_s": None if nxt is None else round(nxt["_start"] - float(row["end"]), 3),
            "floor_owner_after": None if nxt is None else nxt["active_speaker"],
        })

    probes = ["00:51:08.000", "00:51:10.000", "00:51:20.000", "00:51:48.000", "00:51:50.000", "00:52:30.000", "00:53:20.000"]
    probe_rows = []
    for stamp in probes:
        probe_rows.append({"time": stamp, "camera": base.camera_at(shots, stamp)})

    for shot in shots:
        shot.pop("_start", None)
        shot.pop("_end", None)

    counts = Counter(shot["shot_type"] for shot in shots)
    reactions = [shot for shot in shots if shot["reason"] == "reaction"]
    durs = [shot["duration_s"] for shot in shots]
    plan = {
        "kind": "cfs_multicam_16x9_offline_plan",
        "workflow": "cfs_multicam_16x9",
        "role": "roles/virtual_director.md",
        "mode": "offline_editor",
        "visual_language": "FULL_A FULL_B FULL_C ORIGINAL_WIDE",
        "precomputed_before_render": True,
        "speaker_timeline": "data/speakers/CFS03_49-59_turns_v3.json",
        "overlap_timeline": "data/speakers/CFS03_49-59_overlaps_v3.json",
        "speaker_timeline_modified": False,
        "old_speaker_blocks_used": False,
        "source_video_on_disk": "data/inbox/03.mp4",
        "compared_with": "data/director_tests/CFS03_49-59_diarized_turns_v1.mp4",
        "selected_range": {"start": "00:49:20.000", "end": "00:59:20.000", "duration_s": 600.0},
        "camera_priority": [
            "meaningful overlap -> ORIGINAL_WIDE",
            "otherwise meaningful named turn -> FULL_A / FULL_B / FULL_C",
            "short unknown -> hold",
        ],
        "tiles": {
            "speaker_a": {"x": 52, "y": 24, "w": 896, "h": 504},
            "speaker_b": {"x": 972, "y": 24, "w": 896, "h": 504},
            "speaker_c": {"x": 512, "y": 552, "w": 896, "h": 504},
        },
        "scale": "FULL shots: complete 896x504 tile scaled to 1920x1080, lanczos, no extra crop, no pad. ORIGINAL_WIDE: untouched full source frame, no crop, no scale, no blur, no overlay.",
        "transitions": "hard_cut",
        "audio": "original synchronized program audio, unchanged by camera choice",
        "shots": shots,
        "summary": {
            "FULL_A": counts["FULL_A"],
            "FULL_B": counts["FULL_B"],
            "FULL_C": counts["FULL_C"],
            "ORIGINAL_WIDE": counts["ORIGINAL_WIDE"],
            "reaction_shots": len(reactions),
            "camera_edits": len(shots) - 1,
            "average_shot_duration_s": round(sum(durs) / len(durs), 3) if durs else 0,
            "longest_shot_s": max(durs) if durs else 0,
            "shot_count": len(shots),
            "overlap_regions": len(overlap_doc["regions"]),
            "overlap_duration_s": overlap_doc["overlap_duration_s"],
        },
    }
    qa = {
        "kind": "cfs_multicam_16x9_offline_qa",
        "range": "00:49:20.000-00:59:20.000",
        "speaker_timeline": "data/speakers/CFS03_49-59_turns_v3.json",
        "speaker_timeline_modified": turns_path.stat().st_mtime != turns_mtime,
        "overlap_timeline": "data/speakers/CFS03_49-59_overlaps_v3.json",
        "turn_filter": stats,
        "overlaps": overlap_doc["regions"],
        "original_wide": wides,
        "wide_timing_vs_overlap": timing,
        "probes": probe_rows,
        "reactions_not_inserted": skipped,
        "problems": problems,
        "group_reaction_shots": [row for row in wides if row["reason"] == "GROUP_REACTION"],
    }
    plan_path = ROOT / "data/director_tests/CFS03_49-59_diarized_overlap_v1_plan.json"
    qa_path = ROOT / "data/director_tests/CFS03_49-59_diarized_overlap_v1_qa.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print("problems", problems)
    print("summary", json.dumps(plan["summary"]))
    print("wides", json.dumps(wides, ensure_ascii=False))
    print("timing", json.dumps(timing, ensure_ascii=False))
    print("probes", probe_rows)
    print("turns_mtime_unchanged", turns_path.stat().st_mtime == turns_mtime)


if __name__ == "__main__":
    main()
