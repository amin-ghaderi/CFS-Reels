"""Render Edited_multicam_v1. Copies the Edited.mp4 AAC stream."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_multicam_16x9 import OUTPUT_H, OUTPUT_W, TILES
from reels_factory.utils import parse_timestamp

PLAN = ROOT / "data" / "director_tests" / "Edited_multicam_v1_plan.json"
SOURCE = ROOT / "data" / "inbox" / "Edited.mp4"
OUT = ROOT / "data" / "director_tests" / "Edited_multicam_v1.mp4"
WORK = ROOT / "data" / "director_tests" / "_work_edited_multicam_v1"
FPS = 30


def video_filter(shot: dict) -> str:
    if shot["shot_type"] in {"PROTECTED_MASTER", "ORIGINAL_WIDE"}:
        return "setsar=1,fps=30,format=yuv420p"
    camera = {
        "FULL_A": "speaker_a",
        "FULL_B": "speaker_b",
        "FULL_C": "speaker_c",
    }[shot["shot_type"]]
    x, y, w, h = TILES[camera]
    return (
        f"crop={w}:{h}:{x}:{y},"
        f"scale={OUTPUT_W}:{OUTPUT_H}:flags=lanczos,"
        "setsar=1,fps=30,format=yuv420p"
    )


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    shots = plan["shots"]
    origin = parse_timestamp(plan["selected_range"]["start"])
    end = parse_timestamp(plan["selected_range"]["end"])
    span = end - origin
    WORK.mkdir(parents=True, exist_ok=True)
    target = int(round(span * FPS))
    counts = []
    for shot in shots:
        dur = parse_timestamp(shot["end"]) - parse_timestamp(shot["start"])
        counts.append(max(1, int(round(dur * FPS))))
    counts[-1] += target - sum(counts)
    parts = []
    for i, shot in enumerate(shots):
        print(f"shot {i + 1}/{len(shots)} {shot['start']} {shot['shot_type']}", flush=True)
        part = WORK / f"part_{i:04d}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{parse_timestamp(shot['start']):.3f}",
                "-i", str(SOURCE),
                "-frames:v", str(counts[i]),
                "-vf", video_filter(shot),
                "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-g", "30", "-keyint_min", "30",
                str(part),
            ],
            check=True,
        )
        parts.append(part)
    concat = WORK / "concat.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    video = WORK / "video.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", str(video)],
        check=True,
        cwd=WORK,
    )
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(SOURCE),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart",
            str(OUT),
        ],
        check=True,
    )
    print("RENDER_DONE", OUT, flush=True)
    print("AUDIO stream-copied from Edited.mp4", flush=True)


if __name__ == "__main__":
    main()
