"""Offline 16:9 multi-camera editor for CFS.

Separate from the Reel renderer and from the earlier single-tile
cfs_multicam_16x9 live-style test. The shot list is computed before
render.

The visual language is only four shots. FULL_A, FULL_B, and FULL_C
scale one complete participant tile to 1920x1080. ORIGINAL_WIDE is
the untouched full source frame at that timestamp. There is no
designed composite, blur bed, or split screen.

Speaker identity for a floor change comes from
cfs_offline_verify: the resolved timeline is the prior, and a clear
mouth/jaw contradiction may override it for this shot plan only.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .cfs_multicam_16x9 import OUTPUT_H, OUTPUT_W, TILES
from .utils import parse_timestamp, read_json

FPS = 30

ALLOWED_SHOT_TYPES = ("FULL_A", "FULL_B", "FULL_C", "ORIGINAL_WIDE")
_FULL_BY_SPEAKER = {
    "speaker_a": "FULL_A",
    "speaker_b": "FULL_B",
    "speaker_c": "FULL_C",
}
_REJECTED_COMPOSITIONS = frozenset({"two", "three", "three_large", "three_balanced"})
_REJECTED_SHOT_TYPES = frozenset({"TWO_PERSON_COMPOSITE", "THREE_PERSON_COMPOSITE"})


def shot_type(shot: dict) -> str:
    """Name the only shots this workflow can emit."""
    kind = shot.get("composition")
    declared = shot.get("shot_type")
    if kind in _REJECTED_COMPOSITIONS or declared in _REJECTED_SHOT_TYPES:
        raise ValueError(
            "custom composites are not in the offline 16:9 vocabulary; "
            "use FULL_A, FULL_B, FULL_C, or ORIGINAL_WIDE"
        )
    if kind == "original_wide" or declared == "ORIGINAL_WIDE":
        if kind not in (None, "original_wide"):
            raise ValueError(f"ORIGINAL_WIDE cannot use composition {kind!r}")
        if declared not in (None, "ORIGINAL_WIDE"):
            raise ValueError(f"original_wide cannot be labeled {declared!r}")
        return "ORIGINAL_WIDE"
    if kind != "full":
        raise ValueError(f"unknown composition {kind!r}")
    camera = shot.get("dominant")
    if camera not in _FULL_BY_SPEAKER:
        raise ValueError(f"full shot needs one participant, got {camera!r}")
    label = _FULL_BY_SPEAKER[camera]
    if declared not in (None, label):
        raise ValueError(f"full {camera} cannot be labeled {declared!r}")
    return label


def filter_for(shot: dict) -> str:
    label = shot_type(shot)
    if label == "ORIGINAL_WIDE":
        # The recorded 1920x1080 frame. No crop, no scale, no blur, no overlay.
        return "setsar=1,fps=30,format=yuv420p"
    camera = shot["dominant"]
    x, y, w, h = TILES[camera]
    return (
        f"crop={w}:{h}:{x}:{y},"
        f"scale={OUTPUT_W}:{OUTPUT_H}:flags=lanczos,"
        "setsar=1,fps=30,format=yuv420p"
    )


def render_offline(
    plan_path: Path,
    source: Path,
    output: Path,
    *,
    ffmpeg: str = "ffmpeg",
    work_dir: Path | None = None,
) -> Path:
    plan = read_json(plan_path)
    shots = plan["shots"]
    for shot in shots:
        label = shot_type(shot)
        if label not in ALLOWED_SHOT_TYPES:
            raise ValueError(f"shot type not allowed: {label}")
        filter_for(shot)
    origin = parse_timestamp(plan["selected_range"]["start"])
    end = parse_timestamp(plan["selected_range"]["end"])
    span = end - origin
    if abs(parse_timestamp(shots[0]["start"]) - origin) > 0.02:
        raise ValueError("first shot does not start at the range")
    if abs(parse_timestamp(shots[-1]["end"]) - end) > 0.02:
        raise ValueError("last shot does not end at the range")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = work_dir or (output.parent / "_work_offline_39_49")
    work.mkdir(parents=True, exist_ok=True)
    parts = []
    target_frames = int(round(span * FPS))
    counts = []
    for shot in shots:
        dur = parse_timestamp(shot["end"]) - parse_timestamp(shot["start"])
        counts.append(max(1, int(round(dur * FPS))))
    drift = target_frames - sum(counts)
    counts[-1] += drift
    if counts[-1] < 1:
        raise ValueError("frame budget collapsed")
    for i, shot in enumerate(shots):
        print(f"shot {i+1}/{len(shots)} {shot['start']} {shot.get('shot_type')}", flush=True)
        part = work / f"part_{i:03d}.mp4"
        start = parse_timestamp(shot["start"])
        frames = counts[i]
        subprocess.run(
            [
                ffmpeg, "-y",
                "-ss", f"{start:.3f}",
                "-i", str(source),
                "-frames:v", str(frames),
                "-vf", filter_for(shot),
                "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-g", "30", "-keyint_min", "30",
                "-movflags", "+faststart",
                str(part),
            ],
            check=True,
        )
        parts.append(part)
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    video = work / "video.mp4"
    subprocess.run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt",
            "-c", "copy", "video.mp4",
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
