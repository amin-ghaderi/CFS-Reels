"""Isolated diarization process.

Stdout is NDJSON only. The clustering library is imported only for a real run.
The parent cancels this process tree, which also stops the FFmpeg child.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_MODES = frozenset({"diarize", "wait", "fail", "emit"})


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    spec_path = _spec_path(args)
    if spec_path is None:
        _fail("diarization_failed")
        return 1
    try:
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("diarization_failed")
        return 1
    if not isinstance(spec, dict):
        _fail("diarization_failed")
        return 1
    mode = spec.get("mode", "diarize")
    if mode not in _MODES:
        _fail("diarization_failed")
        return 1
    pid_path = spec.get("pid_path")
    if isinstance(pid_path, str) and pid_path:
        try:
            Path(pid_path).write_text(str(os.getpid()), encoding="ascii")
        except OSError:
            _fail("diarization_failed")
            return 1
    if mode == "wait":
        _emit({"type": "ready"})
        while True:
            time.sleep(0.05)
    if mode == "fail":
        _fail("diarization_failed")
        return 1
    if mode == "emit":
        return _emit_fixture(spec)
    return _diarize(spec)


def _diarize(spec: dict) -> int:
    source = spec.get("source_path")
    result_path = spec.get("result_path")
    ffmpeg = spec.get("ffmpeg_path")
    origin = spec.get("source_start_us")
    workspace = spec.get("workspace")
    if (
        not isinstance(source, str)
        or not isinstance(result_path, str)
        or not isinstance(ffmpeg, str)
        or not isinstance(workspace, str)
        or isinstance(origin, bool)
        or not isinstance(origin, int)
    ):
        _fail("diarization_failed")
        return 1
    pcm = Path(workspace) / "audio.f32le"
    _emit({"type": "progress", "bp": 500})
    code = _decode(ffmpeg, source, pcm)
    if code != 0:
        _fail("diarization_failed")
        return 1
    _emit({"type": "progress", "bp": 2500})
    try:
        import numpy as np

        from amix.amix_engine.adapters.diarize.mfcc_kmeans import DECODE_CONFIG, FEATURE_CONFIG, N_SPEAKERS, diarize_pcm
        from amix.amix_engine.adapters.diarize.profile import PROFILE_ID

        audio = np.memmap(pcm, dtype=np.float32, mode="r")
        _emit({"type": "progress", "bp": 4000})
        result = diarize_pcm(audio, origin)
        del audio
    except Exception:
        _fail("diarization_failed")
        return 1
    _emit({"type": "progress", "bp": 9000})
    payload = {
        "profile_id": PROFILE_ID,
        "cluster_count": N_SPEAKERS,
        "window_start_us": origin,
        "window_end_us": origin + result.window_end_offset_us,
        "segments": [
            {"cluster_key": row.cluster_id, "start_us": row.start_us, "end_us": row.end_us}
            for row in result.segments
        ],
        "diagnostics": {
            "speech_windows": result.speech_windows,
            "silence_windows": result.silence_windows,
            "cluster_count": N_SPEAKERS,
            "overlap_supported": False,
            "feature_config": FEATURE_CONFIG,
            "decode": DECODE_CONFIG,
        },
    }
    try:
        Path(result_path).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        _fail("diarization_failed")
        return 1
    _emit({"type": "progress", "bp": 9500})
    return 0


def _decode(ffmpeg: str, source: str, dest: Path) -> int:
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    process = subprocess.Popen(
        [ffmpeg, "-v", "error", "-i", source, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", str(dest)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process.wait()


def _emit_fixture(spec: dict) -> int:
    evidence = spec.get("evidence_path")
    result_path = spec.get("result_path")
    origin = spec.get("source_start_us")
    if not isinstance(evidence, str) or not isinstance(result_path, str):
        _fail("diarization_failed")
        return 1
    if isinstance(origin, bool) or not isinstance(origin, int):
        origin = 0
    try:
        payload = json.loads(Path(evidence).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("diarization_failed")
        return 1
    if not isinstance(payload, dict):
        _fail("diarization_failed")
        return 1
    payload.setdefault("window_start_us", origin)
    payload.setdefault("window_end_us", origin)
    _emit({"type": "progress", "bp": 9000})
    try:
        Path(result_path).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        _fail("diarization_failed")
        return 1
    return 0


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
