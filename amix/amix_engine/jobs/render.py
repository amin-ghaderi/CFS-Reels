"""Sequence render job. One FFmpeg path for every picture treatment and canvas."""
from __future__ import annotations

import hashlib
import json
import os
import sys

from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing, ProbeFailed, ProcessCancelled
from amix.amix_engine.adapters.media.process import run_process
from amix.amix_engine.adapters.media.probe import execute_probe
from amix.amix_engine.adapters.media.proxy import progress_basis_points, progress_time_us
from amix.amix_engine.jobs.media import _record
from amix.amix_engine.jobs.runner import JobCancelled, JobContext, JobFailed
from amix.amix_engine.multicam.apply import multicam_readiness
from amix.amix_engine.editorial.sequence import sequence_fingerprint
from amix.amix_engine.multicam.compile import (
    compile_kept_render,
    compile_render,
    compile_source_program,
    ffmpeg_args,
    filter_script,
)
from amix.amix_engine.multicam.effective import (
    effective_fingerprint,
    override_fingerprint,
    resolve_effective,
)
from amix.amix_engine.multicam.framing import FramingError
from amix.amix_engine.multicam.profile import FRAMING_POLICY, PROFILE_ID, InvalidPreset, output_frame_rate, preset_from_id
from amix.amix_engine.storage.errors import MediaMissing, ProjectDatabaseInvalid

RENDER_MULTICAM = "render_multicam"
RENDER_SEQUENCE = "render_sequence"
SOURCE_PROGRAM = "source_program"
MULTICAM = "multicam"
_SPEC_KEYS = frozenset({"preset", "shot_plan_run_id", "sequence_id", "sequence_revision"})
_SEQUENCE_SPEC_KEYS = frozenset({
    "sequence_id", "visual_treatment", "render_profile_id", "sequence_revision",
})
_TEST_WORKER = "AMIX_RENDER_TEST_WORKER"


class RenderSequenceJob:
    kind = RENDER_SEQUENCE

    def run(self, ctx: JobContext) -> dict:
        sequence_id, treatment, profile_id, revision = _sequence_spec_job(ctx.spec)
        asset_id = _asset_id(ctx)
        try:
            sequence = ctx.store.load_editorial_sequence_by_id(sequence_id)
        except ProjectDatabaseInvalid as exc:
            raise JobFailed("unknown_sequence", "That sequence is not in this project.") from exc
        if sequence["media_asset_id"] != asset_id:
            raise JobFailed("unknown_sequence", "That sequence is not in this project.")
        if revision is not None and revision != sequence["revision"]:
            raise JobFailed("sequence_changed", "That edit changed before rendering.")
        return _render(
            ctx,
            preset_id=profile_id,
            treatment=treatment,
            sequence=sequence,
            requested_plan=None,
            match_plan_span=sequence["purpose"] == "primary",
        )


class RenderMulticamJob:
    kind = RENDER_MULTICAM

    def run(self, ctx: JobContext) -> dict:
        preset_id, requested_plan = _spec(ctx.spec)
        asset_id = _asset_id(ctx)
        sequence = ctx.store.load_primary_sequence(asset_id)
        requested_sequence, requested_revision = _sequence_spec(ctx.spec)
        if requested_sequence is not None and (sequence is None or requested_sequence != sequence["sequence_id"]):
            raise JobFailed("sequence_changed", "That edit is no longer current.")
        if sequence is not None and requested_revision is not None and requested_revision != sequence["revision"]:
            raise JobFailed("sequence_changed", "That edit changed before rendering.")
        return _render(
            ctx,
            preset_id=preset_id,
            treatment=MULTICAM,
            sequence=sequence,
            requested_plan=requested_plan,
            match_plan_span=True,
        )


