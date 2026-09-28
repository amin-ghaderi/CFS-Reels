"""Diarization job. Clustering runs in the worker, not in this process."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from amix.amix_engine.adapters.diarize.profile import InvalidProfile, profile_from_spec
from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing, ProcessCancelled
from amix.amix_engine.adapters.media.process import run_process
from amix.amix_engine.domain.types import DiarizationSegment
from amix.amix_engine.jobs.runner import JobCancelled, JobContext, JobFailed
from amix.amix_engine.storage.errors import MediaMissing
from amix.amix_engine.time.clock import TimeRange

DIARIZE_AUDIO = "diarize_audio"
_SPEC_KEYS = frozenset({"profile"})
_TEST_MODES = frozenset({"wait", "fail", "emit"})
_TEST_WORKER = "AMIX_DIARIZE_TEST_WORKER"
_TEST_EVIDENCE = "AMIX_DIARIZE_TEST_EVIDENCE"


class DiarizeAudioJob:
    kind = DIARIZE_AUDIO

    def run(self, ctx: JobContext) -> dict:
        profile = _profile(ctx.spec)
        asset_id = _asset_id(ctx)
        asset = ctx.store.get_media(asset_id)
        if asset.role != "master":
            raise JobFailed("diarization_requires_source", "Speaker analysis uses the original source media.")
        try:
            source = ctx.store.require_media(asset_id)
        except MediaMissing as exc:
            raise JobFailed("media_missing", "A media file for this project is missing.") from exc
        if asset.probed_at and not asset.audio_codec:
            raise JobFailed("media_has_no_audio", "This media has no audio to analyze for speakers.")
        if ctx.store.active_transcript(asset_id) is None:
            raise JobFailed("no_active_transcript", "No transcript is available for this media yet.")
        ctx.cancellation.raise_if_cancelled()
        mode = _test_mode()
        ffmpeg_path = ""
        ffmpeg_version = ""
        if mode == "diarize":
            try:
                tools = discover_tools()
            except MediaToolMissing as exc:
                raise JobFailed("media_tool_missing", "FFmpeg tools are not available.") from exc
            ffmpeg_path = str(tools.ffmpeg)
            ffmpeg_version = tools.ffmpeg_version
        origin = 0 if asset.container_start_us is None else asset.container_start_us
        temp = ctx.store.root / ".diarize" / ctx.job_id
        temp.mkdir(parents=True, exist_ok=True)
        result_path = temp / "result.json"
        spec_path = temp / "worker.json"
        pid_path = temp / "worker.pid"
        worker_spec = {
            "mode": mode,
            "source_path": str(source),
            "source_start_us": origin,
            "profile": profile.profile_id,
            "ffmpeg_path": ffmpeg_path,
            "workspace": str(temp),
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
                error_code = "diarization_failed"
                return
            if not isinstance(record, dict):
                error_code = "diarization_failed"
                return
            if record.get("type") == "error" and isinstance(record.get("code"), str):
                error_code = record["code"]
                return
            if record.get("type") != "progress":
                return
            value = record.get("bp")
            if isinstance(value, bool) or not isinstance(value, int):
                return
            if value > progress:
                progress = value
                ctx.report_progress(min(progress, 9999))

        try:
            try:
                completed = run_process(worker_command(spec_path), ctx.cancellation, on_line=on_line)
            except ProcessCancelled as exc:
                raise JobCancelled() from exc
            if error_code:
                raise JobFailed(error_code, _message(error_code))
            if completed.code != 0:
                raise JobFailed("diarization_failed", "Speaker analysis did not finish.")
            ctx.cancellation.raise_if_cancelled()
            try:
                ctx.store.require_media(asset_id)
            except MediaMissing as exc:
                raise JobFailed("media_missing", "A media file for this project is missing.") from exc
            try:
                evidence = _load_result(result_path.read_text(encoding="utf-8"), profile.profile_id, profile.cluster_count)
            except (OSError, ValueError) as exc:
                raise JobFailed("diarization_failed", "Speaker analysis did not finish.") from exc
            ctx.cancellation.raise_if_cancelled()
            stat = source.stat()
            fingerprint = hashlib.sha256(
                f"{stat.st_size}:{stat.st_mtime_ns}:{profile.profile_id}:{origin}".encode("ascii")
            ).hexdigest()
            end_us = evidence["window_end_us"]
            if asset.duration_us is not None:
                end_us = origin + asset.duration_us
            if end_us < origin:
                end_us = origin
            config = {
                "profile_id": profile.profile_id,
                "implementation_version": profile.implementation_version,
                "cluster_count": profile.cluster_count,
                "source_container_start_us": origin,
                "clock": "source_container_start",
                "ffmpeg_version": ffmpeg_version,
                "feature_config": evidence["diagnostics"].get("feature_config", {}),
                "decode": evidence["diagnostics"].get("decode", {}),
                "speech_windows": evidence["diagnostics"].get("speech_windows"),
                "silence_windows": evidence["diagnostics"].get("silence_windows"),
                "overlap_supported": False,
            }
            run_id = ctx.store.publish_diarization(
                asset_id=asset_id,
                segments=evidence["segments"],
                algorithm_id=profile.profile_id,
                algorithm_version=profile.implementation_version,
                fingerprint=fingerprint,
                window=TimeRange(origin, end_us),
                config=config,
            )
            ctx.store.set_job_progress(ctx.job_id, 10000)
            return {"activated": True, "diarization_run_id": run_id, "segment_count": len(evidence["segments"])}
        finally:
            shutil.rmtree(temp, ignore_errors=True)


def worker_command(spec_path: Path) -> list[str]:
    return [sys.executable, "-m", "amix.amix_engine.workers.diarize", "--spec", str(spec_path)]


def _load_result(text: str, profile_id: str, cluster_count: int) -> dict:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("result")
    if payload.get("profile_id") != profile_id:
        raise ValueError("profile")
    if payload.get("cluster_count") != cluster_count:
        raise ValueError("clusters")
    start = payload.get("window_start_us")
    end = payload.get("window_end_us")
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        raise ValueError("window")
    if end < start:
        raise ValueError("window")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("segments")
    segments: list[DiarizationSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            raise ValueError("segment")
        if set(item) - {"cluster_key", "start_us", "end_us"}:
            raise ValueError("segment")
        key = item.get("cluster_key")
        seg_start = item.get("start_us")
        seg_end = item.get("end_us")
        if not isinstance(key, str) or not key.startswith("SPEAKER_"):
            raise ValueError("cluster")
        if isinstance(seg_start, bool) or isinstance(seg_end, bool):
            raise ValueError("time")
        if not isinstance(seg_start, int) or not isinstance(seg_end, int) or seg_end <= seg_start:
            raise ValueError("time")
        segments.append(DiarizationSegment(seg_start, seg_end, key))
    diagnostics = payload.get("diagnostics")
    if diagnostics is None:
        diagnostics = {}
    if not isinstance(diagnostics, dict):
        raise ValueError("diagnostics")
    return {
        "segments": segments,
        "window_start_us": start,
        "window_end_us": end,
        "diagnostics": diagnostics,
    }


def _test_mode() -> str:
    mode = os.environ.get(_TEST_WORKER, "")
    if mode in _TEST_MODES:
        return mode
    return "diarize"


def _profile(spec: dict):
    if not isinstance(spec, dict) or set(spec) - _SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    try:
        return profile_from_spec(spec.get("profile"))
    except InvalidProfile as exc:
        raise JobFailed(exc.code, "That speaker-analysis profile is not available.") from exc


def _asset_id(ctx: JobContext) -> str:
    if not ctx.media_asset_id:
        raise JobFailed("unknown_media_asset", "That media file is no longer in this project.")
    return ctx.media_asset_id


def _message(code: str) -> str:
    if code == "invalid_diarization_profile":
        return "That speaker-analysis profile is not available."
    return "Speaker analysis did not finish."
