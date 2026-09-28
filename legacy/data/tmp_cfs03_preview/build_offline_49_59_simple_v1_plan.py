"""Precompute the simplified-vocabulary plan for 00:49:20-00:59:20.

Does not render. Does not write the previous verified plan, QA, or video.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_offline_multicam_16x9 import filter_for, shot_type

# Same floor, same reactions, same story holds as the verified cut.
# Composites are not redesigned layouts. Overlap and the messy handoff
# become the original wide frame. Two quiet single-listener inserts,
# where A was kept dominant, fold back into the FULL_A hold.
RAW = [
    ("00:49:20.000", "00:50:08.140", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "Window opens inside resolved speaker_a. B's chin-on-hands listen at 00:49:46 is one quiet face, not a group event, so it stays inside this hold. B's smile is the next shot."),
    ("00:50:08.140", "00:50:16.140", "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a", False,
     "B smiles with his eyes closed while A is still speaking. Not a floor change."),
    ("00:50:16.140", "00:51:46.200", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "A continues the same explanation. B's hand-over-mouth listen at 00:50:56 does not take the picture off A. The next real overlap is C."),
    ("00:51:46.200", "00:51:56.180", "original_wide", "speaker_a", ["speaker_c"], "overlap", "speaker_a", "speaker_a", False,
     "At 3110 C is talking and A is also animated. One close-up would hide one of them, so the original group frame is used. A still owns the story."),
    ("00:51:56.180", "00:52:24.140", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "Resolved mouth on this stretch still leads on A. B takes the floor at the next word."),
    ("00:52:24.140", "00:52:36.140", "full", "speaker_b", [], "active_speaker", "speaker_b", "speaker_b", False,
     "Resolved B0189 is speaker_b. Frames at 3146 and 3158 show B speaking and A listening."),
    ("00:52:36.140", "00:52:43.440", "full", "speaker_a", [], "reaction", "speaker_b", "speaker_b", False,
     "A's arms are raised and his mouth is closed. B's question continues underneath."),
    ("00:52:43.440", "00:52:52.040", "full", "speaker_b", [], "active_speaker", "speaker_b", "speaker_b", False,
     "Back to B to finish the question before the handoff."),
    ("00:52:52.040", "00:53:07.160", "original_wide", "speaker_a", ["speaker_b", "speaker_c"], "overlap", "speaker_a", "speaker_a", False,
     "Resolved speaker_a. In the next 1.5s A is 3.22 and B is 3.90, too close to award one close-up. The original frame shows the handoff. This replaces the three-person composite."),
    ("00:53:07.160", "00:54:08.040", "full", "speaker_a", [], "active_speaker", "speaker_a", "speaker_a", False,
     "Frame at 3190 is A, and the resolved blocks from 3187 agree. 3210 and 3230 show B and C listening, so the story is not cut for a timer."),
    ("00:54:08.040", "00:54:16.160", "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a", False,
     "B smiles while A is speaking at 3255."),
    ("00:54:16.160", "00:54:26.000", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "A is still the open mouth at 3276, just before the overlap."),
    ("00:54:26.000", "00:54:40.000", "original_wide", "speaker_a", ["speaker_c"], "overlap", "speaker_a", "speaker_a", False,
     "At 3268 both A and C have open mouths. The original frame keeps both. The mouth gate just after 3280 still leads on A."),
    ("00:54:40.000", "00:55:38.300", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "Mouth activity at 3280, 3320 and 3346 still leads on A. A single open-mouth frame of C is not enough to take the floor."),
    ("00:55:38.300", "00:55:46.240", "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a", False,
     "B smiles. A is still the measured speaker, so this is a reaction and not a floor change."),
    ("00:55:46.240", "00:56:02.640", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "A remains the measured speaker through 3346. C's resolved turn starts on the next word."),
    ("00:56:02.640", "00:56:08.940", "full", "speaker_c", [], "active_speaker", "speaker_c", "speaker_c", False,
     "Resolved C at 3362.78, cut on the word at 3362.640. Frame 3364 is C speaking. B's raised hand does not take the floor."),
    ("00:56:08.940", "00:56:36.240", "full", "speaker_a", [], "active_speaker", "speaker_a", "speaker_a", False,
     "Resolved A at 3368.94. Mouth activity in the next 1.5 seconds leads on A."),
    ("00:56:36.240", "00:56:44.040", "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a", False,
     "B's skeptical listen at 3390, after A has been established. A's audio continues."),
    ("00:56:44.040", "00:57:22.060", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "A holds the doctor and data explanation until B's next skeptical listen."),
    ("00:57:22.060", "00:57:30.280", "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a", False,
     "B's finger is at his temple while A is speaking at 3445. Skeptical listen, not a new speaker."),
    ("00:57:30.280", "00:57:48.320", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "Back to A between the two skeptical listens."),
    ("00:57:48.320", "00:57:55.980", "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a", False,
     "The same skeptical listen is still on B at 3470. A's audio continues."),
    ("00:57:55.980", "00:58:36.220", "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a", False,
     "At 3502 A is speaking and C's mouth is closed. The resolved speaker_c label at 3498.76 is not taken yet."),
    ("00:58:36.220", "00:58:59.580", "original_wide", "speaker_a", ["speaker_c"], "overlap", "speaker_a", "speaker_c", True,
     "At 3518 and 3532 both A and C have open mouths. The original frame holds both until C has the floor alone. Resolved speaker_c is not taken yet."),
    ("00:58:59.580", "00:59:20.000", "full", "speaker_c", [], "active_speaker", "speaker_c", "speaker_a", True,
     "Mouth activity at 3539.36 is C 3.63 against A -1.69. Frames at 3542 and 3555 agree. The resolved speaker_a label is not used. The window ends on C."),
]


def sec(ts: str) -> float:
    h, m, rest = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


shots = []
problems = []
for i, (start, end, comp, dom, secondary, reason, active, resolved, override, note) in enumerate(RAW):
    dur = round(sec(end) - sec(start), 3)
    if dur < 2:
        problems.append(f"short {dur} at {start}")
    if i and start != RAW[i - 1][1]:
        problems.append(f"gap at {start}")
    if i and comp == RAW[i - 1][2] and dom == RAW[i - 1][3]:
        problems.append(f"mergeable at {start}")
    shot = {
        "start": start,
        "end": end,
        "duration_s": dur,
        "composition": comp,
        "dominant": dom,
        "secondary": secondary,
        "active_speaker": active,
        "resolved_speaker": resolved,
        "visual_override": override,
        "other_visible_speakers": list(secondary),
        "reason": reason,
        "note": note,
    }
    shot["shot_type"] = shot_type(shot)
    filt = filter_for(shot)
    if shot["shot_type"] == "ORIGINAL_WIDE":
        if any(token in filt for token in ("crop", "scale", "gblur", "overlay", "split")):
            problems.append(f"wide filter is not the source frame at {start}")
    elif "crop=" not in filt or "scale=1920:1080" not in filt:
        problems.append(f"full filter incomplete at {start}")
    shots.append(shot)

if shots[0]["start"] != "00:49:20.000" or shots[-1]["end"] != "00:59:20.000":
    problems.append("range")
total = round(sum(s["duration_s"] for s in shots), 3)
if abs(total - 600.0) > 0.05:
    problems.append(f"duration {total}")
banned = [s["shot_type"] for s in shots if s["shot_type"] not in {"FULL_A", "FULL_B", "FULL_C", "ORIGINAL_WIDE"}]
if banned:
    problems.append(f"banned {banned}")

c = Counter(s["shot_type"] for s in shots)
reactions = [s for s in shots if s["reason"] == "reaction"]
durs = [s["duration_s"] for s in shots]
wides = [s for s in shots if s["shot_type"] == "ORIGINAL_WIDE"]

floor = [
    {
        "turn_start": "00:49:20.000",
        "turn_end": "00:50:08.140",
        "resolved_speaker": "speaker_a",
        "verified_active_speaker": "speaker_a",
        "visual_override": False,
        "mouth_activity_a": None,
        "mouth_activity_b": None,
        "mouth_activity_c": None,
        "selected_camera": "FULL_A",
        "reason": "Window opens inside resolved speaker_a. The quiet listen at 00:49:46 stays inside this FULL_A hold.",
    },
    {
        "turn_start": "00:52:24.140",
        "turn_end": "00:52:36.140",
        "resolved_speaker": "speaker_b",
        "verified_active_speaker": "speaker_b",
        "visual_override": False,
        "mouth_activity_a": 0.604,
        "mouth_activity_b": 3.256,
        "mouth_activity_c": 1.452,
        "selected_camera": "FULL_B",
        "reason": "Resolved B0189 is speaker_b. Frames at 3146 and 3158 show B speaking and A listening.",
    },
    {
        "turn_start": "00:52:52.040",
        "turn_end": "00:53:07.160",
        "resolved_speaker": "speaker_a",
        "verified_active_speaker": "speaker_a",
        "visual_override": False,
        "mouth_activity_a": 3.22,
        "mouth_activity_b": 3.895,
        "mouth_activity_c": 0.957,
        "selected_camera": "ORIGINAL_WIDE",
        "reason": "Resolved speaker_a. In the next 1.5s A is 3.22 and B is 3.90, too close to override. The original frame replaces the three-person composite.",
    },
    {
        "turn_start": "00:56:02.640",
        "turn_end": "00:56:08.940",
        "resolved_speaker": "speaker_c",
        "verified_active_speaker": "speaker_c",
        "visual_override": False,
        "mouth_activity_a": -3.145,
        "mouth_activity_b": 3.29,
        "mouth_activity_c": 4.038,
        "selected_camera": "FULL_C",
        "reason": "Resolved C at 3362.78, cut on the word at 3362.640. Frame 3364 is C speaking. B's raised hand does not take the floor.",
    },
    {
        "turn_start": "00:56:08.940",
        "turn_end": "00:56:36.240",
        "resolved_speaker": "speaker_a",
        "verified_active_speaker": "speaker_a",
        "visual_override": False,
        "mouth_activity_a": 3.769,
        "mouth_activity_b": 3.367,
        "mouth_activity_c": 1.536,
        "selected_camera": "FULL_A",
        "reason": "Resolved A at 3368.94. Mouth activity in the next 1.5 seconds leads on A.",
    },
    {
        "turn_start": "00:58:18.760",
        "turn_end": "00:58:36.220",
        "resolved_speaker": "speaker_c",
        "verified_active_speaker": "speaker_a",
        "visual_override": True,
        "mouth_activity_a": 6.031,
        "mouth_activity_b": 4.875,
        "mouth_activity_c": 0.032,
        "selected_camera": "FULL_A",
        "reason": "Resolved C at 3498.76. The speaking mouth is A, and at 3502 C's mouth is closed, so the camera stays on A.",
    },
    {
        "turn_start": "00:58:59.580",
        "turn_end": "00:59:20.000",
        "resolved_speaker": "speaker_a",
        "verified_active_speaker": "speaker_c",
        "visual_override": True,
        "mouth_activity_a": 0.755,
        "mouth_activity_b": -5.03,
        "mouth_activity_c": 4.737,
        "selected_camera": "FULL_C",
        "reason": "Mouth activity at 3539.36 is C 3.63 against A -1.69. Frames at 3542 and 3555 agree. The resolved speaker_a label is not used. The window ends on C.",
    },
]
overrides = [row for row in floor if row["visual_override"]]
accepted = [row for row in floor if not row["visual_override"]]

plan = {
    "kind": "cfs_multicam_16x9_offline_plan",
    "workflow": "cfs_multicam_16x9",
    "role": "roles/virtual_director.md",
    "mode": "offline_editor",
    "visual_language": "FULL_A FULL_B FULL_C ORIGINAL_WIDE",
    "visual_gate": "reels_factory/cfs_offline_verify.py",
    "precomputed_before_render": True,
    "speaker_timeline": "data/speakers/CFS03.speakers_resolved_v2.json",
    "speaker_timeline_modified": False,
    "source_video_on_disk": "data/inbox/03.mp4",
    "compared_with": "data/director_tests/CFS03_49-59_offline_multicam_16x9_verified.mp4",
    "selected_range": {"start": "00:49:20.000", "end": "00:59:20.000", "duration_s": 600.0},
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
        "FULL_A": c["FULL_A"],
        "FULL_B": c["FULL_B"],
        "FULL_C": c["FULL_C"],
        "ORIGINAL_WIDE": c["ORIGINAL_WIDE"],
        "two_person_composites": 0,
        "three_person_composites": 0,
        "reaction_shots": len(reactions),
        "camera_edits": len(shots) - 1,
        "average_shot_duration_s": round(sum(durs) / len(durs), 3),
        "longest_shot_s": max(durs),
        "shot_count": len(shots),
        "meaningful_floor_changes": len(floor),
        "visual_overrides": len(overrides),
        "resolved_labels_accepted": len(accepted),
    },
}
qa = {
    "kind": "cfs_multicam_16x9_offline_qa",
    "range": "00:49:20.000-00:59:20.000",
    "speaker_timeline": "data/speakers/CFS03.speakers_resolved_v2.json",
    "visual_gate": "reels_factory/cfs_offline_verify.py",
    "reviewed_before_render": True,
    "plan_computed_before_render": True,
    "compared_with": "data/director_tests/CFS03_49-59_offline_multicam_16x9_verified.mp4",
    "meaningful_floor_changes": floor,
    "floor_changes_total": len(floor),
    "visual_overrides": overrides,
    "resolved_labels_accepted_unchanged": accepted,
    "long_shots_over_12s": [
        {"start": s["start"], "end": s["end"], "duration_s": s["duration_s"], "shot_type": s["shot_type"], "reason": s["note"]}
        for s in shots if s["duration_s"] > 12
    ],
    "reaction_shots": [f"{s['start']} {s['shot_type']} while {s['active_speaker']}" for s in reactions],
    "original_wide": [
        {"start": s["start"], "end": s["end"], "duration_s": s["duration_s"], "reason": s["note"]}
        for s in wides
    ],
    "composite_translation": [
        {"previous": "00:49:46.410-00:49:54.230 TWO_PERSON_COMPOSITE A+B reaction", "now": "folded into FULL_A 00:49:20.000-00:50:08.140", "why": "One quiet listen. A stayed dominant. Not group energy."},
        {"previous": "00:50:56.580-00:51:06.060 TWO_PERSON_COMPOSITE A+B reaction", "now": "folded into FULL_A 00:50:16.140-00:51:46.200", "why": "B's hand over his mouth is a listen, not a floor change or a group event."},
        {"previous": "00:51:46.200-00:51:56.180 TWO_PERSON_COMPOSITE A+C overlap", "now": "ORIGINAL_WIDE", "why": "Both A and C are talking. One close-up would hide one of them."},
        {"previous": "00:52:52.040-00:53:07.160 THREE_PERSON_COMPOSITE", "now": "ORIGINAL_WIDE", "why": "Messy handoff. Mouth scores too close for a single close-up."},
        {"previous": "00:54:26.000-00:54:40.000 TWO_PERSON_COMPOSITE A+C overlap", "now": "ORIGINAL_WIDE", "why": "Both mouths open."},
        {"previous": "00:58:36.220-00:58:59.580 TWO_PERSON_COMPOSITE A+C overlap", "now": "ORIGINAL_WIDE", "why": "Both mouths open until C takes the floor."},
    ],
    "rhythm_note": "Cut points of real floor changes, punchline reactions, and overlaps are unchanged. Two mild listening composites no longer leave the FULL_A story, so those two excursions disappear and two A holds get longer. The 60.88s A story at 00:53:07 is untouched. Active-speaker assignments are unchanged. Both visual overrides are unchanged.",
    "problems": problems,
}
out_plan = ROOT / "data/director_tests/CFS03_49-59_offline_multicam_16x9_simple_v1_plan.json"
out_qa = ROOT / "data/director_tests/CFS03_49-59_offline_multicam_16x9_simple_v1_qa.json"
out_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
out_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
print("problems", problems)
print("summary", json.dumps(plan["summary"]))
print("total", total)
print("wides", len(wides))
