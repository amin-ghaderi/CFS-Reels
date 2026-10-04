"""Overlap job. YuNet runs in the worker, not in this process."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing, ProcessCancelled
from amix.amix_engine.adapters.media.process import run_process
from amix.amix_engine.adapters.vision.geometry import participants_in_window
from amix.amix_engine.adapters.vision.profile import InvalidProfile, profile_config, profile_from_spec
from amix.amix_engine.adapters.vision.resolver import VisionResourceError, resolve_vision_model
from amix.amix_engine.analysis.overlap import overlap_regions
from amix.amix_engine.domain.types import LipActivitySeries, ParticipantId
from amix.amix_engine.jobs.runner import JobCancelled, JobContext, JobFailed
from amix.amix_engine.layout import layout_fingerprint
from amix.amix_engine.storage.errors import MediaMissing
from amix.amix_engine.time.clock import TimeRange

DETECT_OVERLAP = "detect_overlap"
_SPEC_KEYS = frozenset({"profile", "start_us", "end_us"})
_TEST_MODES = frozenset({"wait", "fail", "emit"})
_TEST_WORKER = "AMIX_OVERLAP_TEST_WORKER"
_TEST_EVIDENCE = "AMIX_OVERLAP_TEST_EVIDENCE"
_PERIOD_US = 125_000


class DetectOverlapJob:
    kind = DETECT_OVERLAP

    def run(self, ctx: JobContext) -> dict:
        profile = _profile(ctx.spec)
        asset_id = _asset_id(ctx)
        asset = ctx.store.get_media(asset_id)
        if asset.role != "master":
            raise JobFailed("overlap_requires_source", "Overlap analysis uses the original source media.")
        try:
            source = ctx.store.require_media(asset_id)
        except MediaMissing as exc:
            raise JobFailed("media_missing", "A media file for this project is missing.") from exc
        window = _window(asset, ctx.spec)
        bindings = ctx.store.load_layout_bindings(asset_id)
        people = participants_in_window(bindings, window.start_us, window.end_us)
        if len(people) < profile.min_visible_participants:
            raise JobFailed("insufficient_layout", "At least two participant regions are required.")
        records = ctx.store.list_layout_records(asset_id)
        layout_id = layout_fingerprint(records)
        ctx.cancellation.raise_if_cancelled()
        mode = _test_mode()
        model = None
        ffmpeg_path = ""
        ffmpeg_version = ""
        if mode == "extract":
            if not asset.probed_at or not asset.width or not asset.height:
                raise JobFailed("overlap_requires_probe", "Probe this media before overlap analysis.")
            if not asset.video_codec:
                raise JobFailed("overlap_requires_video", "This media has no video to analyze.")
            if not asset.audio_codec:
                raise JobFailed("media_has_no_audio", "This media has no audio to analyze.")
            try:
                model = resolve_vision_model()
            except VisionResourceError as exc:
                raise JobFailed(exc.code, exc.message) from exc
            try:
                tools = discover_tools()
            except MediaToolMissing as exc:
                raise JobFailed("media_tool_missing", "FFmpeg tools are not available.") from exc
            ffmpeg_path = str(tools.ffmpeg)
            ffmpeg_version = tools.ffmpeg_version
        origin = 0 if asset.container_start_us is None else asset.container_start_us
        temp = ctx.store.private / ".overlap" / ctx.job_id
        temp.mkdir(parents=True, exist_ok=True)
        result_path = temp / "activity.json"
        spec_path = temp / "worker.json"
        pid_path = temp / "worker.pid"
        worker_spec = {
            "mode": mode,
            "source_path": str(source),
            "container_start_us": origin,
            "window_start_us": window.start_us,
            "window_end_us": window.end_us,
            "sample_period_us": _PERIOD_US,
            "width": asset.width or 0,
            "height": asset.height or 0,
            "rotation_degrees": asset.rotation_degrees,
            "ffmpeg_path": ffmpeg_path,
            "workspace": str(temp),
            "result_path": str(result_path),
            "pid_path": str(pid_path),
            "child_pid_path": str(temp / "child.pid"),
            "participant_ids": [person.value for person in people],
            "bindings": [
                {
                    "participant_id": binding.participant_id.value,
                    "start_us": binding.span.start_us,
                    "end_us": binding.span.end_us,
                    "x": binding.x,
                    "y": binding.y,
                    "w": binding.w,
                    "h": binding.h,
                }
                for binding in bindings
            ],
        }
        if model is not None:
            worker_spec["model_path"] = model.local_path
            worker_spec["model_id"] = model.model_id
            worker_spec["model_identity"] = model.identity
            worker_spec["model_version"] = model.version
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
                error_code = "overlap_failed"
                return
            if not isinstance(record, dict):
                error_code = "overlap_failed"
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
                raise JobFailed("overlap_failed", "Overlap analysis did not finish.")
            ctx.cancellation.raise_if_cancelled()
            try:
                loaded = _load_activity(result_path.read_text(encoding="utf-8"), window, people, profile.profile_id)
            except (OSError, ValueError) as exc:
                raise JobFailed("overlap_failed", "Overlap analysis did not finish.") from exc
            try:
                regions = overlap_regions(loaded.series, window)
            except ValueError as exc:
                raise JobFailed("overlap_failed", "Overlap analysis did not finish.") from exc
            ctx.cancellation.raise_if_cancelled()
            stat = source.stat()
            model_identity = loaded.model_identity
            fingerprint = hashlib.sha256(
                json.dumps({
                    "layout": layout_id,
                    "model": model_identity,
                    "profile": profile.profile_id,
                    "sample_period_us": _PERIOD_US,
                    "source_mtime_ns": stat.st_mtime_ns,
                    "source_size": stat.st_size,
                    "window_end_us": window.end_us,
                    "window_start_us": window.start_us,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            config = {
                **profile_config(profile),
                "implementation_version": profile.implementation_version,
                "window_start_us": window.start_us,
                "window_end_us": window.end_us,
                "source_container_start_us": origin,
                "source_size": stat.st_size,
                "source_mtime_ns": stat.st_mtime_ns,
                "layout_fingerprint": layout_id,
                "coordinate_space": "display_pixels",
                "model_id": loaded.model_id,
                "model_identity": model_identity,
                "model_version": loaded.model_version,
                "opencv_version": loaded.opencv_version,
                "ffmpeg_version": ffmpeg_version,
                "sample_fps": profile.sample_fps,
                "sample_period_us": _PERIOD_US,
                "activity_retained": False,
            }
            run_id = ctx.store.publish_overlap(
                asset_id=asset_id,
                regions=regions,
                algorithm_id=profile.profile_id,
                algorithm_version=profile.implementation_version,
                fingerprint=fingerprint,
                window=window,
                config=config,
            )
            ctx.store.set_job_progress(ctx.job_id, 10000)
            return {"activated": True, "overlap_run_id": run_id, "region_count": len(regions)}
        finally:
            shutil.rmtree(temp, ignore_errors=True)


def worker_command(spec_path: Path) -> list[str]:
    return [sys.executable, "-m", "amix.amix_engine.workers.overlap", "--spec", str(spec_path)]


class _Loaded:
    def __init__(self, series: LipActivitySeries, model_id, model_identity, model_version, opencv_version) -> None:
        self.series = series
        self.model_id = model_id
        self.model_identity = model_identity
        self.model_version = model_version
        self.opencv_version = opencv_version


def _load_activity(text: str, window: TimeRange, people: tuple[ParticipantId, ...], profile_id: str) -> _Loaded:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("result")
    if payload.get("profile_id") not in {None, profile_id}:
        raise ValueError("profile")
    if payload.get("origin_us") != window.start_us or payload.get("sample_period_us") != _PERIOD_US:
        raise ValueError("window")
    columns = payload.get("participant_ids")
    if columns != [person.value for person in people]:
        raise ValueError("participants")
    scores = payload.get("scores")
    rms = payload.get("audio_rms")
    if not isinstance(scores, list) or not isinstance(rms, list) or len(scores) != len(rms):
        raise ValueError("activity")
    rows = []
    for row in scores:
        if not isinstance(row, list) or len(row) != len(people):
            raise ValueError("activity")
        rows.append(tuple(float(value) for value in row))
    series = LipActivitySeries(
        window.start_us,
        _PERIOD_US,
        people,
        tuple(rows),
        tuple(float(value) for value in rms),
    )
    covered = series.origin_us + len(series.scores) * series.sample_period_us
    if covered != window.end_us:
        raise ValueError("length")
    loaded = _Loaded(
        series,
        payload.get("model_id"),
        payload.get("model_identity") or "test",
        payload.get("model_version"),
        payload.get("opencv_version") or "test",
    )
    return loaded


def _window(asset, spec: dict) -> TimeRange:
    if not isinstance(spec, dict) or set(spec) - _SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    start = spec.get("start_us", None)
    end = spec.get("end_us", None)
    if (start is None) != (end is None):
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    origin = 0 if asset.container_start_us is None else asset.container_start_us
    if start is None:
        if asset.duration_us is None:
            raise JobFailed("invalid_analysis_window", "This media has no duration to analyze.")
        start = origin
        end = origin + int(asset.duration_us)
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        raise JobFailed("invalid_analysis_window", "The analysis window is not valid.")
    if end <= start or start < origin:
        raise JobFailed("invalid_analysis_window", "The analysis window is not valid.")
    if asset.duration_us is not None and end > origin + int(asset.duration_us):
        raise JobFailed("invalid_analysis_window", "The analysis window is outside this media.")
    frames = (end - start) // _PERIOD_US
    if frames < 1:
        raise JobFailed("invalid_analysis_window", "The analysis window is shorter than one sample.")
    return TimeRange(start, start + frames * _PERIOD_US)


def _test_mode() -> str:
    mode = os.environ.get(_TEST_WORKER, "")
    if mode in _TEST_MODES:
        return mode
    return "extract"


def _profile(spec: dict):
    if not isinstance(spec, dict) or set(spec) - _SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    try:
        return profile_from_spec(spec.get("profile"))
    except InvalidProfile as exc:
        raise JobFailed(exc.code, "That overlap profile is not available.") from exc


def _asset_id(ctx: JobContext) -> str:
    if not ctx.media_asset_id:
        raise JobFailed("unknown_media_asset", "That media file is no longer in this project.")
    return ctx.media_asset_id


def _message(code: str) -> str:
    if code == "vision_model_missing":
        return "Face model not installed."
    return "Overlap analysis did not finish."
