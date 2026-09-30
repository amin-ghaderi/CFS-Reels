"""Isolated overlap process.

Stdout is NDJSON only. OpenCV is imported only for a real extraction.
The parent cancels this process tree, which also stops the FFmpeg child.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from amix.amix_engine.adapters.media.publish import publish_pid, publish_text

_MODES = frozenset({"extract", "wait", "fail", "emit"})


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    spec_path = _spec_path(args)
    if spec_path is None:
        _fail("overlap_failed")
        return 1
    try:
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("overlap_failed")
        return 1
    if not isinstance(spec, dict):
        _fail("overlap_failed")
        return 1
    mode = spec.get("mode", "extract")
    if mode not in _MODES:
        _fail("overlap_failed")
        return 1
    pid_path = spec.get("pid_path")
    if isinstance(pid_path, str) and pid_path:
        try:
            publish_pid(pid_path, os.getpid())
        except OSError:
            _fail("overlap_failed")
            return 1
    if mode == "wait":
        return _wait(spec)
    if mode == "fail":
        _fail("overlap_failed")
        return 1
    if mode == "emit":
        return _emit_fixture(spec)
    return _extract(spec)


def _wait(spec: dict) -> int:
    import subprocess

    child_path = spec.get("child_pid_path")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if isinstance(child_path, str) and child_path:
        publish_pid(child_path, child.pid)
    _emit({"type": "ready"})
    while True:
        time.sleep(0.05)


def _emit_fixture(spec: dict) -> int:
    evidence = spec.get("evidence_path")
    result_path = spec.get("result_path")
    if not isinstance(evidence, str) or not isinstance(result_path, str):
        _fail("overlap_failed")
        return 1
    try:
        payload = json.loads(Path(evidence).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("overlap_failed")
        return 1
    if not isinstance(payload, dict):
        _fail("overlap_failed")
        return 1
    payload["opencv_version"] = payload.get("opencv_version") or "test"
    try:
        publish_text(result_path, json.dumps(payload))
    except OSError:
        _fail("overlap_failed")
        return 1
    _emit({"type": "progress", "bp": 9500})
    return 0


def _extract(spec: dict) -> int:
    try:
        return _extract_media(spec)
    except Exception:
        _fail("overlap_failed")
        return 1


def _extract_media(spec: dict) -> int:
    import subprocess

    import numpy as np

    from amix.amix_engine.adapters.vision.extract import AUDIO_RATE, SAMPLE_FPS, measure_frames
    from amix.amix_engine.adapters.vision.profile import PROFILE_ID
    from amix.amix_engine.adapters.vision.yunet import YunetDetector
    from amix.amix_engine.domain.types import ParticipantId

    source = spec["source_path"]
    ffmpeg = spec["ffmpeg_path"]
    result_path = spec["result_path"]
    workspace = Path(spec["workspace"])
    origin = int(spec["container_start_us"])
    start = int(spec["window_start_us"])
    end = int(spec["window_end_us"])
    width = int(spec["width"])
    height = int(spec["height"])
    period = int(spec["sample_period_us"])
    rotation = spec.get("rotation_degrees")
    if rotation is not None:
        rotation = int(rotation)
    bindings = [_binding(item) for item in spec["bindings"]]
    participants = tuple(ParticipantId(value) for value in spec["participant_ids"])
    expected = (end - start) // period
    _emit({"type": "progress", "bp": 200})
    pcm = workspace / "audio.f32le"
    audio_code = subprocess.call(
        _audio_command(ffmpeg, source, pcm, start, end, origin),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if audio_code != 0:
        _fail("overlap_failed")
        return 1
    audio = np.memmap(pcm, dtype=np.float32, mode="r")
    detector = YunetDetector(spec["model_path"])
    command = _video_command(ffmpeg, source, start, end, origin, rotation, width, height)
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        frames = _frames(proc, width, height, expected)
        series = measure_frames(
            frames,
            audio,
            bindings,
            participants,
            origin_us=start,
            sample_period_us=period,
            detector=detector,
            width=width,
            height=height,
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        del audio
    if proc.returncode not in {0, None}:
        _fail("overlap_failed")
        return 1
    if len(series.scores) != expected:
        _fail("overlap_failed")
        return 1
    import cv2

    payload = {
        "profile_id": PROFILE_ID,
        "origin_us": series.origin_us,
        "sample_period_us": series.sample_period_us,
        "participant_ids": [person.value for person in series.participant_ids],
        "scores": series.scores,
        "audio_rms": series.audio_rms,
        "opencv_version": cv2.__version__,
        "model_id": spec.get("model_id"),
        "model_identity": spec.get("model_identity"),
        "model_version": spec.get("model_version"),
        "sample_fps": SAMPLE_FPS,
        "audio_rate": AUDIO_RATE,
    }
    publish_text(result_path, json.dumps(payload))
    _emit({"type": "progress", "bp": 9500})
    return 0


def _frames(proc, width: int, height: int, expected: int):
    import numpy as np

    size = width * height * 3
    last = 0
    for index in range(expected):
        raw = _read_exact(proc.stdout, size)
        if raw is None:
            break
        yield np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3)).copy()
        bp = 200 + int(7000 * (index + 1) / expected)
        if bp - last >= 100:
            last = bp
            _emit({"type": "progress", "bp": bp})
    proc.stdout.close()
    proc.wait(timeout=30)


def _read_exact(stream, size: int) -> bytes | None:
    chunks = []
    remaining = size
    while remaining:
        block = stream.read(remaining)
        if not block:
            return None
        chunks.append(block)
        remaining -= len(block)
    return b"".join(chunks)


def _binding(item: dict) -> "LayoutBinding":
    from amix.amix_engine.domain.types import LayoutBinding, ParticipantId
    from amix.amix_engine.time.clock import TimeRange

    return LayoutBinding(
        ParticipantId(item["participant_id"]),
        int(item["x"]),
        int(item["y"]),
        int(item["w"]),
        int(item["h"]),
        TimeRange(int(item["start_us"]), int(item["end_us"])),
    )


def video_command(ffmpeg: str, source: str, start_us: int, end_us: int, container_start_us: int, rotation, width: int, height: int) -> list[str]:
    return _video_command(ffmpeg, source, start_us, end_us, container_start_us, rotation, width, height)


def _video_command(ffmpeg, source, start_us, end_us, container_start_us, rotation, width, height) -> list[str]:
    from amix.amix_engine.adapters.vision.geometry import display_video_filter, duration_seconds, seek_offset_seconds

    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-noautorotate",
        "-ss", seek_offset_seconds(start_us, container_start_us),
        "-t", duration_seconds(start_us, end_us),
        "-i", source,
        "-an",
        "-vf", display_video_filter(rotation),
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-",
    ]


def _audio_command(ffmpeg, source, dest: Path, start_us, end_us, container_start_us) -> list[str]:
    from amix.amix_engine.adapters.vision.geometry import duration_seconds, seek_offset_seconds

    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", seek_offset_seconds(start_us, container_start_us),
        "-t", duration_seconds(start_us, end_us),
        "-i", source,
        "-vn", "-ac", "1", "-ar", "16000",
        "-f", "f32le",
        str(dest),
    ]


def _spec_path(args: list[str]) -> str | None:
    if len(args) == 2 and args[0] == "--spec":
        return args[1]
    return None


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _fail(code: str) -> None:
    _emit({"type": "error", "code": code})


if __name__ == "__main__":
    raise SystemExit(main())
