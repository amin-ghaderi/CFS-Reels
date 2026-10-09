"""Probe and preview-proxy jobs. They call the media adapter. They do not build shell strings."""
from __future__ import annotations

import logging
import os

from amix.amix_engine.adapters.media.compatible import source_directly_playable
from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing, ProbeFailed, ProcessCancelled
from amix.amix_engine.adapters.media.process import run_process
from amix.amix_engine.adapters.media.probe import PROBE_CONFIG, ProbeMetadata, execute_probe
from amix.amix_engine.adapters.media.proxy import (
    PROXY_PROFILE,
    TIMESTAMP_POLICY,
    progress_basis_points,
    progress_time_us,
    proxy_command,
)
from amix.amix_engine.jobs.runner import JobCancelled, JobContext, JobFailed
from amix.amix_engine.storage.errors import MediaMissing
from amix.amix_engine.storage.jobs import CANCEL_REQUESTED, FAILED, QUEUED, RUNNING, StoredJob
from amix.amix_engine.storage.project import MediaProbeRecord, ProjectStore, StoredMedia

log = logging.getLogger("amix.media")

MEDIA_PROBE = "media_probe"
GENERATE_PROXY = "generate_proxy"

_ACTIVE = frozenset({QUEUED, RUNNING, CANCEL_REQUESTED})


class MediaProbeJob:
    kind = MEDIA_PROBE

    def run(self, ctx: JobContext) -> dict:
        if ctx.spec:
            raise JobFailed("job_spec_rejected", "The job request was rejected.")
        asset_id = _asset_id(ctx)
        ctx.report_progress(0)
        path = _existing(ctx.store, asset_id)
        tools = _tools()
        stat = path.stat()
        try:
            metadata = execute_probe(tools.ffprobe, path, ctx.cancellation)
        except ProcessCancelled as exc:
            raise JobCancelled() from exc
        except ProbeFailed as exc:
            log.info("probe failed")
            raise JobFailed("media_probe_failed", "The media file could not be analyzed.") from exc
        ctx.cancellation.raise_if_cancelled()
        stored = ctx.store.apply_probe(asset_id, _record(metadata, stat.st_size, stat.st_mtime_ns, tools.ffprobe_version))
        ctx.report_progress(10000)
        return {
            "asset_id": stored.asset_id,
            "duration_us": stored.duration_us,
            "duration_source": stored.duration_source,
            "width": stored.width,
            "height": stored.height,
            "fps_num": stored.fps_num,
            "fps_den": stored.fps_den,
            "container_start_us": stored.container_start_us,
            "probe_config": stored.probe_config,
        }