def _render(
    ctx: JobContext,
    *,
    preset_id: str,
    treatment: str,
    sequence: dict | None,
    requested_plan: str | None,
    match_plan_span: bool,
) -> dict:
    if treatment not in {SOURCE_PROGRAM, MULTICAM}:
        raise JobFailed("invalid_visual_treatment", "That picture treatment is not available.")
    preset = _preset(preset_id)
    asset_id = _asset_id(ctx)
    asset = ctx.store.get_media(asset_id)
    if asset.role != "master":
        raise JobFailed("render_requires_source", "Rendering uses the original source media.")
    try:
        source = ctx.store.require_media(asset_id)
    except MediaMissing as exc:
        raise JobFailed("media_missing", "A media file for this project is missing.") from exc
    if not asset.probed_at or not asset.width or not asset.height:
        raise JobFailed("render_requires_probe", "Probe this media before rendering.")
    ready = multicam_readiness(ctx.store, asset_id) if treatment == MULTICAM else None
    plan_id = None
    overrides = []
    effective = []
    plan = None
    if treatment == MULTICAM:
        if ready["plan_stale"] or ready["overlap_stale"]:
            raise JobFailed("plan_stale", "The shot plan is out of date.")
        if not ready["plan_present"] or not ready["shot_plan_run_id"]:
            raise JobFailed("plan_required", "Build a shot plan before rendering.")
        plan_id = ready["shot_plan_run_id"]
        if requested_plan is not None and requested_plan != plan_id:
            raise JobFailed("plan_changed", "That shot plan is no longer the active plan.")
        plan = ctx.store.load_shot_plan(plan_id)
        records = ctx.store.list_shot_records(plan_id)
        overrides = ctx.store.list_shot_overrides(plan_id)
        effective = resolve_effective(records, overrides)
        if sequence is not None and match_plan_span:
            if sequence["source_start_us"] != plan.span.start_us or sequence["source_end_us"] != plan.span.end_us:
                raise JobFailed("sequence_changed", "That edit was built for a different plan range.")
    rate = output_frame_rate(asset.fps_num, asset.fps_den)
    container = 0 if asset.container_start_us is None else asset.container_start_us
    clips = [] if sequence is None else [
        (clip["source_start_us"], clip["source_end_us"]) for clip in sequence["clips"]
    ]
    try:
        if treatment == SOURCE_PROGRAM:
            if sequence is None:
                raise JobFailed("sequence_required", "Choose an edit before rendering.")
            compiled = compile_source_program(
                clips=clips,
                preset=preset,
                fps_num=rate[0],
                fps_den=rate[1],
                container_start_us=container,
                source_width=asset.width,
                source_height=asset.height,
                has_audio=bool(asset.audio_codec),
            )
        elif sequence is not None:
            compiled = compile_kept_render(
                shots=effective,
                clips=clips,
                bindings=ctx.store.load_layout_bindings(asset_id),
                preset=preset,
                fps_num=rate[0],
                fps_den=rate[1],
                render_start_us=plan.span.start_us,
                render_end_us=plan.span.end_us,
                container_start_us=container,
                source_width=asset.width,
                source_height=asset.height,
                has_audio=bool(asset.audio_codec),
            )
        else:
            compiled = compile_render(
                shots=effective,
                bindings=ctx.store.load_layout_bindings(asset_id),
                preset=preset,
                fps_num=rate[0],
                fps_den=rate[1],
                render_start_us=plan.span.start_us,
                render_end_us=plan.span.end_us,
                container_start_us=container,
                source_width=asset.width,
                source_height=asset.height,
                has_audio=bool(asset.audio_codec),
            )
    except FramingError as exc:
        raise JobFailed(exc.code, exc.message) from exc
    ctx.cancellation.raise_if_cancelled()
    mode = os.environ.get(_TEST_WORKER, "")
    if mode == "fail":
        raise JobFailed("render_failed", "The render did not finish.")
    tmp_dir = ctx.store.root / "exports" / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    script_path = tmp_dir / f"{ctx.job_id}.filter.txt"
    tmp_path = tmp_dir / f"{ctx.job_id}.mp4"
    final_path = ctx.store.root / "exports" / f"{ctx.job_id}.mp4"
    published = False
    try:
        script_path.write_text(filter_script(compiled), encoding="utf-8")
        if mode == "wait":
            command = [sys.executable, "-c", "import time; time.sleep(30)"]
        else:
            try:
                tools = discover_tools()
            except MediaToolMissing as exc:
                raise JobFailed("media_tool_missing", "FFmpeg tools are not available.") from exc
            command = ffmpeg_args(str(tools.ffmpeg), str(source), script_path, tmp_path, compiled)
        progress = 0
        duration = compiled.end_us - compiled.start_us

        def on_line(line: str) -> None:
            nonlocal progress
            observed = progress_time_us(line)
            if observed is None:
                return
            progress = progress_basis_points(observed, duration, progress)
            ctx.report_progress(min(progress, 9999))

        try:
            completed = run_process(command, ctx.cancellation, on_line=on_line)
        except ProcessCancelled as exc:
            raise JobCancelled() from exc
        if mode == "wait":
            raise JobFailed("render_failed", "The render did not finish.")
        if completed.code != 0 or not tmp_path.is_file():
            raise JobFailed("render_failed", "The render did not finish.")
        ctx.cancellation.raise_if_cancelled()
        try:
            metadata = execute_probe(tools.ffprobe, tmp_path, ctx.cancellation)
        except ProbeFailed as exc:
            raise JobFailed("render_failed", "The rendered file could not be checked.") from exc
        except ProcessCancelled as exc:
            raise JobCancelled() from exc
        if metadata.width != compiled.output_width or metadata.height != compiled.output_height:
            raise JobFailed("render_failed", "The rendered file could not be checked.")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, final_path)
        stat = final_path.stat()
        record = _record(metadata, stat.st_size, stat.st_mtime_ns, tools.ffprobe_version)
        export_id = ctx.store.publish_export(
            asset_id,
            record,
            relative_path=f"exports/{ctx.job_id}.mp4",
            display_name=f"{preset.preset_id}-{ctx.job_id[:8]}.mp4",
            job_id=ctx.job_id,
        )
        published = True
        ctx.store.set_job_progress(ctx.job_id, 10000)
        source_stat = source.stat()
        fingerprint = None if sequence is None else sequence_fingerprint(
            sequence["source_start_us"],
            sequence["source_end_us"],
            clips,
        )
        camera = treatment == MULTICAM
        return {
            "activated": True,
            "export_media_asset_id": export_id,
            "visual_treatment": treatment,
            "camera_analysis_used": camera,
            "shot_plan_run_id": plan_id if camera else None,
            "override_fingerprint": override_fingerprint(overrides) if camera else None,
            "effective_fingerprint": effective_fingerprint(effective) if camera else None,
            "layout_fingerprint": None if ready is None else ready["layout_fingerprint"],
            "protected_fingerprint": None if ready is None else ready["protected_fingerprint"],
            "sequence_id": None if sequence is None else sequence["sequence_id"],
            "sequence_purpose": None if sequence is None else sequence["purpose"],
            "sequence_revision": None if sequence is None else sequence["revision"],
            "sequence_fingerprint": fingerprint,
            "clip_fingerprint": _clip_fingerprint(clips),
            "profile_id": PROFILE_ID,
            "preset_id": preset.preset_id,
            "width": compiled.output_width,
            "height": compiled.output_height,
            "fps_num": compiled.fps_num,
            "fps_den": compiled.fps_den,
            "framing_policy": FRAMING_POLICY,
            "ffmpeg_version": tools.ffmpeg_version,
            "source_size": source_stat.st_size,
            "source_mtime_ns": source_stat.st_mtime_ns,
            "relative_path": f"exports/{ctx.job_id}.mp4",
        }
    finally:
        script_path.unlink(missing_ok=True)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        if not published and final_path.exists() and mode != "wait":
            final_path.unlink(missing_ok=True)


