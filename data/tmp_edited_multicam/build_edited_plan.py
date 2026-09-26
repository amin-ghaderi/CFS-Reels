"""Shot plan for Edited.mp4.

Floor and overlap rules match the 49-59 diarized overlap test.
Protected master intervals override every camera decision.
No reaction inserts. No timestamps from 03.mp4.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_offline_multicam_16x9 import filter_for
from reels_factory.utils import ts

MIN_DUR = 2.0
MIN_WORDS = 4
LONG_WORDLESS = 12.0
NAMED = {"speaker_a", "speaker_b", "speaker_c"}
PLAN = ROOT / "data" / "director_tests" / "Edited_multicam_v1_plan.json"
QA = ROOT / "data" / "director_tests" / "Edited_multicam_v1_qa.json"


def meaningful(turn: dict) -> bool:
    return (
        turn["speaker"] in NAMED
        and float(turn["duration_s"]) >= MIN_DUR
        and int(turn["word_count"]) >= MIN_WORDS
    )


def wordless_gaps(start: float, end: float, words: list[dict]) -> list[tuple[float, float]]:
    cursor = start
    gaps = []
    for word in words:
        if float(word["end"]) <= start or float(word["start"]) >= end:
            continue
        if float(word["start"]) - cursor >= LONG_WORDLESS:
            gaps.append((cursor, float(word["start"])))
        cursor = max(cursor, float(word["end"]))
    if end - cursor >= LONG_WORDLESS:
        gaps.append((cursor, end))
    return gaps


def piece(start: float, end: float, presentation: str, reason: str, note: str, active: str | None) -> dict:
    dominant = None if presentation in {"ORIGINAL_WIDE", "PROTECTED_MASTER"} else active
    shot = {
        "start": ts(start),
        "end": ts(end),
        "duration_s": round(end - start, 3),
        "presentation": presentation,
        "shot_type": presentation,
        "reason": reason,
        "note": note,
        "active_speaker": active,
        "dominant": dominant if dominant else active,
        "composition": "original_wide" if presentation in {"ORIGINAL_WIDE", "PROTECTED_MASTER"} else "full",
        "secondary": [],
        "other_visible_speakers": [],
        "visual_override": False,
        "_start": round(start, 3),
        "_end": round(end, 3),
    }
    return shot


def floors_for_span(origin: float, end: float, turns: list[dict], words: list[dict]) -> list[dict]:
    kept = [
        turn for turn in turns
        if meaningful(turn) and float(turn["end"]) > origin and float(turn["start"]) < end
    ]
    if not kept:
        return [piece(
            origin, end, "ORIGINAL_WIDE", "unknown_hold",
            "No meaningful named turn in this program span.",
            None,
        )]
    shots = []
    cursor = origin
    speaker = kept[0]["speaker"]
    ids = [kept[0]["turn_id"]]

    def close(at: float) -> None:
        nonlocal cursor, ids
        at = min(end, max(cursor, at))
        if at - cursor >= 0.02:
            label = "FULL_" + speaker[-1].upper()
            shots.append(piece(
                cursor, at, label, "active_speaker",
                f"Diarized floor is {speaker}. Turns {', '.join(ids)}.",
                speaker,
            ))
        cursor = at
        ids = []

    for prev, turn in zip(kept, kept[1:]):
        gap_lo = max(origin, float(prev["end"]))
        gap_hi = min(end, float(turn["start"]))
        gaps = wordless_gaps(gap_lo, gap_hi, words) if gap_hi - gap_lo >= LONG_WORDLESS else []
        if turn["speaker"] == speaker and not gaps:
            ids.append(turn["turn_id"])
            continue
        if gaps:
            gap_start, gap_end = gaps[0]
            gap_start = max(origin, gap_start)
            gap_end = min(end, gap_end)
            if prev["turn_id"] not in ids:
                ids.append(prev["turn_id"])
            close(gap_start)
            if gap_end - cursor >= 0.02:
                shots.append(piece(
                    cursor, gap_end, "ORIGINAL_WIDE", "unknown_hold",
                    "No words for more than 12 seconds inside program footage.",
                    None,
                ))
                cursor = gap_end
            speaker = turn["speaker"]
            ids = [turn["turn_id"]]
            continue
        cut = min(end, max(origin, float(turn["start"])))
        close(cut)
        speaker = turn["speaker"]
        ids = [turn["turn_id"]]
    close(end)
    return [shot for shot in shots if shot["_end"] - shot["_start"] >= 0.02]


def snap_edge(t: float, words: list[dict], *, toward: str, lo: float, hi: float) -> float:
    for word in words:
        start = float(word["start"])
        end = float(word["end"])
        if start <= t <= end:
            if toward == "start" and 0 <= t - start <= 0.40 and start >= lo:
                return start
            if toward == "end" and 0 <= end - t <= 0.40 and end <= hi:
                return end
            return t
    return t


def apply_overlaps(shots: list[dict], overlaps: list[dict], words: list[dict], lo: float, hi: float) -> list[dict]:
    prepared = []
    for row in overlaps:
        if float(row["end"]) <= lo or float(row["start"]) >= hi:
            continue
        start = snap_edge(max(lo, float(row["start"])), words, toward="start", lo=lo, hi=hi)
        end = snap_edge(min(hi, float(row["end"])), words, toward="end", lo=lo, hi=hi)
        start = max(lo, start)
        end = min(hi, end)
        if end - start < 1.0:
            continue
        item = dict(row)
        item["shot_start"] = start
        item["shot_end"] = end
        prepared.append(item)
    if not prepared:
        return shots
    cuts = {lo, hi}
    for shot in shots:
        cuts.add(shot["_start"])
        cuts.add(shot["_end"])
    for row in prepared:
        cuts.add(row["shot_start"])
        cuts.add(row["shot_end"])
    bounds = sorted(cuts)
    out = []
    for left, right in zip(bounds, bounds[1:]):
        if right - left < 0.03:
            continue
        mid = (left + right) / 2.0
        host = next((shot for shot in shots if shot["_start"] <= mid < shot["_end"] or abs(shot["_end"] - hi) < 0.001 and abs(mid - hi) < 0.001), None)
        if host is None:
            continue
        row = next((item for item in prepared if item["shot_start"] <= mid < item["shot_end"]), None)
        if row is None:
            cloned = dict(host)
            cloned["_start"] = round(left, 3)
            cloned["_end"] = round(right, 3)
            cloned["start"] = ts(left)
            cloned["end"] = ts(right)
            cloned["duration_s"] = round(right - left, 3)
            out.append(cloned)
            continue
        owner = host["active_speaker"]
        speakers = row["speakers_active"]
        shot = piece(
            left, right, "ORIGINAL_WIDE", "overlap",
            f"Overlap {', '.join(speakers)}. Floor owner remains {owner}.",
            owner,
        )
        shot["other_visible_speakers"] = [name for name in speakers if name != owner]
        shot["overlap_confidence"] = row.get("confidence")
        out.append(shot)
    return out


def merge_same(shots: list[dict]) -> list[dict]:
    merged = []
    for shot in shots:
        prev = merged[-1] if merged else None
        same = (
            prev is not None
            and prev["presentation"] == shot["presentation"]
            and prev["reason"] == shot["reason"]
            and prev["active_speaker"] == shot["active_speaker"]
            and abs(prev["_end"] - shot["_start"]) < 0.05
        )
        if not same:
            merged.append(shot)
            continue
        prev["_end"] = shot["_end"]
        prev["end"] = shot["end"]
        prev["duration_s"] = round(prev["_end"] - prev["_start"], 3)
        prev["note"] = prev["note"] + " " + shot["note"]
    return merged


def main() -> None:
    edit = json.loads((ROOT / "data/director_tests/Edited_editability_map.json").read_text(encoding="utf-8"))
    turns_doc = json.loads((ROOT / "data/speakers/Edited.turns_v3.json").read_text(encoding="utf-8"))
    words = json.loads((ROOT / "data/speakers/Edited.words_with_speakers_v3.json").read_text(encoding="utf-8"))["words"]
    overlaps = json.loads((ROOT / "data/speakers/Edited.overlaps_v3.json").read_text(encoding="utf-8"))["regions"]
    turns = turns_doc["turns"]
    end = float(edit["duration_s"])
    shots = []
    for row in edit["protected"]:
        shots.append(piece(
            float(row["start"]), float(row["end"]), "PROTECTED_MASTER", row["reason"],
            "Edited master frame. Multicam is off.",
            None,
        ))
    for row in edit["directable"]:
        span = floors_for_span(float(row["start"]), float(row["end"]), turns, words)
        span = apply_overlaps(span, overlaps, words, float(row["start"]), float(row["end"]))
        shots.extend(span)
    shots.sort(key=lambda shot: shot["_start"])
    shots = merge_same(shots)
    problems = []
    if abs(shots[0]["_start"]) > 0.05 or abs(shots[-1]["_end"] - end) > 0.05:
        problems.append("range")
    for i, shot in enumerate(shots):
        if i and abs(shot["_start"] - shots[i - 1]["_end"]) > 0.05:
            problems.append(f"gap {shot['start']}")
        if shot["presentation"] not in {"PROTECTED_MASTER", "FULL_A", "FULL_B", "FULL_C", "ORIGINAL_WIDE"}:
            problems.append(f"bad {shot['presentation']}")
        if shot["presentation"] == "PROTECTED_MASTER":
            continue
        probe = dict(shot)
        if shot["presentation"] == "ORIGINAL_WIDE":
            probe["dominant"] = None
        filt = filter_for(probe)
        if shot["presentation"] == "ORIGINAL_WIDE" and any(tok in filt for tok in ("crop", "scale", "overlay")):
            problems.append(f"wide filter {shot['start']}")
        if shot["presentation"].startswith("FULL") and "crop=" not in filt:
            problems.append(f"full filter {shot['start']}")
    counts = Counter(shot["presentation"] for shot in shots)
    durations = {}
    for shot in shots:
        durations[shot["presentation"]] = round(durations.get(shot["presentation"], 0.0) + shot["duration_s"], 3)
    meaningful_n = sum(1 for turn in turns if meaningful(turn))
    public = []
    for shot in shots:
        row = {k: v for k, v in shot.items() if not k.startswith("_")}
        public.append(row)
    plan = {
        "kind": "edited_multicam_v1",
        "source_video": "data/inbox/Edited.mp4",
        "raw_source_timestamps_used": False,
        "old_speaker_artifacts_used": False,
        "reaction_shots": 0,
        "visual_language": ["PROTECTED_MASTER", "FULL_A", "FULL_B", "FULL_C", "ORIGINAL_WIDE"],
        "selected_range": {"start": "00:00:00.000", "end": ts(end), "duration_s": end},
        "speaker_timeline": "data/speakers/Edited.turns_v3.json",
        "overlap_timeline": "data/speakers/Edited.overlaps_v3.json",
        "editability_map": "data/director_tests/Edited_editability_map.json",
        "summary": {
            "shot_count": len(public),
            "camera_edits": max(0, len(public) - 1),
            "counts": dict(counts),
            "durations_s": durations,
            "diarized_turns": len(turns),
            "meaningful_turns_used": meaningful_n,
            "overlap_regions": len(overlaps),
        },
        "problems": problems,
        "shots": public,
    }
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    qa = {
        "source_video": "data/inbox/Edited.mp4",
        "source_duration_s": end,
        "raw_source_timestamps_used": False,
        "reaction_timestamps_reused": False,
        "turns_v3": "data/speakers/Edited.turns_v3.json",
        "protected": edit["protected"],
        "directable": edit["directable"],
        "summary": plan["summary"],
        "problems": problems,
        "checks": {
            "intro_protected": edit["protected"][0]["reason"] == "INTRO" and edit["protected"][0]["start"] == 0.0,
            "middle_text_protected": any(row["reason"] == "FULLSCREEN_TEXT" for row in edit["protected"]),
            "ending_protected": edit["protected"][-1]["reason"] == "ENDING",
            "directing_only_on_program": True,
        },
    }
    QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(plan["summary"], ensure_ascii=False), flush=True)
    print("problems", problems, flush=True)
    print("PLAN_DONE", flush=True)


if __name__ == "__main__":
    main()
