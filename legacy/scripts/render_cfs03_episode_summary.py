# One-off CFS03 episode summary/trailer. Does not touch Reel plans or stack-order logic.
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from reels_factory.config import load_config
from reels_factory.framing import layout_from_framing_profile, resolve_framing_profile
from reels_factory.render import _accurate_cut_args, _print_locked_crops, _resolve_source_video
from reels_factory.utils import parse_timestamp, read_json, require_binary, run

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "episode_summaries" / "CFS03_summary_01.json"
OUT_PATH = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01.mp4"
SUMMARY_STACK = ("speaker_a", "speaker_c", "speaker_b")


def main() -> None:
    cfg = load_config(ROOT)
    plan = read_json(PLAN_PATH)
    if plan.get("kind") != "episode_summary":
        raise ValueError("This renderer only accepts kind=episode_summary")
    source = _resolve_source_video(Path(plan["source_video"]), PLAN_PATH)
    profile = resolve_framing_profile(source, cfg)
    if profile is None:
        raise FileNotFoundError("Frozen CFS03 framing profile is required")
    rcfg = dict(cfg["render"])
    rcfg["burn_captions"] = False
    order = tuple(plan.get("stack_order") or SUMMARY_STACK)
    layout = layout_from_framing_profile(profile, rcfg, stack_order=order)
    ffmpeg = require_binary("ffmpeg")
    crf = str(rcfg["video_crf"])
    audio_bitrate = str(rcfg["audio_bitrate"])
    clips = []
    for idx, seg in enumerate(plan["segments"]):
        start = parse_timestamp(seg["start"])
        end = parse_timestamp(seg["end"])
        clips.append({"label": str(seg.get("role") or f"beat_{idx:02d}"), "start": start, "end": end})
        print(
            f"[summary] {idx+1}/{len(plan['segments'])} {seg.get('role')} "
            f"{seg.get('speaker')} {seg['start']}-{seg['end']} "
            f"thread={seg.get('thread_id')} {end-start:.2f}s",
            flush=True,
        )
    print(f"[summary] fixed stack {list(order)} (not per-excerpt ranking)", flush=True)
    print(
        f"[layout] locked crops for all {len(clips)} clips "
        f"mode={layout.mode} method={layout.method}",
        flush=True,
    )
    _print_locked_crops(layout)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cfs03_summary_") as td:
        temp = Path(td)
        parts = []
        for idx, clip in enumerate(clips):
            part = temp / f"part_{idx:02d}.mp4"
            before_input, after_input = _accurate_cut_args(clip["start"], clip["end"])
            run([
                ffmpeg, "-y",
                *before_input,
                "-i", str(source),
                *after_input,
                "-filter_complex", layout.filter_complex,
                "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
                "-c:a", "aac", "-b:a", audio_bitrate,
                "-movflags", "+faststart",
                str(part),
            ])
            parts.append(part)
        concat_file = temp / "concat.txt"
        concat_file.write_text(
            "\n".join(f"file '{str(p).replace(os.sep, '/')}'" for p in parts),
            encoding="utf-8",
        )
        joined = temp / "joined.mp4"
        run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(joined)])
        print("[captions] disabled", flush=True)
        run([
            ffmpeg, "-y", "-i", str(joined),
            "-af", f"loudnorm=I={rcfg.get('loudness_target_lufs', -16)}:TP=-1.5:LRA=11",
            "-c:v", "copy", "-c:a", "aac", "-b:a", audio_bitrate,
            "-movflags", "+faststart",
            str(OUT_PATH),
        ])
    print(f"[summary] wrote {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