def _spec(spec: dict) -> tuple[str, str | None]:
    if not isinstance(spec, dict) or set(spec) - _SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    preset = spec.get("preset")
    if not isinstance(preset, str):
        raise JobFailed("invalid_render_preset", "That output format is not available.")
    plan_id = spec.get("shot_plan_run_id")
    if plan_id is not None and not isinstance(plan_id, str):
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    return preset, plan_id


def _sequence_spec_job(spec: dict) -> tuple[str, str, str, int | None]:
    if not isinstance(spec, dict) or set(spec) - _SEQUENCE_SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    sequence_id = spec.get("sequence_id")
    treatment = spec.get("visual_treatment")
    profile_id = spec.get("render_profile_id")
    if not isinstance(sequence_id, str) or not isinstance(treatment, str) or not isinstance(profile_id, str):
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    revision = spec.get("sequence_revision")
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int)):
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    return sequence_id, treatment, profile_id, revision


def _clip_fingerprint(clips: list[tuple[int, int]]) -> str:
    raw = json.dumps(
        [{"start_us": start, "end_us": end} for start, end in clips],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sequence_spec(spec: dict) -> tuple[str | None, int | None]:
    sequence_id = spec.get("sequence_id")
    if sequence_id is not None and not isinstance(sequence_id, str):
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    revision = spec.get("sequence_revision")
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int)):
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    return sequence_id, revision


def _preset(preset_id: str):
    try:
        return preset_from_id(preset_id)
    except InvalidPreset as exc:
        raise JobFailed(exc.code, "That output format is not available.") from exc


def sequence_render_readiness(store, asset_id: str, sequence_id: str) -> dict:
    from amix.amix_engine.adapters.media.discovery import discover_tools
    from amix.amix_engine.adapters.media.errors import MediaToolMissing

    sequence = store.load_editorial_sequence_by_id(sequence_id)
    if sequence["media_asset_id"] != asset_id:
        raise ProjectDatabaseInvalid(f"unknown sequence {sequence_id}")
    asset = store.get_media(asset_id)
    try:
        store.require_media(asset_id)
        source_missing = asset.role != "master" or not asset.probed_at
    except MediaMissing:
        source_missing = True
    try:
        discover_tools()
        ffmpeg_ready = True
    except MediaToolMissing:
        ffmpeg_ready = False
    source_reason = None
    if source_missing:
        source_reason = "source_missing"
    elif not ffmpeg_ready:
        source_reason = "ffmpeg_missing"
    elif not sequence["clips"]:
        source_reason = "empty_sequence"
    ready = multicam_readiness(store, asset_id)
    multicam_reason = source_reason
    if multicam_reason is None:
        if not ready["plan_present"]:
            multicam_reason = "shot_plan_missing"
        elif ready["plan_stale"]:
            multicam_reason = "shot_plan_stale"
        elif ready["overlap_stale"]:
            multicam_reason = "layout_incompatible"
    return {
        "source_program_ready": source_reason is None,
        "multicam_ready": multicam_reason is None,
        "source_program_reason": source_reason,
        "multicam_reason": multicam_reason,
        "ffmpeg_ready": ffmpeg_ready,
    }


def _asset_id(ctx: JobContext) -> str:
    if not ctx.media_asset_id:
        raise JobFailed("unknown_media_asset", "That media file is no longer in this project.")
    return ctx.media_asset_id
