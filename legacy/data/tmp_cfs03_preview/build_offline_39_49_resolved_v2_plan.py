"""Precompute the 00:39:20-00:49:20 plan from the resolved speaker timeline.

Does not render. Does not write the previous multicam plan or QA.
"""
import json
from pathlib import Path

OLD = json.loads(
    Path("data/director_tests/CFS03_39-49_offline_multicam_16x9_plan.json").read_text(encoding="utf-8")
)
words = json.loads(Path("data/transcripts/CFS03.words.json").read_text(encoding="utf-8"))["words"]


def sec(ts: str) -> float:
    h, m, rest = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def ts(seconds: float) -> str:
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms == 1000:
        whole += 1
        ms = 0
    h, m, s = whole // 3600, (whole % 3600) // 60, whole % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def shot_type(comp, dom):
    if comp == "full":
        return {"speaker_a": "FULL_A", "speaker_b": "FULL_B", "speaker_c": "FULL_C"}[dom]
    return "TWO_PERSON_COMPOSITE" if comp == "two" else "THREE_PERSON_COMPOSITE"


def make(start, end, comp, dom, sec_list, reason, active, note):
    visible = []
    if comp == "two":
        visible = list(sec_list)
    elif comp == "three_balanced":
        visible = [s for s in sec_list if s != active]
    elif comp == "three_large":
        visible = list(sec_list)
    return {
        "start": ts(start),
        "end": ts(end),
        "duration_s": round(end - start, 3),
        "shot_type": shot_type(comp, dom),
        "composition": comp,
        "dominant": dom,
        "secondary": sec_list,
        "active_speaker": active,
        "other_visible_speakers": visible,
        "reason": reason,
        "note": note,
    }


# Index old shots by start timestamp.
by_start = {s["start"]: s for s in OLD["shots"]}


def keep(start_ts, **updates):
    shot = dict(by_start[start_ts])
    shot.update(updates)
    return shot


shots = []
shots.append(keep(
    "00:39:20.000",
    note="Window opens inside resolved speaker_a (B0157). Listeners at 2362 and 2376 are neutral, so the shot is not broken.",
))
shots.append(keep(
    "00:39:43.370",
    active_speaker="speaker_a",
    note="Resolved B0158 is speaker_a. The frame at 2386 is a shared laugh, A with a hand over his mouth, so the three-person shot stays. This is group laughter, not an unknown hold.",
))
shots.append(keep(
    "00:39:59.640",
    active_speaker="speaker_a",
    note="C's laugh is the clearest face once the group laugh is underway. Resolved speech through 2401 is still A, so this is a reaction, not a new speaker.",
))
shots.append(keep(
    "00:40:06.000",
    active_speaker="speaker_a",
    note="B's laugh peaks, hand on his forehead. The resolved A block has ended and there is no new speaker block, so the cut stays visual.",
))
shots.append(keep(
    "00:40:18.000",
    active_speaker="speaker_a",
    note="The laugh settles on all three before B's resolved line at 2430.",
))
shots.append(keep(
    "00:40:30.000",
    note="Resolved B0159 is speaker_b at 2430.000. C is in the same beat, so B is large rather than alone.",
))
shots.append(keep(
    "00:40:39.280",
    note="Resolved B0160 names speaker_b for the whole block. At 2440 and 2444 C is the open mouth and B is listening, so the opening is C. The old speaker_a label is not restored.",
))
shots.append(make(
    2448.160, 2463.460, "full", "speaker_b", [], "active_speaker", "speaker_b",
    "Resolved correction: B0160 was speaker_a at 0.50 and is now speaker_b. By 2450 B is speaking. The old three-person unknown and the early jump to A are not used.",
))
shots.append(make(
    2463.460, 2469.040, "two", "speaker_a", ["speaker_b"], "active_speaker", "speaker_a",
    "Frame at 2463 is A speaking. A is dominant from that word so his entrance is not missed. B's smile stays in the secondary tile.",
))
# Old FULL_A from 00:41:09.040 onward through the B reaction at 00:43:18, then skip the B reaction.
for start_ts in [
    "00:41:09.040", "00:41:35.940", "00:41:45.620", "00:41:54.540",
    "00:42:03.160", "00:42:12.620", "00:42:26.160", "00:42:36.080",
    "00:42:47.800", "00:42:51.840", "00:43:12.480",
]:
    shots.append(keep(start_ts))

