"""Build the precomputed 00:39:20-00:49:20 offline multicam plan. Not a renderer."""
import json
from pathlib import Path

RAW = [
    (2360.000, 2383.370, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "Window opens mid-turn. A is inside one guardrail metaphor. Sampled listeners at 2362 and 2376 are neutral, so the shot is not broken by a timer."),
    (2383.370, 2398.650, "three_balanced", None, ["speaker_a", "speaker_b", "speaker_c"], "group_reaction", "unknown",
     "Attribution drops to unknown and all three enter a laugh. No single identity is assigned."),
    (2398.650, 2406.000, "full", "speaker_c", [], "reaction", "unknown",
     "C's laugh is the clearest face once the group laugh is underway. Speech here is still unattributed."),
    (2406.000, 2418.000, "full", "speaker_b", [], "reaction", "unknown",
     "B's laugh peaks, hand on his forehead. There are no words in this stretch, so the cut is visual."),
    (2418.000, 2430.000, "three_balanced", None, ["speaker_a", "speaker_b", "speaker_c"], "group_reaction", "unknown",
     "The laugh settles on all three before B's attributed line."),
    (2430.000, 2439.280, "two", "speaker_b", ["speaker_c"], "overlap", "speaker_b",
     "B takes the floor at the word boundary, confidence 0.72. C is in the same beat, mouth open and then laughing."),
    (2439.280, 2448.160, "full", "speaker_c", [], "active_speaker", "speaker_c",
     "The file labels this speaker_a at 0.50. At 2440 and 2444 C is speaking and A is listening, so the label is not used."),
    (2448.160, 2456.000, "three_balanced", None, ["speaker_a", "speaker_b", "speaker_c"], "overlap", "unknown",
     "Mouths are unclear through the Terminator sentence. Nobody is assigned."),
    (2456.000, 2463.460, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A's Terminator / Neuralink thesis. The next clean speaking frame at 2463 confirms him."),
    (2463.460, 2469.040, "full", "speaker_b", [], "reaction", "speaker_a",
     "B smiles while A says he would chase the upgrade. A's audio continues."),
    (2469.040, 2495.660, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A demonstrates the walking robots. At 2486 B is looking down, which is not a usable reaction."),
    (2495.660, 2505.620, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "A addresses the table on how the old robots were programmed. B is the listener about to rest his chin on his hand."),
    (2505.620, 2514.540, "full", "speaker_b", [], "reaction", "speaker_a",
     "B's chin-on-hand listen while A moves the story into the real world."),
    (2514.540, 2523.160, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A on learning the way a person learns."),
    (2523.160, 2532.560, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "B's hand comes up to his face during that comparison."),
    (2532.560, 2546.000, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "Words in this gap have no speaker block. The frame at 2546 shows A still carrying the same explanation. The missing label is not treated as a new speaker."),
    (2546.000, 2556.080, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "B's held attention during the speed comparison."),
    (2556.080, 2567.760, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A's 1000x line. Same speaker on both sides of the gap."),
    (2567.760, 2571.860, "full", "speaker_b", [], "reaction", "speaker_a",
     "B's hand on his forehead, skeptical, while A delivers the four-days claim."),
    (2571.860, 2592.480, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A's competition argument. The unknown block is the same voice: at 2580 A is the only open mouth."),
    (2592.480, 2598.000, "two", "speaker_a", ["speaker_b"], "overlap", "speaker_a",
     "At 2592 A is speaking and B's mouth is open on the same beat."),
    (2598.000, 2600.080, "full", "speaker_a", [], "active_speaker", "speaker_a",
     "Back to A for the short landing before B's smile."),
    (2600.080, 2603.540, "full", "speaker_b", [], "reaction", "speaker_a",
     "B smiles. The following speaker_b block at 0.50 is not a floor change: at 2604 and 2608 A is speaking and B turns away."),
    (2603.540, 2617.200, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A explains reinforcement learning. The 0.50 B label is ignored."),
    (2617.200, 2623.740, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "B clasps his hands while A says every robot is learning."),
    (2623.740, 2632.640, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A sets up the doctor line."),
    (2632.640, 2639.240, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "B's hands stay clasped while A delivers the doctor punchline."),
    (2639.240, 2655.460, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "Unlabelled words continue A's France anecdote. The frame at 2642 is A."),
    (2655.460, 2660.240, "full", "speaker_b", [], "reaction", "speaker_a",
     "B laughs on the strange-and-a-mess beat."),
    (2660.240, 2668.000, "two", "speaker_a", ["speaker_c"], "overlap", "speaker_a",
     "At 2664 A and C are both mid-word. A stays dominant, C is the other voice."),
    (2668.000, 2680.240, "full", "speaker_a", [], "active_speaker", "speaker_a",
     "A pulls the point back."),
    (2680.240, 2686.800, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "B's skeptical listen at the start of the setup."),
    (2686.800, 2702.680, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A starts the unguarded-exam story. Frames at 2682, 2688 and 2694 are A, so the unknown label is not a new speaker."),
    (2702.680, 2708.200, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "A says the model had no guardrail. B is locked on him."),
    (2708.200, 2721.080, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A on the system deciding to spend less energy."),
    (2721.080, 2726.080, "full", "speaker_b", [], "reaction", "speaker_a",
     "B smiles as A describes the model leaving the box."),
    (2726.080, 2734.520, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A: the model leaves the box and enters the real world."),
    (2734.520, 2740.000, "two", "speaker_a", ["speaker_b"], "reaction", "speaker_a",
     "B stays with the story while A says it found the answer site."),
    (2740.000, 2755.650, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A keeps the punchline: it hacks the site, returns the answers, and cannot be contained."),
    (2755.650, 2761.810, "full", "speaker_b", [], "reaction", "speaker_a",
     "B smiles while A turns the point on the people asking the question."),
    (2761.810, 2784.220, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A on the data of the whole world. At 2770 B's eyes are closed, so that frame is not used as a reaction."),
    (2784.220, 2789.570, "full", "speaker_b", [], "reaction", "speaker_a",
     "B's chin on his hand as A says the model starts to talk like you."),
    (2789.570, 2807.390, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "The two-roommate metaphor, told straight through."),
    (2807.390, 2812.870, "full", "speaker_b", [], "reaction", "speaker_a",
     "B's finger on his chin on enslaves-or-eats."),
    (2812.870, 2822.270, "full", "speaker_a", [], "sustained_story", "speaker_a",
     "A compares a million years of evolution with thirty years of the model."),
    (2822.270, 2828.650, "full", "speaker_b", [], "reaction", "speaker_a",
     "B's amused wince while A lands the comparison."),
    (2828.650, 2832.050, "full", "speaker_a", [], "active_speaker", "speaker_a",
     "Back to A for the last beat before C comes in."),
    (2832.050, 2846.530, "full", "speaker_c", [], "active_speaker", "speaker_c",
     "C is the open mouth from 2832, and the 0.77 label at 2836.450 sits inside this shot. The 0.50 speaker_a label at 2839 is not used: A is listening."),
    (2846.530, 2858.150, "full", "speaker_b", [], "question", "speaker_b",
     "B's mouth opens on the question. The file still says speaker_a at 0.50. The picture is the cut."),
    (2858.150, 2867.630, "three_balanced", None, ["speaker_a", "speaker_b", "speaker_c"], "overlap", "unknown",
     "B looks away, C covers his mouth, A is not the voice. No identity is forced."),
    (2867.630, 2875.110, "two", "speaker_b", ["speaker_c"], "overlap", "speaker_b",
     "B and C are both in it. The 0.78 speaker_a label is rejected: A's hands are behind his head."),
    (2875.110, 2889.050, "full", "speaker_b", [], "question", "speaker_b",
     "B's attributed question begins. The frame at 2878 confirms him."),
    (2889.050, 2899.110, "full", "speaker_a", [], "reaction", "speaker_b",
     "A receives the question, chin on his hand. B's audio continues."),
    (2899.110, 2910.250, "full", "speaker_b", [], "question", "speaker_b",
     "B finishes the question on feelings, children, and Terminator."),
    (2910.250, 2927.550, "full", "speaker_c", [], "answer", "speaker_c",
     "C takes the floor on the Kurdish example and stays with it. The block is still labelled speaker_b, but from 2910 C is the open mouth."),
    (2927.550, 2931.110, "full", "speaker_a", [], "reaction", "speaker_c",
     "A listens, hand on his chin, while C explains the cut he wants to make."),
    (2931.110, 2935.210, "full", "speaker_c", [], "answer", "speaker_c",
     "Back to C to finish the line."),
    (2935.210, 2941.610, "three_large", "speaker_c", ["speaker_a", "speaker_b"], "overlap", "speaker_c",
     "A and C both speak. B smiles. C stays large."),
    (2941.610, 2956.470, "full", "speaker_c", [], "answer", "speaker_c",
     "C lists the languages. The cut is the word start, because the 0.75 label falls inside the word. He is still speaking at 2952."),
    (2956.470, 2960.000, "full", "speaker_a", [], "active_speaker", "speaker_a",
     "A takes the floor back, pointing. The window ends on him."),
]


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


words = json.loads(Path("data/transcripts/CFS03.words.json").read_text(encoding="utf-8"))["words"]


def snap(t: float) -> float:
    """Move a cut onto a word start. Long ASR blobs are left alone."""
    if abs(t - 2360) < 0.001 or abs(t - 2960) < 0.001:
        return round(t, 3)
    for w in words:
        if abs(w["start"] - t) <= 0.04:
            return round(w["start"], 3)
    for i, w in enumerate(words):
        if w["start"] < t < w["end"] - 0.01:
            if w["end"] - w["start"] >= 1.5:
                return round(t, 3)
            return round(words[i + 1]["start"], 3)
        if w["start"] > t:
            return round(t, 3)
    return round(t, 3)


for i in range(1, len(RAW)):
    prev = RAW[i - 1]
    cur = RAW[i]
    boundary = snap(cur[0])
    if boundary <= prev[0] + 1.5 or boundary >= cur[1] - 1.5:
        boundary = round(cur[0], 3)
    RAW[i - 1] = (prev[0], boundary, *prev[2:])
    RAW[i] = (boundary, *cur[1:])
RAW[-1] = (*RAW[-1][:1], 2960.000, *RAW[-1][2:])


def inside_word(t: float) -> str | None:
    for w in words:
        if w["start"] < t < w["end"] - 0.02:
            return w["text"]
        if w["start"] >= t:
            break
    return None


problems = []
if abs(RAW[0][0] - 2360) > 0.001 or abs(RAW[-1][1] - 2960) > 0.001:
    problems.append("range")
for i, row in enumerate(RAW):
    a, b = row[0], row[1]
    if b - a < 2 and i != len(RAW) - 1:
        problems.append(f"short {b-a:.2f} at {a}")
    if i and abs(a - RAW[i - 1][1]) > 0.001:
        problems.append(f"not contiguous at {a}")
    if i and (row[2], row[3], tuple(row[4])) == (RAW[i-1][2], RAW[i-1][3], tuple(RAW[i-1][4])):
        problems.append(f"mergeable at {a}")
    if i and (hit := inside_word(a)):
        problems.append(f"mid-word {a:.3f} {hit}")

shots = []
for start, end, comp, dom, sec, reason, active, note in RAW:
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
        "other_visible_speakers": visible,
        "reason": reason,
        "note": note,
    })

from collections import Counter
c = Counter(s["shot_type"] for s in shots)
reactions = sum(1 for s in shots if s["reason"] == "reaction")
durs = [s["duration_s"] for s in shots]
longs = [s for s in shots if s["duration_s"] > 12]
# rapid: 4 consecutive shots each under 4s
rapid = []
for i in range(len(shots) - 3):
    window = shots[i:i+4]
    if all(s["duration_s"] < 4 for s in window):
        rapid.append(shots[i]["start"])

plan = {
    "kind": "cfs_multicam_16x9_offline_plan",
    "workflow": "cfs_multicam_16x9",
    "role": "roles/virtual_director.md",
    "mode": "offline_editor",
    "precomputed_before_render": True,
    "source_video_on_disk": "data/inbox/03.mp4",
    "selected_range": {"start": "00:39:20.000", "end": "00:49:20.000", "duration_s": 600.0},
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
    },
}

floor = [
    {"boundary": "00:40:30.000", "outgoing": "unknown", "incoming": "speaker_b", "confidence": 0.72,
     "planned": "TWO_PERSON_COMPOSITE B large", "at_boundary": True,
     "note": "Word start. B is the open mouth. C is also in the beat, so B is large rather than alone."},
    {"boundary": "00:40:39.280", "outgoing": "speaker_b", "incoming": "speaker_c", "confidence": None,
     "planned": "FULL_C", "at_boundary": True,
     "note": "File says speaker_a at 0.50. Picture at 2440 and 2444 is C speaking, A listening. Label rejected."},
    {"boundary": "00:40:56.000", "outgoing": "unknown", "incoming": "speaker_a", "confidence": 0.50,
     "planned": "FULL_A", "at_boundary": True,
     "note": "Return to A's thesis once the handoff is no longer a clear C shot. Confirmed speaking by 2463."},
    {"boundary": "00:43:21.200", "outgoing": "speaker_a", "incoming": "speaker_b", "confidence": 0.50,
     "planned": "stayed FULL_A", "at_boundary": False,
     "note": "Rejected. At 2604 A is speaking and B has turned away. Not a floor change."},
    {"boundary": "00:47:16.450", "outgoing": "speaker_a", "incoming": "speaker_c", "confidence": 0.77,
     "planned": "already FULL_C from 00:47:12.050", "at_boundary": True,
     "note": "C is already the picture at 2832. The labelled start sits inside the C shot."},
    {"boundary": "00:47:55.110", "outgoing": "speaker_c", "incoming": "speaker_b", "confidence": 0.52,
     "planned": "FULL_B", "at_boundary": True,
     "note": "Question starts. Frame 2878 confirms B. The earlier 0.78 A label at 2866 is rejected because A is not speaking."},
    {"boundary": "00:48:30.250", "outgoing": "speaker_b", "incoming": "speaker_c", "confidence": None,
     "planned": "FULL_C", "at_boundary": True,
     "note": "Block still says speaker_b until 2933. From 2910 C is the speaker. Cut is the word start."},
    {"boundary": "00:49:02.570", "outgoing": "overlap", "incoming": "speaker_c", "confidence": 0.75,
     "planned": "FULL_C from the word at 00:49:01.610", "at_boundary": True,
     "note": "Label falls inside انگلیسی. Cut is that word's start, and C is already the large tile."},
    {"boundary": "00:49:16.470", "outgoing": "speaker_c", "incoming": "speaker_a", "confidence": None,
     "planned": "FULL_A", "at_boundary": True,
     "note": "Picture at 2956 is A. Attribution on this tail is unknown. Not guessed earlier than the frame."},
]

primary_not_active = []
for s in shots:
    shown = s["dominant"]
    if shown and shown != s["active_speaker"]:
        primary_not_active.append({
            "start": s["start"],
            "end": s["end"],
            "shown": shown,
            "active_speaker": s["active_speaker"],
            "reason": s["reason"],
            "note": s["note"],
        })

qa = {
    "kind": "cfs_multicam_16x9_offline_qa",
    "range": "00:39:20.000-00:49:20.000",
    "reviewed_before_render": True,
    "plan_computed_before_render": True,
    "meaningful_floor_changes": floor,
    "floor_changes_at_boundary": sum(1 for f in floor if f["at_boundary"]),
    "floor_changes_total": len(floor),
    "long_shots_over_12s": [
        {"start": s["start"], "end": s["end"], "duration_s": s["duration_s"], "shot_type": s["shot_type"], "reason": s["note"]}
        for s in longs
    ],
    "rapid_cut_runs_of_4_under_4s": rapid,
    "composite_shots": [s["start"] + " " + s["shot_type"] + " " + s["reason"] for s in shots if "COMPOSITE" in s["shot_type"]],
    "reaction_shots": [s["start"] + " shown " + str(s["dominant"]) + " while " + s["active_speaker"] for s in shots if s["reason"] == "reaction"],
    "primary_not_active_speaker": primary_not_active,
    "rejected_labels": [
        "00:40:39 speaker_a 0.50 — picture is C",
        "00:43:21 speaker_b 0.50 — picture is A, B turned away",
        "00:47:19 speaker_a 0.50 — picture is still C, then B",
        "00:47:46 speaker_a 0.78 — A is not speaking; B and C are",
        "00:48:30-00:48:53 speaker_b block continues while C has the floor",
    ],
}

out_plan = Path("data/director_tests/CFS03_39-49_offline_multicam_16x9_plan.json")
out_qa = Path("data/director_tests/CFS03_39-49_offline_multicam_16x9_qa.json")
out_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
out_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
print("problems", problems)
print("summary", json.dumps(plan["summary"], ensure_ascii=False))
print("long", len(longs), "rapid", rapid)
print("primary_not_active", len(primary_not_active))
print("total_duration", round(sum(durs), 3))