class GenerateProxyJob:
    kind = GENERATE_PROXY

    def run(self, ctx: JobContext) -> dict:
        profile = _profile(ctx.spec)
        asset_id = _asset_id(ctx)
        source = ctx.store.get_media(asset_id)
        if source.role != "master":
            raise JobFailed("invalid_proxy_source", "A proxy can be generated for source media.")
        path = _existing(ctx.store, asset_id)
        tools = _tools()
        ctx.report_progress(0)
        if source.width is None or source.height is None or source.probed_at is None:
            stat = path.stat()
            try:
                probed = execute_probe(tools.ffprobe, path, ctx.cancellation)
            except ProcessCancelled as exc:
                raise JobCancelled() from exc
            except ProbeFailed as exc:
                raise JobFailed("media_probe_failed", "The media file could not be analyzed.") from exc
            source = ctx.store.apply_probe(
                asset_id, _record(probed, stat.st_size, stat.st_mtime_ns, tools.ffprobe_version),
            )
        if not source.video_codec and source.width is None:
            raise JobFailed("proxy_requires_video", "This media has no video to proxy.")
        if source.width is None or source.height is None:
            raise JobFailed("proxy_requires_video", "This media has no video to proxy.")
        metadata = _metadata_from_asset(source)
        if not metadata.has_video:
            raise JobFailed("proxy_requires_video", "This media has no video to proxy.")
        stamp = path.stat()
        ctx.store.clean_proxy_tmp(keep_name=f"{ctx.job_id}.mp4")
        temporary = ctx.store.private / "proxy" / ".tmp" / f"{ctx.job_id}.mp4"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        final = ctx.store.private / "proxy" / f"{asset_id}.mp4"
        progress = {"bp": 0}

        def on_line(line: str) -> None:
            observed = progress_time_us(line)
            if observed is None:
                return
            progress["bp"] = progress_basis_points(observed, source.duration_us, progress["bp"])
            ctx.report_progress(progress["bp"])

        try:
            result = run_process(
                proxy_command(tools.ffmpeg, path, temporary, metadata),
                ctx.cancellation,
                on_line=on_line,
            )
        except (ProcessCancelled, JobCancelled) as exc:
            _discard(temporary)
            raise JobCancelled() from exc
        except OSError as exc:
            _discard(temporary)
            log.info("proxy process failed")
            raise JobFailed("media_proxy_failed", "The proxy could not be generated.") from exc
        if ctx.cancellation.is_cancelled():
            _discard(temporary)
            raise JobCancelled()
        if result.code != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            _discard(temporary)
            log.info("proxy encode failed code=%s", result.code)
            raise JobFailed("media_proxy_failed", "The proxy could not be generated.")
        ctx.cancellation.raise_if_cancelled()
        try:
            proxy_probe = execute_probe(tools.ffprobe, temporary, ctx.cancellation)
        except ProcessCancelled as exc:
            _discard(temporary)
            raise JobCancelled() from exc
        except ProbeFailed as exc:
            _discard(temporary)
            raise JobFailed("media_probe_failed", "The proxy file could not be analyzed.") from exc
        ctx.cancellation.raise_if_cancelled()
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, final)
        proxy_stat = final.stat()
        published = ctx.store.publish_proxy(
            asset_id,
            _record(proxy_probe, proxy_stat.st_size, proxy_stat.st_mtime_ns, tools.ffprobe_version),
            relative_path=f"proxy/{asset_id}.mp4",
            display_name=f"{asset_id}.mp4",
            profile=profile,
            proxy_tool=tools.ffmpeg_version,
            job_id=ctx.job_id,
            source_size=stamp.st_size,
            source_mtime_ns=stamp.st_mtime_ns,
            timestamp_policy=TIMESTAMP_POLICY,
        )
        ctx.report_progress(10000)
        from amix.amix_engine.jobs.poster import write_project_poster
        write_project_poster(final, ctx.store.private)
        return {
            "asset_id": published.asset_id,
            "source_media_asset_id": asset_id,
            "profile": published.proxy_profile,
            "timestamp_policy": published.timestamp_policy,
            "relative_path": published.relative_path,
            "width": published.width,
            "height": published.height,
        }


def prepare_state(
    source: StoredMedia,
    proxy: StoredMedia | None,
    jobs: list[StoredJob],
    *,
    source_present: bool,
    source_size: int | None,
    source_mtime_ns: int | None,
    proxy_file_present: bool,
) -> str:
    """User-facing media state. A playable master does not wait on its proxy."""
    if not source_present:
        return "missing"
    related = [
        job for job in jobs
        if job.media_asset_id == source.asset_id and job.kind == MEDIA_PROBE
    ]
    observed = proxy_state(
        source,
        proxy,
        jobs,
        source_size=source_size,
        source_mtime_ns=source_mtime_ns,
        proxy_file_present=proxy_file_present,
    )
    probed = source.probed_at is not None
    video = source.width is not None and source.height is not None
    if source_directly_playable(source):
        return "ready"
    if observed == "ready" and probed:
        return "ready"
    if any(job.status in _ACTIVE for job in related) and not probed:
        return "preparing"
    if video:
        if observed in {"queued", "generating"}:
            return "preparing"
        if probed:
            return "preview_required"
        if any(job.status == FAILED for job in related):
            return "failed"
        return "preparing"
    if probed:
        return "ready"
    if any(job.status == FAILED for job in related):
        return "failed"
    return "preparing"


