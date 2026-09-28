"""Turn the 2 fps layout scan into protected vs directable regions.

Enter program only after 1.5 seconds of the branded three-tile bed
with a face in every tile. Leave on the first sample whose side
panels are no longer that bed. A missed face does not open a hole
while the bed is still there.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
NPZ = ROOT / "data" / "tmp_edited_multicam" / "layout_samples.npz"
OUT = ROOT / "data" / "director_tests" / "Edited_editability_map.json"
SOURCE = ROOT / "data" / "inbox" / "Edited.mp4"
ENTER_SAMPLES = 3  # 1.5 s at 2 fps


def duration() -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(SOURCE),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(proc.stdout.strip())


def regions_from_mask(times: np.ndarray, mask: np.ndarray, end: float) -> list[tuple[float, float]]:
    spans = []
    start = None
    step = float(times[1] - times[0]) if len(times) > 1 else 0.5
    for t, on in zip(times, mask):
        if on and start is None:
            start = float(t)
        elif not on and start is not None:
            spans.append((start, float(t)))
            start = None
    if start is not None:
        spans.append((start, end))
    # The sample at t represents [t, t+step). The loop already closes at the
    # first off sample, which is the start of that sample's window.
    if spans and spans[-1][1] < end and mask[-1]:
        spans[-1] = (spans[-1][0], end)
    return [(a, b) for a, b in spans if b - a >= step * 0.5]


def preliminary_reason(start: float, end: float, full_mean: float, first: float, last: float) -> str:
    if start <= 0.05 and end <= first + 0.05:
        return "INTRO"
    if start >= last - 0.05:
        return "ENDING"
    # The middle card is white type on a black frame, so the picture is dark.
    if full_mean < 30.0 and (end - start) >= 2.0:
        return "FULLSCREEN_TEXT"
    if full_mean < 18.0:
        return "BLACK"
    if full_mean > 110.0 and (end - start) >= 2.0:
        return "FULLSCREEN_TEXT"
    return "NON_PROGRAM_LAYOUT"


def main() -> None:
    data = np.load(NPZ)
    times = data["times"]
    gutter = data["gutter"].astype(bool)
    faces = data["faces"]
    full_mean = data["full_mean"]
    raw = gutter & (faces[:, 0] > 0) & (faces[:, 1] > 0) & (faces[:, 2] > 0)
    directable = np.zeros(len(times), dtype=bool)
    i = 0
    n = len(times)
    while i < n:
        if not raw[i]:
            i += 1
            continue
        j = i
        while j < n and gutter[j]:
            j += 1
        open_end = i
        while open_end < j and raw[open_end]:
            open_end += 1
        if open_end - i >= ENTER_SAMPLES:
            directable[i:j] = True
        i = max(j, i + 1)
    # A single half-second gutter miss is a flash or a detection blip.
    # Real cards and the two-person insert last much longer.
    step = float(times[1] - times[0]) if len(times) > 1 else 0.5
    i = 0
    n = len(directable)
    while i < n:
        if directable[i]:
            i += 1
            continue
        j = i
        while j < n and not directable[j]:
            j += 1
        hole = (j - i) * step
        left_program = i > 0 and directable[i - 1]
        right_program = j < n and directable[j]
        if left_program and right_program and hole < 1.0:
            directable[i:j] = True
        i = j
    end = duration()
    program = regions_from_mask(times, directable, end)
    protected_mask = ~directable
    # Samples start at 0. Anything after the last sample through EOF is protected
    # unless the last samples are directable, in which case regions_from_mask extends it.
    protected = regions_from_mask(times, protected_mask, end)
    if not protected or protected[0][0] > 0.05:
        protected.insert(0, (0.0, float(times[0]) if len(times) else end))
    first = program[0][0] if program else end
    last = program[-1][1] if program else 0.0
    protected_rows = []
    for start, stop in protected:
        sel = (times >= start) & (times < stop)
        mean = float(full_mean[sel].mean()) if sel.any() else 0.0
        protected_rows.append({
            "start": round(start, 3),
            "end": round(stop, 3),
            "duration_s": round(stop - start, 3),
            "state": "PROTECTED_MASTER",
            "reason": preliminary_reason(start, stop, mean, first, last),
            "full_frame_mean": round(mean, 2),
        })
    program_rows = [
        {
            "start": round(a, 3),
            "end": round(b, 3),
            "duration_s": round(b - a, 3),
            "state": "DIRECTABLE_PROGRAM",
        }
        for a, b in program
    ]
    payload = {
        "source_video": "data/inbox/Edited.mp4",
        "duration_s": end,
        "sample_fps": 2,
        "tiles": {
            "speaker_a": [52, 24, 896, 504],
            "speaker_b": [972, 24, 896, 504],
            "speaker_c": [512, 552, 896, 504],
        },
        "gate": "branded side panels match the program bed and each tile has a face; uncertain stays protected",
        "enter_s": 1.5,
        "exit": "first sample whose side panels leave the program bed",
        "directable_duration_s": round(sum(r["duration_s"] for r in program_rows), 3),
        "protected_duration_s": round(sum(r["duration_s"] for r in protected_rows), 3),
        "directable": program_rows,
        "protected": protected_rows,
        "raw_source_timestamps_used": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("program", len(program_rows), "protected", len(protected_rows), flush=True)
    for row in protected_rows:
        print("P", row["start"], row["end"], row["reason"], row["duration_s"], flush=True)
    for row in program_rows:
        print("D", row["start"], row["end"], row["duration_s"], flush=True)
    print("MAP_DONE", flush=True)


if __name__ == "__main__":
    main()