shots.append(make(
    sec("00:43:18.000"), sec("00:43:37.620"), "full", "speaker_a", [], "active_speaker", "speaker_a",
    "Resolved B0165 is speaker_a from 2601.20 at 0.93. Mouth activity is A 7.39, B -0.24, C 0.82. The old FULL_B reaction from 2600 to 2603 is removed. At 2604 B has turned away.",
))
shots.append(keep(
    "00:43:37.620",
    note="B clasps his hands while A is still speaking. Resolved B0166 names speaker_b at 0.60, but the mouth leader is A (8.3 vs 6.3) and the frame at 2618 is A speaking. The clasped hands stay a reaction, not a floor change.",
))
for start_ts in [
    "00:43:43.800", "00:43:52.740", "00:43:59.920", "00:44:15.460",
    "00:44:20.240", "00:44:28.000", "00:44:40.240", "00:44:47.040",
    "00:45:02.700", "00:45:08.260", "00:45:21.080", "00:45:26.040",
    "00:45:35.100", "00:45:40.140", "00:45:55.770", "00:46:01.810",
    "00:46:24.220", "00:46:29.530", "00:46:47.510", "00:46:52.890",
    "00:47:02.830", "00:47:08.630",
]:
    shots.append(keep(start_ts))

shots.append(keep(
    "00:47:12.050",
    note="C is the open mouth from 2832. Resolved B0177 and B0178 are speaker_c. The old 0.50 speaker_a label was corrected to C and is not put back on camera.",
))
shots.append(keep(
    "00:47:26.530",
    note="B's question. Resolved B0178 still says C and B0180 later says A. At 2848 B is the open mouth, so the question is shown on B.",
))
shots.append(keep(
    "00:47:38.150",
    active_speaker="speaker_b",
    note="B looks away and C covers his mouth. Resolved B0179 says speaker_a. At 2868 A's hands are behind his head, so A is not shown as the speaker.",
))
shots.append(keep(
    "00:47:47.630",
    note="B and C are both in the exchange. The resolved speaker_a label is not used.",
))
shots.append(keep(
    "00:47:55.110",
    note="B's question at 2875.110. Resolved B0180 says speaker_a at 0.71. At 2878 B is speaking and A's hand is on his mouth, so the camera stays on B.",
))
shots.append(keep(
    "00:48:09.130",
    note="A receives the question, chin on his hand. B's audio continues. This is a reaction, not the resolved A label taking the floor.",
))
shots.append(keep("00:48:19.110"))
shots.append(keep(
    "00:48:30.250",
    note="C takes the answer at 2910.250. The resolved block still names A through 2934. At 2910 and 2922 C is the open mouth.",
))
for start_ts in ["00:48:47.550", "00:48:51.110", "00:48:55.210", "00:49:01.610"]:
    shots.append(keep(start_ts))
shots.append(keep(
    "00:49:16.470",
    note="Resolved B0183 names A from 2947.31. At 2952 C is still speaking, so the cut waits until 2956.470, when A is the open mouth.",
))

# Contiguous check and duration.
problems = []
if abs(sec(shots[0]["start"]) - 2360) > 0.001 or abs(sec(shots[-1]["end"]) - 2960) > 0.001:
    problems.append("range")
for i, shot in enumerate(shots):
    a, b = sec(shot["start"]), sec(shot["end"])
    shot["duration_s"] = round(b - a, 3)
    if b - a < 2:
        problems.append(f"short {b-a:.2f} at {shot['start']}")
    if i and abs(a - sec(shots[i - 1]["end"])) > 0.001:
        problems.append(f"gap at {shot['start']}")
    if i and (shot["composition"], shot["dominant"], tuple(shot["secondary"])) == (
        shots[i - 1]["composition"], shots[i - 1]["dominant"], tuple(shots[i - 1]["secondary"])
    ):
        problems.append(f"mergeable at {shot['start']}")
    for w in words:
        if w["start"] >= a:
            break
        if w["start"] < a < w["end"] - 0.02 and (w["end"] - w["start"]) < 1.5 and i:
            problems.append(f"mid-word {a:.3f} {w['text']}")
            break

from collections import Counter
c = Counter(s["shot_type"] for s in shots)
reactions = sum(1 for s in shots if s["reason"] == "reaction")
durs = [s["duration_s"] for s in shots]
longs = [s for s in shots if s["duration_s"] > 12]

