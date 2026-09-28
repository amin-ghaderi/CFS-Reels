"""Playback descriptor for one editorial source.

The engine chooses the proxy and the canonical origin. React does not
reconstruct that mapping, and it does not choose a file by name.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amix.amix_engine.adapters.media.proxy import PROXY_PROFILE, TIMESTAMP_POLICY
from amix.amix_engine.jobs.media import proxy_state
from amix.amix_engine.storage.project import ProjectStore, StoredMedia

SOURCE_MISSING_WARNING = (
    "Original media is currently unavailable. Preview is using the project proxy."
)


@dataclass(frozen=True)
class PlaybackDescriptor:
    source_media_asset_id: str
    playable: bool
    status: str
    warning: str | None
    playback_media_asset_id: str | None
    profile: str | None
    resolved_path: str | None
    playback_duration_us: int | None
    source_duration_us: int | None
    source_container_start_us: int | None
    proxy_container_start_us: int | None
    canonical_origin_us: int | None
    timestamp_policy: str | None
    byte_size: int | None
    file_mtime_ns: int | None
    container: str | None
    mime: str | None
    source_present: bool


def canonical_origin_us(source_start_us: int | None, proxy_start_us: int | None) -> int:
    """Canonical source time at playback currentTime 0.

    container_normalized_v1:
    canonical_source_us = proxy_time_us - proxy_container_start_us + source_container_start_us
    At proxy time 0 that is source_container_start_us - proxy_container_start_us.
    Missing starts count as 0. The result stays an integer.
    """
    return int(source_start_us or 0) - int(proxy_start_us or 0)


def resolve_playback(store: ProjectStore, asset_id: str) -> PlaybackDescriptor:
    """Resolve preview for a source asset. The path is set only when playback is allowed."""
    source = store.get_media(asset_id)
    if source.role == "proxy":
        return _empty(source, status="unavailable", source_present=store.media_status(asset_id) == "present")
    proxy = store.find_proxy(asset_id)
    jobs = store.list_processing_jobs()
    observed_size, observed_mtime = store.observed_file(asset_id)
    source_present = observed_size is not None
    proxy_file = None if proxy is None else _confined_proxy_file(store.root, proxy)
    state = proxy_state(
        source,
        proxy,
        jobs,
        source_size=observed_size,
        source_mtime_ns=observed_mtime,
        proxy_file_present=proxy_file is not None,
    ) or "unavailable"
    if (
        state == "ready"
        and not source_present
        and proxy is not None
        and _recorded_identity_conflicts(source, proxy)
    ):
        # The source can no longer be stat'd, but the last stored identity
        # already disagreed with this proxy. That is known-stale, not a
        # usable preview.
        state = "stale"
    provenance_ok = proxy is not None and _provenance_ok(proxy) and proxy_file is not None
    if state == "ready" and not provenance_ok:
        state = "unsupported"
    playable = state == "ready" and provenance_ok and proxy is not None and proxy_file is not None
    origin = None
    if proxy is not None and _provenance_ok(proxy):
        origin = canonical_origin_us(source.container_start_us, proxy.container_start_us)
    warning = SOURCE_MISSING_WARNING if playable and not source_present else None
    identity_size = None
    identity_mtime = None
    if playable and proxy_file is not None:
        stat = proxy_file.stat()
        identity_size = stat.st_size
        identity_mtime = stat.st_mtime_ns
    return PlaybackDescriptor(
        source_media_asset_id=source.asset_id,
        playable=playable,
        status=state,
        warning=warning,
        playback_media_asset_id=None if proxy is None else proxy.asset_id,
        profile=None if proxy is None else proxy.proxy_profile,
        resolved_path=str(proxy_file) if playable and proxy_file is not None else None,
        playback_duration_us=None if proxy is None else proxy.duration_us,
        source_duration_us=source.duration_us,
        source_container_start_us=source.container_start_us,
        proxy_container_start_us=None if proxy is None else proxy.container_start_us,
        canonical_origin_us=origin if playable else None,
        timestamp_policy=None if proxy is None else proxy.timestamp_policy,
        byte_size=identity_size,
        file_mtime_ns=identity_mtime,
        container=None if proxy is None else proxy.container,
        mime="video/mp4" if playable else None,
        source_present=source_present,
    )


def _empty(source: StoredMedia, *, status: str, source_present: bool) -> PlaybackDescriptor:
    return PlaybackDescriptor(
        source_media_asset_id=source.asset_id,
        playable=False,
        status=status,
        warning=None,
        playback_media_asset_id=None,
        profile=None,
        resolved_path=None,
        playback_duration_us=None,
        source_duration_us=source.duration_us,
        source_container_start_us=source.container_start_us,
        proxy_container_start_us=None,
        canonical_origin_us=None,
        timestamp_policy=None,
        byte_size=None,
        file_mtime_ns=None,
        container=None,
        mime=None,
        source_present=source_present,
    )


def _provenance_ok(proxy: StoredMedia) -> bool:
    return (
        proxy.role == "proxy"
        and proxy.proxy_profile == PROXY_PROFILE
        and proxy.timestamp_policy == TIMESTAMP_POLICY
        and proxy.location_kind == "project"
        and bool(proxy.source_media_asset_id)
    )


def _recorded_identity_conflicts(source: StoredMedia, proxy: StoredMedia) -> bool:
    if (
        source.byte_size is not None
        and proxy.proxy_source_size is not None
        and source.byte_size != proxy.proxy_source_size
    ):
        return True
    if (
        source.file_mtime_ns is not None
        and proxy.proxy_source_mtime_ns is not None
        and source.file_mtime_ns != proxy.proxy_source_mtime_ns
    ):
        return True
    return False


def _confined_proxy_file(root: Path, proxy: StoredMedia) -> Path | None:
    """The published proxy file, only when it stays inside the project proxy directory."""
    if proxy.location_kind != "project" or not proxy.relative_path:
        return None
    project_root = root.resolve()
    proxy_root = (project_root / "proxy").resolve()
    candidate = (project_root / proxy.relative_path).resolve()
    playback_root = (proxy_root / ".playback").resolve()
    if not candidate.is_file():
        return None
    if not candidate.is_relative_to(proxy_root):
        return None
    if candidate.is_relative_to(playback_root):
        return None
    return candidate
