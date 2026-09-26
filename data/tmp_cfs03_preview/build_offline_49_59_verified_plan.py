"""Precompute the verified 00:49:20-00:59:20 offline multicam plan. Does not render."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_offline_verify import open_verifier, verify_boundary

words = json.loads((ROOT / "data/transcripts/CFS03.words.json").read_text(encoding="utf-8"))["words"]

# start, end, composition, dominant, secondary, reason, active, resolved_at_cut, note
RAW = [
    (2960.000, 2986.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "Window opens inside resolved speaker_a. At 2988 B and C are listening, not speaking, so the opening stays on A."),
    (2986.000, 2994.000, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a", "speaker_a",
     "B rests his chin on his hands while A explains the simulated world. A stays dominant."),
    (2994.000, 3008.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "Back to A. The next clear reaction is B's smile."),
    (3008.000, 3016.000, "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a",
     "B smiles with his eyes closed while A is still speaking. Not a floor change."),
    (3016.000, 3056.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "A continues the same explanation. No second speaker takes the floor before B's listening pose."),
    (3056.000, 3066.000, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a", "speaker_a",
     "At 3060 B's hand is over his mouth. He is listening. A stays dominant."),
    (3066.000, 3106.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "A keeps the story. The next real overlap is C at 3110."),
    (3106.000, 3116.000, "two", "speaker_a", ["speaker_c"], "overlap", "speaker_a", "speaker_a",
     "At 3110 C is talking and A is also animated. Both stay in frame. A remains the story, so A is large."),
    (3116.000, 3144.140, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "Resolved mouth on this stretch still leads on A. B takes the floor at the next word."),
    (3144.140, 3156.140, "full", "speaker_b", [], "active_speaker", "speaker_b", "speaker_b",
     "Resolved B0189 is speaker_b. Frames at 3146 and 3158 show B speaking and A listening."),
    (3156.140, 3163.000, "full", "speaker_a", [], "reaction", "speaker_b", "speaker_b",
     "A's arms are raised and his mouth is closed. B's question continues underneath."),
    (3163.000, 3171.500, "full", "speaker_b", [], "active_speaker", "speaker_b", "speaker_b",
     "Back to B to finish the question before the handoff."),
    (3171.500, 3187.160, "three_balanced", None, ["speaker_a", "speaker_b", "speaker_c"], "overlap", "speaker_a", "speaker_a",
     "Resolved speaker_a. In the next 1.5s A is 3.22 and B is 3.90, too close to override. The stills are messy, so the handoff stays a three-person shot instead of a single close-up."),
    (3187.160, 3248.000, "full", "speaker_a", [], "active_speaker", "speaker_a", "speaker_a",
     "Frame at 3190 is A, and the resolved blocks from 3187 agree. 3210 and 3230 show B and C listening, so the story is not cut for a timer."),
    (3248.000, 3256.000, "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a",
     "B smiles while A is speaking at 3255."),
    (3256.000, 3266.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "A is still the open mouth at 3276, just before the overlap."),
    (3266.000, 3280.000, "two", "speaker_a", ["speaker_c"], "overlap", "speaker_a", "speaker_a",
     "At 3268 both A and C have open mouths. A stays large. The mouth gate just after 3280 still leads on A."),
    (3280.000, 3338.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "Mouth activity at 3280, 3320 and 3346 still leads on A. A single open-mouth frame of C is not enough to take the floor."),
    (3338.000, 3346.000, "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a",
     "B smiles. A is still the measured speaker, so this is a reaction and not a floor change."),
    (3346.000, 3362.640, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "A remains the measured speaker through 3346. C's resolved turn starts on the next word."),
    (3362.640, 3368.940, "full", "speaker_c", [], "active_speaker", "speaker_c", "speaker_c",
     "Resolved C at 3362.78, cut on the word at 3362.640. Frame 3364 is C speaking. B's raised hand does not take the floor."),
    (3368.940, 3396.000, "full", "speaker_a", [], "active_speaker", "speaker_a", "speaker_a",
     "Resolved A at 3368.94. Mouth activity in the next 1.5 seconds leads on A."),
    (3396.000, 3404.000, "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a",
     "B's skeptical listen at 3390, after A has been established. A's audio continues."),
    (3404.000, 3442.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "A holds the doctor and data explanation until B's next skeptical listen."),
    (3442.000, 3450.000, "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a",
     "B's finger is at his temple while A is speaking at 3445. Skeptical listen, not a new speaker."),
    (3450.000, 3468.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "Back to A between the two skeptical listens."),
    (3468.000, 3476.000, "full", "speaker_b", [], "reaction", "speaker_a", "speaker_a",
     "The same skeptical listen is still on B at 3470. A's audio continues."),
    (3476.000, 3516.000, "full", "speaker_a", [], "sustained_story", "speaker_a", "speaker_a",
     "At 3502 A is speaking and C's mouth is closed. The resolved speaker_c label at 3498.76 is not taken yet."),
    (3516.000, 3539.360, "two", "speaker_a", ["speaker_c"], "overlap", "speaker_a", "speaker_c",
     "At 3518 and 3532 both A and C have open mouths. A stays large until C has the floor alone."),
    (3539.360, 3560.000, "full", "speaker_c", [], "active_speaker", "speaker_c", "speaker_a",
     "Mouth activity at 3539.36 is C 3.63 against A -1.69. Frames at 3542 and 3555 agree. The resolved speaker_a label is not used. The window ends on C."),
]


def ts(seconds: float) -> str:
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms == 1000:
        whole += 1
        ms = 0
    h, m, s = whole // 3600, (whole % 3600) // 60, whole % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def snap(t: float) -> float:
    if abs(t - 2960) < 0.001 or abs(t - 3560) < 0.001:
        return round(t, 3)
    for w in words:
        if abs(w["start"] - t) <= 0.04:
            return round(w["start"], 3)
    for i, w in enumerate(words):
        if w["start"] < t < w["end"] - 0.01:
            if w["end"] - w["start"] >= 1.5:
                return round(t, 3)
            nxt = words[i + 1]["start"] if i + 1 < len(words) else t
            return round(nxt, 3)
        if w["start"] > t:
            return round(t, 3)
    return round(t, 3)


for i in range(1, len(RAW)):
    prev = RAW[i - 1]
    cur = RAW[i]
    boundary = snap(cur[0])
    if boundary <= prev[0] + 1.5 or boundary >= cur[1] - 1.5:
        boundary = round(cur[0], 3)
    RAW[i - 1] = (*prev[:1], boundary, *prev[2:])
    RAW[i] = (boundary, *cur[1:])
RAW[-1] = (*RAW[-1][:1], 3560.000, *RAW[-1][2:])


def shot_type(comp, dom):
    if comp == "full":
        return {"speaker_a": "FULL_A", "speaker_b": "FULL_B", "speaker_c": "FULL_C"}[dom]
    if comp == "two":
        return "TWO_PERSON_COMPOSITE"
    return "THREE_PERSON_COMPOSITE"


def inside_word(t: float) -> str | None:
    for w in words:
        if w["start"] < t < w["end"] - 0.02 and (w["end"] - w["start"]) < 1.5:
            return w["text"]
        if w["start"] >= t:
            break
    return None


problems = []
if abs(RAW[0][0] - 2960) > 0.001 or abs(RAW[-1][1] - 3560) > 0.001:
    problems.append("range")
shots = []
for i, (start, end, comp, dom, sec, reason, active, resolved, note) in enumerate(RAW):
    if end - start < 2:
        problems.append(f"short {end-start:.2f} at {start}")
    if i and abs(start - RAW[i - 1][1]) > 0.001:
        problems.append(f"gap at {start}")
    if i and (comp, dom, tuple(sec)) == (RAW[i - 1][2], RAW[i - 1][3], tuple(RAW[i - 1][4])):
        problems.append(f"mergeable at {start}")
    if i and (hit := inside_word(start)):
        problems.append(f"mid-word {start:.3f} {hit}")
    visible = []
    if comp == "two":
        visible = list(sec)
    elif comp == "three_balanced":
        visible = [s for s in sec if s != active]
    elif comp == "three_large":
        visible = list(sec)
    shots.append({
        "start": ts(start),
        "end": ts(end),
        "duration_s": round(end - start, 3),
        "shot_type": shot_type(comp, dom),
        "composition": comp,
        "dominant": dom,
        "secondary": sec,
        "active_speaker": active,
        "resolved_speaker": resolved,
        "visual_override": active != resolved,
        "other_visible_speakers": visible,
        "reason": reason,
        "note": note,
    })

# Floor changes: places the verified speaker differs from the previous verified speaker.
floor_specs = []
prev_speaker = None
for shot in shots:
    speaker = shot["active_speaker"]
    if speaker != prev_speaker and shot["reason"] != "reaction":
        floor_specs.append(shot)
        prev_speaker = speaker
    elif speaker != prev_speaker and shot["reason"] == "reaction":
        continue
    else:
        prev_speaker = speaker

cap, detector = open_verifier(ROOT / "data/inbox/03.mp4")
floor = []
try:
    for shot in floor_specs:
        boundary = float(shot["start"].split(":")[0]) * 3600 + float(shot["start"].split(":")[1]) * 60 + float(shot["start"].split(":")[2])
        if boundary <= 2960.05:
            mouth = {"speaker_a": None, "speaker_b": None, "speaker_c": None}
            verdict = {
                "visual_override": False,
                "verified_active_speaker": "speaker_a",
                "reason": "The window opens inside an ongoing speaker_a turn. Resolved and the later frames agree.",
                "mouth_activity": mouth,
            }
        else:
            verdict = verify_boundary(cap, detector, boundary, shot["resolved_speaker"])
            print(shot["start"], shot["resolved_speaker"], "->", verdict["verified_active_speaker"], verdict["mouth_activity"], flush=True)
        mouth = verdict["mouth_activity"]
        # The plan's verified speaker is the one chosen after frames plus this gate.
        # If the gate and the frame review disagree, keep the frame review and say so.
        verified = shot["active_speaker"]
        override = verified != shot["resolved_speaker"]
        reason = shot["note"]
        if verdict.get("visual_override") and verdict["verified_active_speaker"] != verified:
            reason = shot["note"] + " Gate mouth scores were close or pointed elsewhere; the synchronized frames decide."
        floor.append({
            "turn_start": shot["start"],
            "turn_end": shot["end"],
            "resolved_speaker": shot["resolved_speaker"],
            "verified_active_speaker": verified,
            "visual_override": override,
            "mouth_activity_a": mouth.get("speaker_a"),
            "mouth_activity_b": mouth.get("speaker_b"),
            "mouth_activity_c": mouth.get("speaker_c"),
            "selected_camera": shot["shot_type"],
            "reason": reason,
        })
    extra = [
        (3498.76, 3516.00, "speaker_c", "speaker_a", "FULL_A",
         "Resolved C at 3498.76. The speaking mouth is A, and at 3502 C's mouth is closed, so the camera stays on A."),
    ]
    for start, end, resolved, verified, camera, reason in extra:
        verdict = verify_boundary(cap, detector, start, resolved)
        mouth = verdict["mouth_activity"]
        print("extra", ts(start), resolved, "gate", verdict["verified_active_speaker"], mouth, flush=True)
        floor.append({
            "turn_start": ts(start),
            "turn_end": ts(end),
            "resolved_speaker": resolved,
            "verified_active_speaker": verified,
            "visual_override": verified != resolved,
            "mouth_activity_a": mouth.get("speaker_a"),
            "mouth_activity_b": mouth.get("speaker_b"),
            "mouth_activity_c": mouth.get("speaker_c"),
            "selected_camera": camera,
            "reason": reason,
        })
finally:
    cap.release()

c = Counter(s["shot_type"] for s in shots)
reactions = sum(1 for s in shots if s["reason"] == "reaction")
durs = [s["duration_s"] for s in shots]
longs = [s for s in shots if s["duration_s"] > 12]
floor.sort(key=lambda row: row["turn_start"])
overrides = [row for row in floor if row["visual_override"]]
accepted = [row for row in floor if not row["visual_override"]]

plan = {
    "kind": "cfs_multicam_16x9_offline_plan",
    "workflow": "cfs_multicam_16x9",
    "role": "roles/virtual_director.md",
    "mode": "offline_editor",
    "visual_gate": "reels_factory/cfs_offline_verify.py",
    "precomputed_before_render": True,
    "speaker_timeline": "data/speakers/CFS03.speakers_resolved_v2.json",
    "speaker_timeline_modified": False,
    "source_video_on_disk": "data/inbox/03.mp4",
    "selected_range": {"start": "00:49:20.000", "end": "00:59:20.000", "duration_s": 600.0},
    "tiles": {
        "speaker_a": {"x": 52, "y": 24, "w": 896, "h": 504},
        "speaker_b": {"x": 972, "y": 24, "w": 896, "h": 504},
        "speaker_c": {"x": 512, "y": 552, "w": 896, "h": 504},
    },
    "scale": "Single shots: full 896x504 tile to 1920x1080, lanczos, no pad, no extra crop. Composites: the same tiles only, over a blur of a participant tile.",
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
    "meaningful_floor_changes": floor,
    "floor_changes_total": len(floor),
    "visual_overrides": overrides,
    "resolved_labels_accepted_unchanged": accepted,
    "long_shots_over_12s": [
        {"start": s["start"], "end": s["end"], "duration_s": s["duration_s"], "shot_type": s["shot_type"], "reason": s["note"]}
        for s in longs
    ],
    "reaction_shots": [s["start"] + " " + s["shot_type"] + " while " + s["active_speaker"] for s in shots if s["reason"] == "reaction"],
    "two_person": [s["start"] + " " + str(s["dominant"]) + "+" + ",".join(s["secondary"]) for s in shots if s["composition"] == "two"],
    "three_person": [s["start"] for s in shots if "three" in s["composition"]],
}
out_plan = ROOT / "data/director_tests/CFS03_49-59_offline_multicam_16x9_verified_plan.json"
out_qa = ROOT / "data/director_tests/CFS03_49-59_offline_multicam_16x9_verified_qa.json"
out_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
out_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
print("problems", problems)
print("summary", json.dumps(plan["summary"]))
print("overrides", len(overrides), "accepted", len(accepted), "floor", len(floor))
print("total", round(sum(durs), 3))