floor = [
    {
        "turn_start": "00:40:30.000",
        "turn_end": "00:41:15.920",
        "resolved_speaker": "speaker_b",
        "previous_speaker": "speaker_a",
        "camera_at_turn_start": "TWO_PERSON_COMPOSITE",
        "chosen_shot": "TWO_PERSON_COMPOSITE B large, C secondary",
        "at_boundary": True,
        "reason": "Resolved B0159 starts at 2430.000. B is dominant from that word. C shares the beat.",
    },
    {
        "turn_start": "00:40:39.280",
        "turn_end": "00:41:15.920",
        "resolved_speaker": "speaker_b",
        "previous_speaker": "speaker_b",
        "camera_at_turn_start": "FULL_C",
        "chosen_shot": "FULL_C until 00:40:48.160, then FULL_B",
        "at_boundary": False,
        "reason": "Same resolved B block, but 2440 and 2444 show C speaking. C holds the opening. B is shown from 2448.160, where the frame confirms him. This is the A-to-B label correction.",
    },
    {
        "turn_start": "00:41:16.820",
        "turn_end": "00:43:27.780",
        "resolved_speaker": "speaker_a",
        "previous_speaker": "speaker_b",
        "camera_at_turn_start": "FULL_A",
        "chosen_shot": "TWO_PERSON_COMPOSITE A dominant from 00:41:03.460, then FULL_A",
        "at_boundary": False,
        "reason": "Resolved A starts at 2476.82. The frame at 2463 is already A, so A is dominant from 2463.460. The resolved block boundary lags the picture.",
    },
    {
        "turn_start": "00:43:21.200",
        "turn_end": "00:43:27.780",
        "resolved_speaker": "speaker_a",
        "previous_speaker": "speaker_a",
        "camera_at_turn_start": "FULL_A",
        "chosen_shot": "FULL_A",
        "at_boundary": True,
        "reason": "Not a new floor. Resolved B0165 corrects the old speaker_b label to speaker_a. The camera is already A and the old B reaction is gone.",
    },
    {
        "turn_start": "00:43:34.000",
        "turn_end": "00:43:59.240",
        "resolved_speaker": "speaker_b",
        "previous_speaker": "speaker_a",
        "camera_at_turn_start": "FULL_A",
        "chosen_shot": "FULL_A, then TWO_PERSON with A still dominant",
        "at_boundary": False,
        "conflict": True,
        "reason": "Resolved B0166 says speaker_b at 0.60. Mouth leader is A, 8.3 versus 6.3, and 2618 shows A speaking while B listens. The label is not put on camera.",
    },
    {
        "turn_start": "00:44:29.240",
        "turn_end": "00:47:14.010",
        "resolved_speaker": "speaker_a",
        "previous_speaker": "speaker_b",
        "camera_at_turn_start": "FULL_A",
        "chosen_shot": "FULL_A",
        "at_boundary": True,
        "reason": "Resolved speech returns to A. The camera is already on A because the previous B label was not followed.",
    },
    {
        "turn_start": "00:47:16.230",
        "turn_end": "00:47:45.450",
        "resolved_speaker": "speaker_c",
        "previous_speaker": "speaker_a",
        "camera_at_turn_start": "FULL_C",
        "chosen_shot": "FULL_C from 00:47:12.050",
        "at_boundary": True,
        "reason": "Resolved B0177 and the corrected B0178 are speaker_c. C is already the picture. The old speaker_a label stays corrected.",
    },
    {
        "turn_start": "00:47:46.910",
        "turn_end": "00:48:53.970",
        "resolved_speaker": "speaker_a",
        "previous_speaker": "speaker_c",
        "camera_at_turn_start": "TWO_PERSON_COMPOSITE",
        "chosen_shot": "B and C, not A",
        "at_boundary": False,
        "conflict": True,
        "reason": "Resolved B0179 and B0180 say speaker_a. At 2868 A is not speaking. At 2878 B is speaking. At 2910 and 2922 C is speaking. The camera follows those visible turns.",
    },
    {
        "turn_start": "00:48:55.150",
        "turn_end": "00:49:05.210",
        "resolved_speaker": "speaker_c",
        "previous_speaker": "speaker_a",
        "camera_at_turn_start": "FULL_C",
        "chosen_shot": "FULL_C already, from 00:48:30.250",
        "at_boundary": True,
        "reason": "Resolved C continues the answer that has been on camera since 2910.250.",
    },
    {
        "turn_start": "00:49:07.310",
        "turn_end": "00:49:19.470",
        "resolved_speaker": "speaker_a",
        "previous_speaker": "speaker_c",
        "camera_at_turn_start": "FULL_C",
        "chosen_shot": "FULL_A from 00:49:16.470",
        "at_boundary": False,
        "conflict": True,
        "reason": "Resolved A starts at 2947.31. At 2952 C is still speaking, so A is shown at 2956.470, when he is the open mouth.",
    },
]

