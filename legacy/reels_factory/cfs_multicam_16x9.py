"""Independent 16:9 multi-camera program director for CFS.

Not a Reel workflow. Does not import or change the 9:16 stack renderer.
Each output frame is exactly one frozen participant tile scaled to 1920x1080.
There is no wide shot and no three-person composite.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .utils import parse_timestamp, read_json

OUTPUT_W = 1920
OUTPUT_H = 1080
# Frozen clean 16:9 participant tiles. Full tile, no extra face crop.
TILES = {
    "speaker_a": (52, 24, 896, 504),
    "speaker_b": (972, 24, 896, 504),
    "speaker_c": (512, 552, 896, 504),
}
CAMERAS = ("speaker_a", "speaker_b", "speaker_c")
ALLOWED_DECISIONS = {
    "active_speaker",
    "reaction",
    "unknown_hold",
    "shot_hold",
    "anticipatory_cut",
}


def tile_chain(camera: str) -> str:
    if camera not in TILES:
        raise ValueError(f"cfs_multicam_16x9 has no camera {camera!r}")
    x, y, w, h = TILES[camera]
    # 896x504 is exactly 16:9, so this fills 1920x1080 with no pad and no extra crop.
    return (
        f"crop={w}:{h}:{x}:{y},"
        f"scale={OUTPUT_W}:{OUTPUT_H}:flags=lanczos,"
        "setsar=1,fps=30,format=yuv420p"
    )


def camera_segments(plan: dict) -> list[dict]:
    """Collapse the decision log into hard-cut shots. Camera changes only."""
    decisions = plan.get("decisions") or []
    if not decisions:
        raise ValueError("director plan has no decisions")
    start = parse_timestamp(plan["selected_range"]["start"])
    end = parse_timestamp(plan["selected_range"]["end"])
    shots = []
    current = None
    for row in decisions:
        kind = str(row.get("decision_type") or "")
        if kind not in ALLOWED_DECISIONS:
            raise ValueError(f"decision type not allowed in 16:9 mode: {kind}")
        camera = str(row.get("selected_camera") or "")
        if camera not in CAMERAS:
            raise ValueError(f"selected camera must be one participant, got {camera!r}")
        t = parse_timestamp(row["timestamp"])
        if current is None:
            current = {"camera": camera, "start": t, "decision_type": kind}
            continue
        if camera != current["camera"]:
            current["end"] = t
            shots.append(current)
            current = {"camera": camera, "start": t, "decision_type": kind}
    if current is None:
        raise ValueError("no camera selected")
    current["end"] = end
    shots.append(current)
    if abs(shots[0]["start"] - start) > 0.05:
        raise ValueError("first shot does not start at the selected range")
    if abs(shots[-1]["end"] - end) > 0.05:
        raise ValueError("last shot does not end at the selected range")
    for shot in shots:
        if shot["end"] <= shot["start"]:
            raise ValueError(f"empty shot {shot}")
    return shots


def render_multicam(
    plan_path: Path,
    source: Path,
    output: Path,
    *,
    ffmpeg: str = "ffmpeg",
) -> Path:
    plan = read_json(plan_path)
    shots = camera_segments(plan)
    origin = parse_timestamp(plan["selected_range"]["start"])
    span = parse_timestamp(plan["selected_range"]["end"]) - origin
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / "_work_multicam_16x9"
    work.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, shot in enumerate(shots):
        dur = shot["end"] - shot["start"]
        part = work / f"part_{i:02d}.mp4"
        subprocess.run(
            [
                ffmpeg, "-y",
                "-ss", f"{shot['start']:.3f}",
                "-i", str(source),
                "-t", f"{dur:.3f}",
                "-vf", tile_chain(shot["camera"]),
                "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-movflags", "+faststart",
                str(part),
            ],
            check=True,
        )
        parts.append(part)
    concat = work / "concat.txt"
    concat.write_text(
        "".join(f"file '{p.name}'\n" for p in parts),
        encoding="utf-8",
    )
    video = work / "video.mp4"
    subprocess.run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat.name,
            "-c", "copy", video.name,
        ],
        check=True,
        cwd=work,
    )
    subprocess.run(
        [
            ffmpeg, "-y",
            "-i", str(video),
            "-ss", f"{origin:.3f}", "-t", f"{span:.3f}", "-i", str(source),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-shortest", "-movflags", "+faststart",
            str(output),
        ],
        check=True,
    )
    return output