def proxy_state(
    source: StoredMedia,
    proxy: StoredMedia | None,
    jobs: list[StoredJob],
    *,
    source_size: int | None,
    source_mtime_ns: int | None,
    proxy_file_present: bool,
) -> str | None:
    """Compact derivative state for a source asset. Proxy rows themselves have none."""
    if source.role == "proxy":
        return None
    related = [
        job for job in jobs
        if job.kind == GENERATE_PROXY and job.media_asset_id == source.asset_id
    ]
    if any(job.status in {RUNNING, CANCEL_REQUESTED} for job in related):
        return "generating"
    if any(job.status == QUEUED for job in related):
        return "queued"
    if proxy is None:
        if any(job.status == FAILED for job in related):
            return "failed"
        return "not_generated"
    if not proxy_file_present:
        return "missing"
    if source_size is not None and source_size != proxy.proxy_source_size:
        return "stale"
    if (
        source_mtime_ns is not None
        and proxy.proxy_source_mtime_ns is not None
        and source_mtime_ns != proxy.proxy_source_mtime_ns
    ):
        return "stale"
    return "ready"


def _asset_id(ctx: JobContext) -> str:
    if not ctx.media_asset_id:
        raise JobFailed("unknown_media_asset", "That media file is no longer in this project.")
    return ctx.media_asset_id


def _existing(store: ProjectStore, asset_id: str):
    try:
        return store.require_media(asset_id)
    except MediaMissing as exc:
        raise JobFailed("media_missing", "The media file is missing.") from exc


def _tools():
    try:
        return discover_tools()
    except MediaToolMissing as exc:
        raise JobFailed("media_tool_missing", "FFmpeg tools are not available.") from exc


def _profile(spec: dict) -> str:
    if not isinstance(spec, dict) or set(spec) - {"profile"}:
        raise JobFailed("invalid_proxy_profile", "That proxy profile is not available.")
    chosen = spec.get("profile", PROXY_PROFILE)
    if chosen != PROXY_PROFILE:
        raise JobFailed("invalid_proxy_profile", "That proxy profile is not available.")
    return PROXY_PROFILE


def _record(metadata: ProbeMetadata, size: int, mtime_ns: int, tool: str) -> MediaProbeRecord:
    return MediaProbeRecord(
        container=metadata.container,
        duration_us=metadata.duration_us,
        duration_source=metadata.duration_source,
        container_start_us=metadata.container_start_us,
        bit_rate=metadata.bit_rate,
        video_codec=metadata.video_codec,
        width=metadata.width,
        height=metadata.height,
        pixel_format=metadata.pixel_format,
        fps_num=metadata.fps_num,
        fps_den=metadata.fps_den,
        r_fps_num=metadata.r_fps_num,
        r_fps_den=metadata.r_fps_den,
        time_base_num=metadata.time_base_num,
        time_base_den=metadata.time_base_den,
        video_start_us=metadata.video_start_us,
        video_duration_us=metadata.video_duration_us,
        rotation_degrees=metadata.rotation_degrees,
        audio_codec=metadata.audio_codec,
        sample_rate=metadata.sample_rate,
        audio_channels=metadata.audio_channels,
        channel_layout=metadata.channel_layout,
        audio_start_us=metadata.audio_start_us,
        audio_duration_us=metadata.audio_duration_us,
        byte_size=size,
        file_mtime_ns=mtime_ns,
        probe_tool=tool[:200],
        probe_config=PROBE_CONFIG,
    )


def _metadata_from_asset(asset: StoredMedia) -> ProbeMetadata:
    has_video = asset.width is not None and asset.height is not None
    return ProbeMetadata(
        container=asset.container,
        duration_us=asset.duration_us,
        duration_source=asset.duration_source,
        container_start_us=asset.container_start_us,
        bit_rate=asset.bit_rate,
        video_codec=asset.video_codec,
        width=asset.width,
        height=asset.height,
        pixel_format=asset.pixel_format,
        fps_num=asset.fps_num,
        fps_den=asset.fps_den,
        r_fps_num=asset.r_fps_num,
        r_fps_den=asset.r_fps_den,
        time_base_num=asset.time_base_num,
        time_base_den=asset.time_base_den,
        video_start_us=asset.video_start_us,
        video_duration_us=asset.video_duration_us,
        rotation_degrees=asset.rotation_degrees,
        audio_codec=asset.audio_codec,
        sample_rate=asset.sample_rate,
        audio_channels=asset.audio_channels,
        channel_layout=asset.channel_layout,
        audio_start_us=asset.audio_start_us,
        audio_duration_us=asset.audio_duration_us,
        has_video=has_video,
        has_audio=asset.audio_codec is not None or asset.audio_channels is not None,
    )


def _discard(path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        log.info("temporary proxy file remained")