plan = {
    "kind": "cfs_multicam_16x9_offline_plan",
    "workflow": "cfs_multicam_16x9",
    "role": "roles/virtual_director.md",
    "mode": "offline_editor",
    "precomputed_before_render": True,
    "speaker_timeline": "data/speakers/CFS03.speakers_resolved_v2.json",
    "speaker_timeline_modified": False,
    "source_video_on_disk": "data/inbox/03.mp4",
    "selected_range": {"start": "00:39:20.000", "end": "00:49:20.000", "duration_s": 600.0},
    "tiles": OLD["tiles"],
    "scale": OLD["scale"],
    "transitions": "hard_cut",
    "audio": "original synchronized program audio, unchanged by camera choice",
    "shots": shots,
    "summary": {
        "FULL_A": c["FULL_A"],
        "FULL_B": c["FULL_B"],
        "FULL_C": c["FULL_C"],
        "two_person_composites": c["TWO_PERSON_COMPOSITE"],
        "three_person_composites": c["THREE_PERSON_COMPOSITE"],
        "reaction_shots": reactions,
        "camera_edits": len(shots) - 1,
        "average_shot_duration_s": round(sum(durs) / len(durs), 3),
        "longest_shot_s": max(durs),
        "shot_count": len(shots),
    },
}

qa = {
    "kind": "cfs_multicam_16x9_offline_qa",
    "range": "00:39:20.000-00:49:20.000",
    "speaker_timeline": "data/speakers/CFS03.speakers_resolved_v2.json",
    "reviewed_before_render": True,
    "plan_computed_before_render": True,
    "meaningful_floor_changes": floor,
    "floor_changes_total": len(floor),
    "floor_changes_represented_correctly": sum(1 for row in floor if not row.get("conflict")),
    "resolved_speaker_conflicts": [row for row in floor if row.get("conflict")],
    "long_shots_over_12s": [
        {"start": s["start"], "end": s["end"], "duration_s": s["duration_s"], "shot_type": s["shot_type"], "reason": s["note"]}
        for s in longs
    ],
    "comparison_vs_previous": {
        "previous_plan": "data/director_tests/CFS03_39-49_offline_multicam_16x9_plan.json",
        "camera_changes": [
            "00:40:48.160-00:41:03.460 was a three-person unknown then FULL_A. It is now FULL_B, because resolved B0160 is speaker_b and the frame at 2450 confirms him.",
            "00:41:03.460-00:41:09.040 was FULL_B as a reaction while the file still thought A had not started. It is now a two-person shot with A dominant, because 2463 shows A speaking and B smiling.",
            "00:43:20.080-00:43:23.540 FULL_B is removed. Resolved B0165 is speaker_a, and 2604 shows A speaking while B has turned away. The surrounding A shots are one FULL_A from 00:43:18.000 to 00:43:37.620.",
        ],
        "unchanged": "The laugh coverage, A's robot and exam story, the reaction rhythm inside that story, and C's answer at the end keep the previous shot choices.",
        "around_00_43_21": "Previously a FULL_B reaction covered 2600.080-2603.540, overlapping the start of the mislabeled block. The resolved block is speaker_a at 0.93. The new shot is FULL_A across 2601.20.",
    },
}

out_plan = Path("data/director_tests/CFS03_39-49_offline_multicam_16x9_resolved_v2_plan.json")
out_qa = Path("data/director_tests/CFS03_39-49_offline_multicam_16x9_resolved_v2_qa.json")
out_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
out_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
print("problems", problems)
print("summary", json.dumps(plan["summary"]))
print("long", [(s["start"], s["duration_s"], s["shot_type"]) for s in longs])
print("total", round(sum(durs), 3), "shots", len(shots))
