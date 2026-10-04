"""Transcription job. The handler launches a worker. It does not load a model."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing, ProcessCancelled
from amix.amix_engine.adapters.media.process import run_process
from amix.amix_engine.adapters.stt.evidence import SttEvidenceError, load_evidence
from amix.amix_engine.adapters.stt.profile import InvalidLanguage, InvalidProfile, profile_from_spec, requested_language
from amix.amix_engine.adapters.stt.progress import transcription_progress_bp
from amix.amix_engine.jobs.runner import JobCancelled, JobContext, JobFailed
from amix.amix_engine.stt import activate_transcription
from amix.amix_engine.stt.resolver import SpeechResourceError, resolve_speech_model
from amix.amix_engine.storage.errors import MediaMissing

TRANSCRIBE = "transcribe"
_SPEC_KEYS = frozenset({"profile", "language"})
_TEST_MODES = frozenset({"wait", "fail", "emit"})
_TEST_WORKER = "AMIX_STT_TEST_WORKER"
_TEST_EVIDENCE = "AMIX_STT_TEST_EVIDENCE"


class TranscribeJob:
    kind = TRANSCRIBE

    def run(self, ctx: JobContext) -> dict:
        language = _language(ctx.spec)
        profile = _profile(ctx.spec)
        asset_id = _asset_id(ctx)
        asset = ctx.store.get_media(asset_id)
        if asset.role != "master":
            raise JobFailed("transcription_requires_source", "Transcription uses the original source media.")
        try:
            source = ctx.store.require_media(asset_id)
        except MediaMissing as exc:
            raise JobFailed("media_missing", "A media file for this project is missing.") from exc
        if asset.probed_at and not asset.audio_codec:
            raise JobFailed("media_has_no_audio", "This media has no audio to transcribe.")
        try:
            model = resolve_speech_model()
        except SpeechResourceError as exc:
            raise JobFailed(exc.code, exc.message) from exc
        ctx.cancellation.raise_if_cancelled()
        temp = ctx.store.private / ".stt" / ctx.job_id
        temp.mkdir(parents=True, exist_ok=True)
        result_path = temp / "result.json"
        spec_path = temp / "worker.json"
        pid_path = temp / "worker.pid"
        mode = _test_mode()
        worker_spec = {
            "mode": mode,
            "source_path": str(source),
            "model_path": model.local_path,
            "device": model.device,
            "compute_type": model.compute_type,
            "language": language,
            "profile": profile.profile_id,
            "result_path": str(result_path),
            "pid_path": str(pid_path),
        }
        if mode == "emit":
            worker_spec["evidence_path"] = os.environ.get(_TEST_EVIDENCE, "")
        spec_path.write_text(json.dumps(worker_spec), encoding="utf-8")
        progress = 0
        error_code: str | None = None

        def on_line(line: str) -> None:
            nonlocal progress, error_code
            if not line:
                return
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return
            if not isinstance(record, dict):
                error_code = "speech_transcription_failed"
                return
            kind = record.get("type")
            if kind == "error" and isinstance(record.get("code"), str):
                error_code = record["code"]
                return
            if kind != "progress":
                return
            end_us = record.get("segment_end_us")
            if isinstance(end_us, bool) or not isinstance(end_us, int):
                return
            updated = transcription_progress_bp(end_us, asset.duration_us, progress)
            if updated > progress:
                progress = updated
                ctx.report_progress(progress)

        try:
            try:
                completed = run_process(
                    worker_command(spec_path),
                    ctx.cancellation,
                    on_line=on_line,
                    env=speech_worker_env(),
                )
            except ProcessCancelled as exc:
                raise JobCancelled() from exc
            if error_code:
                raise JobFailed(error_code, _message(error_code))
            if completed.code != 0:
                raise JobFailed("speech_transcription_failed", "Transcription did not finish.")
            ctx.cancellation.raise_if_cancelled()
            try:
                ctx.store.require_media(asset_id)
            except MediaMissing as exc:
                raise JobFailed("media_missing", "A media file for this project is missing.") from exc
            try:
                evidence = load_evidence(result_path.read_text(encoding="utf-8"))
            except (OSError, SttEvidenceError) as exc:
                raise JobFailed("speech_transcription_failed", "Transcription did not finish.") from exc
            ctx.cancellation.raise_if_cancelled()
            run_id = activate_transcription(
                ctx.store,
                asset,
                source,
                evidence,
                model,
                profile,
                requested_language=language,
            )
            ctx.store.set_job_progress(ctx.job_id, 10000)
            return {
                "activated": True,
                "transcript_run_id": run_id,
                "word_count": len(evidence.words),
            }
        finally:
            shutil.rmtree(temp, ignore_errors=True)


def speech_worker_env() -> dict[str, str]:
    """Give the speech worker the same FFmpeg the media tools already use.

    faster-whisper decodes audio by running ``ffmpeg`` from PATH. Probe and
    proxy resolve the saved tool directory themselves. The worker does not.
    """
    env = dict(os.environ)
    try:
        tools = discover_tools()
    except MediaToolMissing:
        return env
    directory = str(tools.ffmpeg.parent)
    current = env.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if directory not in parts:
        env["PATH"] = directory + (os.pathsep + current if current else "")
    return env


def worker_command(spec_path: Path) -> list[str]:
    """The same interpreter, one module. The job spec cannot replace this command."""
    return [sys.executable, "-m", "amix.amix_engine.workers.transcribe", "--spec", str(spec_path)]


def _test_mode() -> str:
    mode = os.environ.get(_TEST_WORKER, "")
    if mode in _TEST_MODES:
        return mode
    return "transcribe"


def _language(spec: dict) -> str | None:
    if not isinstance(spec, dict) or set(spec) - _SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    try:
        return requested_language(spec.get("language"))
    except InvalidLanguage as exc:
        raise JobFailed(exc.code, "That language code is not supported. Use Auto or a Whisper language code.") from exc


def _profile(spec: dict):
    try:
        return profile_from_spec(spec.get("profile"))
    except InvalidProfile as exc:
        raise JobFailed(exc.code, "That transcription profile is not available.") from exc


def _asset_id(ctx: JobContext) -> str:
    if not ctx.media_asset_id:
        raise JobFailed("unknown_media_asset", "That media file is no longer in this project.")
    return ctx.media_asset_id


def _message(code: str) -> str:
    return {
        "invalid_language": "That language code is not supported. Use Auto or a Whisper language code.",
        "invalid_speech_model": "The configured speech model cannot be used.",
        "speech_model_missing": "Speech model not installed.",
        "speech_runtime_unavailable": "The speech runtime is not available.",
        "media_missing": "A media file for this project is missing.",
        "media_has_no_audio": "This media has no audio to transcribe.",
        "audio_stream_unavailable": "This media has no audio to transcribe.",
        "ffmpeg_unavailable": "FFmpeg is not available.",
        "worker_failed": "Transcription did not finish.",
        "speech_transcription_failed": "Transcription did not finish.",
    }.get(code, "Transcription did not finish.")
