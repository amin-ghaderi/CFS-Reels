"""Shot plan for 00:49:20-00:59:20 from the diarized turn timeline.

Does not render. Does not read or write the old speaker block files.
Does not modify turns_v3 or the word timestamps.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_offline_multicam_16x9 import filter_for, shot_type
from reels_factory.cfs_offline_verify import open_verifier, verify_boundary
from reels_factory.utils import parse_timestamp, ts

ORIGIN = 2960.0
END = 3560.0
# A named turn takes the floor when it is more than a one-word flicker.
MIN_DUR = 2.0
MIN_WORDS = 4
# A one-word unknown holds the current camera. A long stretch with no words does not.
LONG_WORDLESS = 12.0
NAMED = {"speaker_a", "speaker_b", "speaker_c"}
SOURCE = ROOT / "data/inbox/03.mp4"
TURNS_PATH = ROOT / "data/speakers/CFS03_49-59_turns_v3.json"
WORDS_PATH = ROOT / "data/speakers/CFS03_49-59_words_with_speakers.json"

# Previously reviewed listens. Used only while that person still owns the floor.
# They are not new floor decisions.
REACTIONS = [
    (parse_timestamp("00:50:08.140"), parse_timestamp("00:50:16.140"), "speaker_b", "speaker_a",
     "B smiles with his eyes closed while A is still the diarized speaker."),
    (parse_timestamp("00:52:36.140"), parse_timestamp("00:52:43.440"), "speaker_a", "speaker_b",
     "A's arms are raised and his mouth is closed. B's question continues."),
    (parse_timestamp("00:54:08.040"), parse_timestamp("00:54:14.160"), "speaker_b", "speaker_a",
     "B smiles while A is speaking. The cut returns at C's turn, not at the old reaction end."),
    (parse_timestamp("00:56:36.240"), parse_timestamp("00:56:44.040"), "speaker_b", "speaker_a",
     "B's skeptical listen while A is the diarized speaker."),
    (parse_timestamp("00:57:22.060"), parse_timestamp("00:57:30.280"), "speaker_b", "speaker_a",
     "B's finger is at his temple while A is speaking."),
    (parse_timestamp("00:57:48.320"), parse_timestamp("00:57:53.080"), "speaker_b", "speaker_a",
     "B's skeptical listen. B's own turn begins at the end of this listen, so the camera stays."),
]

# The simple_v1 edit, kept here only so this plan can be compared with it.
SIMPLE_V1 = [
    (parse_timestamp("00:49:20.000"), parse_timestamp("00:50:08.140"), "FULL_A"),
    (parse_timestamp("00:50:08.140"), parse_timestamp("00:50:16.140"), "FULL_B"),
    (parse_timestamp("00:50:16.140"), parse_timestamp("00:51:46.200"), "FULL_A"),
    (parse_timestamp("00:51:46.200"), parse_timestamp("00:51:56.180"), "ORIGINAL_WIDE"),
    (parse_timestamp("00:51:56.180"), parse_timestamp("00:52:24.140"), "FULL_A"),
    (parse_timestamp("00:52:24.140"), parse_timestamp("00:52:36.140"), "FULL_B"),
    (parse_timestamp("00:52:36.140"), parse_timestamp("00:52:43.440"), "FULL_A"),
    (parse_timestamp("00:52:43.440"), parse_timestamp("00:52:52.040"), "FULL_B"),
    (parse_timestamp("00:52:52.040"), parse_timestamp("00:53:07.160"), "ORIGINAL_WIDE"),
    (parse_timestamp("00:53:07.160"), parse_timestamp("00:54:08.040"), "FULL_A"),
    (parse_timestamp("00:54:08.040"), parse_timestamp("00:54:16.160"), "FULL_B"),
    (parse_timestamp("00:54:16.160"), parse_timestamp("00:54:26.000"), "FULL_A"),
    (parse_timestamp("00:54:26.000"), parse_timestamp("00:54:40.000"), "ORIGINAL_WIDE"),
    (parse_timestamp("00:54:40.000"), parse_timestamp("00:55:38.300"), "FULL_A"),
    (parse_timestamp("00:55:38.300"), parse_timestamp("00:55:46.240"), "FULL_B"),
    (parse_timestamp("00:55:46.240"), parse_timestamp("00:56:02.640"), "FULL_A"),
    (parse_timestamp("00:56:02.640"), parse_timestamp("00:56:08.940"), "FULL_C"),
    (parse_timestamp("00:56:08.940"), parse_timestamp("00:56:36.240"), "FULL_A"),
    (parse_timestamp("00:56:36.240"), parse_timestamp("00:56:44.040"), "FULL_B"),
    (parse_timestamp("00:56:44.040"), parse_timestamp("00:57:22.060"), "FULL_A"),
    (parse_timestamp("00:57:22.060"), parse_timestamp("00:57:30.280"), "FULL_B"),
    (parse_timestamp("00:57:30.280"), parse_timestamp("00:57:48.320"), "FULL_A"),
    (parse_timestamp("00:57:48.320"), parse_timestamp("00:57:55.980"), "FULL_B"),
    (parse_timestamp("00:57:55.980"), parse_timestamp("00:58:36.220"), "FULL_A"),
    (parse_timestamp("00:58:36.220"), parse_timestamp("00:58:59.580"), "ORIGINAL_WIDE"),
    (parse_timestamp("00:58:59.580"), parse_timestamp("00:59:20.000"), "FULL_C"),
]
PROBES = [
    "00:51:08.000", "00:51:10.000", "00:51:12.000", "00:51:20.000",
    "00:51:24.000", "00:51:28.000", "00:51:32.000", "00:51:48.000", "00:51:50.000",
]


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


def build_floors(turns: list[dict], words: list[dict]) -> tuple[list[dict], dict]:
    kept = [turn for turn in turns if meaningful(turn)]
    ignored_unknown = [turn for turn in turns if turn["speaker"] == "unknown"]
    ignored_tiny = [turn for turn in turns if turn["speaker"] in NAMED and not meaningful(turn)]
    floors = []
    cursor = ORIGIN
    speaker = kept[0]["speaker"]
    ids = [kept[0]["turn_id"]]

    def close(at: float) -> None:
        nonlocal cursor, ids
        if at - cursor >= 0.02:
            floors.append({
                "start": cursor,
                "end": at,
                "speaker": speaker,
                "kind": "floor",
                "turn_ids": list(ids),
            })
        cursor = at
        ids = []

    for prev, turn in zip(kept, kept[1:]):
        gaps = wordless_gaps(float(prev["end"]), float(turn["start"]), words)
        if turn["speaker"] == speaker and not gaps:
            ids.append(turn["turn_id"])
            continue
        if gaps:
            gap_start, gap_end = gaps[0]
            ids.append(prev["turn_id"]) if prev["turn_id"] not in ids else None
            close(gap_start)
            floors.append({
                "start": gap_start,
                "end": gap_end,
                "speaker": None,
                "kind": "long_unknown",
                "turn_ids": [],
            })
            cursor = gap_end
            if turn["speaker"] != speaker:
                if turn["start"] - cursor >= 0.02:
                    floors.append({
                        "start": cursor,
                        "end": float(turn["start"]),
                        "speaker": speaker,
                        "kind": "floor",
                        "turn_ids": [],
                    })
                cursor = float(turn["start"])
                speaker = turn["speaker"]
                ids = [turn["turn_id"]]
            else:
                speaker = turn["speaker"]
                ids = [turn["turn_id"]]
            continue
        close(float(turn["start"]))
        speaker = turn["speaker"]
        ids = [turn["turn_id"]]
    close(END)
    stats = {
        "diarized_turns": len(turns),
        "meaningful_turns_used": len(kept),
        "tiny_or_backchannel_ignored": len(ignored_tiny),
        "unknown_boundary_turns_ignored": len(ignored_unknown),
        "meaningful_turn_ids": [turn["turn_id"] for turn in kept],
        "ignored_tiny_ids": [turn["turn_id"] for turn in ignored_tiny],
        "ignored_unknown_ids": [turn["turn_id"] for turn in ignored_unknown],
    }
    return floors, stats


def piece(start: float, end: float, dominant: str | None, active: str | None, reason: str, note: str) -> dict:
    comp = "original_wide" if dominant is None else "full"
    shot = {
        "start": ts(start),
        "end": ts(end),
        "duration_s": round(end - start, 3),
        "composition": comp,
        "dominant": active if dominant is None else dominant,
        "secondary": [],
        "active_speaker": active,
        "resolved_speaker": active,
        "visual_override": False,
        "other_visible_speakers": [],
        "reason": reason,
        "note": note,
        "_start": start,
        "_end": end,
    }
    if dominant is None:
        shot["dominant"] = active
        shot["composition"] = "original_wide"
    shot["shot_type"] = shot_type(shot)
    return shot


def floors_to_shots(floors: list[dict]) -> list[dict]:
    shots = []
    for floor in floors:
        if floor["kind"] == "long_unknown":
            shots.append(piece(
                floor["start"], floor["end"], None, None, "unknown_hold",
                "No words for more than 12 seconds. A one-word unknown would hold the current camera. This gap is long, so the original frame holds until the next named turn.",
            ))
            continue
        who = floor["speaker"]
        label = who.replace("speaker_", "").upper()
        ids = ", ".join(floor["turn_ids"])
        shots.append(piece(
            floor["start"], floor["end"], who, who, "active_speaker",
            f"Diarized floor is {who}. FULL_{label}. Turns {ids}. One-word unknowns and turns under 2 seconds do not take the camera.",
        ))
    return shots


def insert_reactions(shots: list[dict]) -> tuple[list[dict], list[str]]:
    skipped = []
    for start, end, face, owner, note in REACTIONS:
        host = None
        for shot in shots:
            if shot["reason"] != "active_speaker" or shot["active_speaker"] != owner:
                continue
            if shot["_start"] - 0.02 <= start < shot["_end"] - 0.02:
                host = shot
                break
        if host is None:
            skipped.append(f"{ts(start)} no {owner} floor")
            continue
        cut_end = min(end, host["_end"])
        if cut_end - start < 2.0 or start - host["_start"] < 2.0:
            skipped.append(f"{ts(start)} would leave a stub")
            continue
        if host["_end"] - cut_end < 2.0 and host["_end"] - cut_end >= 0.05:
            # The remainder of this floor is too short to be its own shot.
            # Keep the reaction only when the next floor is a different camera.
            skipped.append(f"{ts(start)} remainder under 2s")
            continue
        before = piece(host["_start"], start, owner, owner, "active_speaker", host["note"])
        reaction = piece(start, cut_end, face, owner, "reaction", note)
        after = []
        if host["_end"] - cut_end >= 0.05:
            after_shot = piece(cut_end, host["_end"], owner, owner, "active_speaker", host["note"])
            after = [after_shot]
        idx = shots.index(host)
        shots = shots[:idx] + [before, reaction] + after + shots[idx + 1:]
    return shots, skipped


def merge_same_camera(shots: list[dict]) -> list[dict]:
    merged = []
    for shot in shots:
        prev = merged[-1] if merged else None
        same = (
            prev is not None
            and prev["shot_type"] == shot["shot_type"]
            and prev["dominant"] == shot["dominant"]
            and abs(parse_timestamp(prev["end"]) - parse_timestamp(shot["start"])) < 0.05
        )
        if not same:
            merged.append(shot)
            continue
        prev["end"] = shot["end"]
        prev["_end"] = shot["_end"]
        prev["duration_s"] = round(prev["_end"] - prev["_start"], 3)
        prev["note"] = prev["note"] + " " + shot["note"]
        if shot["reason"] == "active_speaker":
            prev["reason"] = "active_speaker"
            prev["active_speaker"] = shot["active_speaker"]
            prev["resolved_speaker"] = shot["active_speaker"]
    return merged


def camera_at(shots, stamp: str) -> str:
    t = parse_timestamp(stamp)
    for shot in shots:
        start = shot["_start"] if "_start" in shot else parse_timestamp(shot[0] if isinstance(shot, tuple) else shot["start"])
        end = shot["_end"] if "_end" in shot else parse_timestamp(shot[1] if isinstance(shot, tuple) else shot["end"])
        label = shot["shot_type"] if isinstance(shot, dict) else shot[2]
        if start <= t < end or (abs(t - END) < 0.001 and abs(end - END) < 0.001):
            return label
    return "none"


def simple_at(stamp: str) -> str:
    t = parse_timestamp(stamp)
    for start, end, label in SIMPLE_V1:
        if start <= t < end or (abs(t - END) < 0.001 and abs(end - END) < 0.001):
            return label
    return "none"


def main() -> None:
    turns = json.loads(TURNS_PATH.read_text(encoding="utf-8"))["turns"]
    words = json.loads(WORDS_PATH.read_text(encoding="utf-8"))["words"]
    floors, stats = build_floors(turns, words)
    shots = floors_to_shots(floors)
    shots, skipped_reactions = insert_reactions(shots)
    shots = merge_same_camera(shots)

    problems = []
    for i, shot in enumerate(shots):
        if shot["duration_s"] < 2:
            problems.append(f"short {shot['duration_s']} at {shot['start']}")
        if i and shot["start"] != shots[i - 1]["end"]:
            problems.append(f"gap/overlap at {shot['start']}")
        filt = filter_for(shot)
        if shot["shot_type"] == "ORIGINAL_WIDE":
            if any(token in filt for token in ("crop", "scale", "gblur", "overlay")):
                problems.append(f"wide filter at {shot['start']}")
        elif "crop=" not in filt or "scale=1920:1080" not in filt:
            problems.append(f"full filter at {shot['start']}")
    if shots[0]["start"] != "00:49:20.000" or shots[-1]["end"] != "00:59:20.000":
        problems.append("range")
    total = round(sum(shot["duration_s"] for shot in shots), 3)
    if abs(total - 600.0) > 0.05:
        problems.append(f"duration {total}")

    print("verify floor changes", flush=True)
    cap, detector = open_verifier(SOURCE)
    qa_floors = []
    try:
        previous = None
        for shot in shots:
            if shot["reason"] != "active_speaker" or shot["active_speaker"] not in NAMED:
                previous = shot["active_speaker"]
                continue
            if shot["active_speaker"] == previous:
                continue
            boundary = shot["_start"]
            if boundary <= ORIGIN + 0.05:
                previous = shot["active_speaker"]
                qa_floors.append({
                    "turn_start": shot["start"],
                    "turn_end": shot["end"],
                    "diarized_speaker": shot["active_speaker"],
                    "selected_camera": shot["shot_type"],
                    "visual_check": "opening hold, no incoming boundary",
                })
                continue
            verdict = verify_boundary(cap, detector, boundary, shot["active_speaker"])
            mouth = verdict.get("mouth_activity") or {}
            contradicted = bool(verdict.get("visual_override"))
            qa_floors.append({
                "turn_start": shot["start"],
                "turn_end": shot["end"],
                "diarized_speaker": shot["active_speaker"],
                "selected_camera": shot["shot_type"],
                "visual_override_applied": False,
                "visual_contradiction_logged": contradicted,
                "mouth_activity_a": mouth.get("speaker_a"),
                "mouth_activity_b": mouth.get("speaker_b"),
                "mouth_activity_c": mouth.get("speaker_c"),
                "visual_note": verdict.get("reason"),
            })
            if contradicted:
                print("contradiction", shot["start"], shot["active_speaker"], mouth, flush=True)
            previous = shot["active_speaker"]
    finally:
        cap.release()

    for shot in shots:
        shot.pop("_start", None)
        shot.pop("_end", None)

    counts = Counter(shot["shot_type"] for shot in shots)
    reactions = [shot for shot in shots if shot["reason"] == "reaction"]
    durs = [shot["duration_s"] for shot in shots]
    probes = []
    for stamp in PROBES:
        now = camera_at(shots, stamp)
        old = simple_at(stamp)
        probes.append({
            "time": stamp,
            "simple_v1": old,
            "diarized_turns_v1": now,
            "changed": now != old,
        })

    plan = {
        "kind": "cfs_multicam_16x9_offline_plan",
        "workflow": "cfs_multicam_16x9",
        "role": "roles/virtual_director.md",
        "mode": "offline_editor",
        "visual_language": "FULL_A FULL_B FULL_C ORIGINAL_WIDE",
        "visual_gate": "reels_factory/cfs_offline_verify.py",
        "visual_gate_role": "secondary QA on diarized floor changes; it does not replace the turn timeline",
        "precomputed_before_render": True,
        "speaker_timeline": "data/speakers/CFS03_49-59_turns_v3.json",
        "word_timeline": "data/speakers/CFS03_49-59_words_with_speakers.json",
        "speaker_timeline_modified": False,
        "old_speaker_blocks_used": False,
        "source_video_on_disk": "data/inbox/03.mp4",
        "compared_with": "data/director_tests/CFS03_49-59_offline_multicam_16x9_simple_v1.mp4",
        "selected_range": {"start": "00:49:20.000", "end": "00:59:20.000", "duration_s": 600.0},
        "floor_rule": "A named turn changes the camera when it lasts at least 2.0s and has at least 4 words. Unknown and shorter turns do not. The same speaker on both sides of an unknown stays one floor. Different speakers stay split.",
        "overlap_note": "The diarizer assigns one speaker per window. ORIGINAL_WIDE is used for a long stretch with no words, not because an overlap label was present.",
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
            "two_person_composites": 0,
            "three_person_composites": 0,
            "reaction_shots": len(reactions),
            "camera_edits": len(shots) - 1,
            "average_shot_duration_s": round(sum(durs) / len(durs), 3),
            "longest_shot_s": max(durs),
            "shot_count": len(shots),
            "diarized_turns": stats["diarized_turns"],
            "meaningful_turns_used": stats["meaningful_turns_used"],
            "tiny_or_backchannel_ignored": stats["tiny_or_backchannel_ignored"],
            "unknown_boundary_turns_ignored": stats["unknown_boundary_turns_ignored"],
        },
    }
    qa = {
        "kind": "cfs_multicam_16x9_offline_qa",
        "range": "00:49:20.000-00:59:20.000",
        "speaker_timeline": "data/speakers/CFS03_49-59_turns_v3.json",
        "old_speaker_blocks_used": False,
        "visual_gate": "reels_factory/cfs_offline_verify.py",
        "reviewed_before_render": True,
        "plan_computed_before_render": True,
        "compared_with": "data/director_tests/CFS03_49-59_offline_multicam_16x9_simple_v1.mp4",
        "floor_changes": qa_floors,
        "turn_filter": stats,
        "reaction_shots": [f"{shot['start']} {shot['shot_type']} while {shot['active_speaker']}" for shot in reactions],
        "reactions_not_inserted": skipped_reactions,
        "original_wide": [
            {"start": shot["start"], "end": shot["end"], "duration_s": shot["duration_s"], "reason": shot["note"]}
            for shot in shots if shot["shot_type"] == "ORIGINAL_WIDE"
        ],
        "long_shots_over_12s": [
            {"start": shot["start"], "end": shot["end"], "duration_s": shot["duration_s"], "shot_type": shot["shot_type"]}
            for shot in shots if shot["duration_s"] > 12
        ],
        "probe_vs_simple_v1": probes,
        "problems": problems,
    }
    plan_path = ROOT / "data/director_tests/CFS03_49-59_diarized_turns_v1_plan.json"
    qa_path = ROOT / "data/director_tests/CFS03_49-59_diarized_turns_v1_qa.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print("problems", problems)
    print("summary", json.dumps(plan["summary"]))
    print("skipped", skipped_reactions)
    for row in probes:
        print(row["time"], row["simple_v1"], "->", row["diarized_turns_v1"], "changed" if row["changed"] else "same")
    for shot in shots:
        print(shot["start"], shot["end"], shot["shot_type"], shot["reason"], shot["duration_s"])


if __name__ == "__main__":
    main()
