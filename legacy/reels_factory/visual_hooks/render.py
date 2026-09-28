from __future__ import annotations

import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from ..framing import load_framing_profile
from ..utils import require_binary, run
from .compose import apply_hook_frames
from .config import VisualHookConfig
from .segment import SubjectSegmenter
from .sfx import mix_dialogue_with_sfx, read_wav, sfx_for_preset, write_wav

FPS = 30


def frozen_crop(profile: dict, speaker: str) -> tuple[int, int, int, int]:
    box = profile[speaker]
    return int(round(box["x"])), int(round(box["y"])), int(round(box["w"])), int(round(box["h"]))


def _extract_crop(
    ffmpeg: str,
    source: Path,
    start: float,
    duration: float,
    crop: tuple[int, int, int, int],
    temp: Path,
) -> tuple[list[np.ndarray], np.ndarray]:
    x, y, w, h = crop
    pattern = temp / "src_%04d.png"
    audio_path = temp / "src_audio.wav"
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vf", f"crop={w}:{h}:{x}:{y},fps={FPS}",
        str(pattern),
    ])
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vn", "-ac", "2", "-ar", "48000",
        str(audio_path),
    ])
    frames = []
    for path in sorted(temp.glob("src_*.png")):
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            continue
        frames.append(img)
    audio, _sr = read_wav(audio_path)
    if not frames:
        raise RuntimeError("No frames extracted for visual hook")
    max_n = min(len(frames), int(round(min(float(duration), 2.5) * FPS)))
    frames = frames[:max_n]
    need = int(round(max_n / float(FPS) * 48000))
    audio = audio[:need]
    return frames, audio


def _write_mp4(
    ffmpeg: str,
    frames: list[np.ndarray],
    audio: np.ndarray,
    out_path: Path,
    temp: Path,
    prefix: str,
) -> None:
    for i, frame in enumerate(frames):
        cv2.imwrite(str(temp / f"{prefix}_{i:04d}.png"), frame)
    wav = temp / f"{prefix}.wav"
    write_wav(wav, audio)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(FPS),
        "-i", str(temp / f"{prefix}_%04d.png"),
        "-i", str(wav),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ])


def _label(frame: np.ndarray, text: str) -> np.ndarray:
    out = frame.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 36), (0, 0, 0), -1)
    cv2.putText(out, text, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (240, 240, 240), 2, cv2.LINE_AA)
    return out


def render_visual_hook(
    source: Path,
    profile: dict,
    config: VisualHookConfig,
    out_path: Path,
    *,
    before_after_path: Path | None = None,
    ffmpeg: str | None = None,
) -> dict:
    """Render a short localized VFX hook inside a frozen speaker crop.

    Does not write framing profiles, edit plans, or Reel outputs.
    """
    if not config.enabled:
        raise ValueError("visual hook is disabled")
    if config.start_time is None:
        raise ValueError("visual_hook.start_time is required to render")
    crop = frozen_crop(profile, config.target_speaker)
    ffmpeg = ffmpeg or require_binary("ffmpeg")
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="visual_hook_") as td:
        temp = Path(td)
        frames, dialogue = _extract_crop(
            ffmpeg, source, config.start_time, config.duration, crop, temp
        )
        print(
            f"[visual_hook] crop={crop} frames={len(frames)} "
            f"preset={config.preset} speaker={config.target_speaker}",
            flush=True,
        )
        segmenter = SubjectSegmenter()
        print(f"[visual_hook] segmentation={segmenter.method}", flush=True)

        def _prog(i, n):
            if i == 1 or i == n or i % 5 == 0:
                print(f"[visual_hook] matte {i}/{n}", flush=True)

        hooked, mattes, method = apply_hook_frames(
            frames, config, fps=FPS, segmenter=segmenter, progress=_prog
        )
        audio = dialogue
        if config.sfx_enabled:
            sfx = sfx_for_preset(config.preset, config.duration)
            gain = 0.17 if config.preset == "fire_behind_subject" else 0.42
            audio = mix_dialogue_with_sfx(dialogue, sfx, gain=gain)
        _write_mp4(ffmpeg, hooked, audio, out_path, temp, "hook")
        if before_after_path is not None:
            labeled = [
                np.concatenate([_label(a, "BEFORE"), _label(b, "AFTER")], axis=1)
                for a, b in zip(frames, hooked)
            ]
            _write_mp4(ffmpeg, labeled, audio, before_after_path, temp, "cmp")
    elapsed = time.perf_counter() - t0
    info = {
        "output": str(out_path),
        "before_after": str(before_after_path) if before_after_path else None,
        "preset": config.preset,
        "target_speaker": config.target_speaker,
        "crop": {"x": crop[0], "y": crop[1], "w": crop[2], "h": crop[3]},
        "duration_s": round(len(hooked) / float(FPS), 3),
        "frame_count": len(hooked),
        "segmentation": method,
        "render_time_s": round(elapsed, 2),
        "source": str(source),
        "sfx_enabled": config.sfx_enabled,
    }
    print(f"[visual_hook] wrote {out_path} in {elapsed:.1f}s", flush=True)
    return info


def load_profile(path: Path) -> dict:
    return load_framing_profile(path)
