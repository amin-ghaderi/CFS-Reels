"""Isolated transcription process.

Stdout is NDJSON only. Diagnostics go to stderr. The model library is imported
only for a real transcription, after offline hub flags are set.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from amix.amix_engine.adapters.media.publish import publish_pid, publish_text

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

_MODES = frozenset({"transcribe", "wait", "fail", "emit"})


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    spec_path = _spec_path(args)
    if spec_path is None:
        _fail("speech_transcription_failed")
        return 1
    try:
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("speech_transcription_failed")
        return 1
    if not isinstance(spec, dict):
        _fail("speech_transcription_failed")
        return 1
    mode = spec.get("mode", "transcribe")
    if mode not in _MODES:
        _fail("speech_transcription_failed")
        return 1
    pid_path = spec.get("pid_path")
    if isinstance(pid_path, str) and pid_path:
        try:
            publish_pid(pid_path, os.getpid())
        except OSError:
            _fail("speech_transcription_failed")
            return 1
    if mode == "wait":
        _emit({"type": "ready"})
        while True:
            time.sleep(0.05)
    if mode == "fail":
        _fail("speech_transcription_failed")
        return 1
    if mode == "emit":
        return _emit_fixture(spec)
    return _transcribe(spec)


def _transcribe(spec: dict) -> int:
    source = spec.get("source_path")
    model = spec.get("model_path")
    result_path = spec.get("result_path")
    if not isinstance(source, str) or not isinstance(model, str) or not isinstance(result_path, str):
        _fail("speech_transcription_failed")
        return 1
    language = spec.get("language")
    if language is not None and not isinstance(language, str):
        _fail("invalid_language")
        return 1
    device = spec.get("device")
    compute = spec.get("compute_type")
    if not isinstance(device, str) or not isinstance(compute, str):
        _fail("invalid_speech_model")
        return 1
    from amix.amix_engine.adapters.stt.evidence import dump_evidence
    from amix.amix_engine.adapters.stt.faster_whisper import transcribe_file
    from amix.amix_engine.adapters.stt.profile import V1

    def on_segment(end_us: int) -> None:
        _emit({"type": "progress", "segment_end_us": end_us})

    try:
        evidence = transcribe_file(
            Path(source),
            Path(model),
            profile=V1,
            language=language,
            device=device,
            compute_type=compute,
            on_segment_end_us=on_segment,
        )
        publish_text(result_path, dump_evidence(evidence))
    except Exception as exc:
        _fail(classify_transcription_error(exc))
        return 1
    _emit({"type": "done"})
    return 0


def classify_transcription_error(exc: BaseException) -> str:
    """Map an operational speech failure to a stable code.

    Unknown failures stay ``speech_transcription_failed``. This does not
    report success, and it does not include the exception text.
    """
    filename = str(getattr(exc, "filename", "") or "")
    text = f"{filename} {exc}".lower()
    if isinstance(exc, FileNotFoundError) and ("ffmpeg" in text or "ffprobe" in text):
        return "ffmpeg_unavailable"
    if "ffmpeg" in text and any(token in text for token in ("not found", "no such file", "cannot find", "winerror 2")):
        return "ffmpeg_unavailable"
    if any(token in text for token in ("no audio", "audio stream", "does not contain an audio")):
        return "audio_stream_unavailable"
    if "model" in text and any(token in text for token in ("not found", "not usable", "unable to open")):
        return "invalid_speech_model"
    return "speech_transcription_failed"


def _emit_fixture(spec: dict) -> int:
    evidence_path = spec.get("evidence_path")
    result_path = spec.get("result_path")
    if not isinstance(evidence_path, str) or not isinstance(result_path, str):
        _fail("speech_transcription_failed")
        return 1
    try:
        text = Path(evidence_path).read_text(encoding="utf-8")
        publish_text(result_path, text)
    except OSError:
        _fail("speech_transcription_failed")
        return 1
    _emit({"type": "progress", "segment_end_us": 1})
    _emit({"type": "done"})
    return 0


def _spec_path(argv: list[str]) -> str | None:
    if len(argv) != 2 or argv[0] != "--spec":
        return None
    return argv[1]


def _emit(record: dict) -> None:
    sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
    sys.stdout.flush()


def _fail(code: str) -> None:
    sys.stderr.write(f"amix-stt: {code}\n")
    _emit({"type": "error", "code": code})


if __name__ == "__main__":
    raise SystemExit(main())
