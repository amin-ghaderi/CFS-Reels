"""Playback descriptor and word-at-time. No FFmpeg and no media fixtures."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amix.amix_engine.domain.types import Word
from amix.amix_engine.playback import SOURCE_MISSING_WARNING, canonical_origin_us, resolve_playback
from amix.amix_engine.storage.project import MediaProbeRecord, create_project
from amix.amix_engine.time.clock import TimeRange
from amix.tests.test_service import _client, _create, _headers


def _record(**overrides) -> MediaProbeRecord:
    values = dict(
        container="mp4",
        duration_us=2_000_000,
        duration_source="video",
        container_start_us=0,
        bit_rate=800000,
        video_codec="h264",
        width=320,
        height=240,
        pixel_format="yuv420p",
        fps_num=25,
        fps_den=1,
        r_fps_num=25,
        r_fps_den=1,
        time_base_num=1,
        time_base_den=12800,
        video_start_us=0,
        video_duration_us=2_000_000,
        rotation_degrees=0,
        audio_codec="aac",
        sample_rate=48000,
        audio_channels=2,
        channel_layout="stereo",
        audio_start_us=0,
        audio_duration_us=2_000_000,
        byte_size=4,
        file_mtime_ns=1,
        probe_tool="ffprobe version test",
        probe_config="amix.probe.v1",
    )
    values.update(overrides)
    return MediaProbeRecord(**values)


class OriginTests(unittest.TestCase):
    def test_origin_is_the_integer_source_time_at_playback_zero(self) -> None:
        self.assertEqual(canonical_origin_us(0, 0), 0)
        self.assertEqual(canonical_origin_us(None, None), 0)
        self.assertEqual(canonical_origin_us(1_500_000, 0), 1_500_000)
        self.assertEqual(canonical_origin_us(1_500_000, 250_000), 1_250_000)
        self.assertIsInstance(canonical_origin_us(1_500_000, 250_000), int)


class DescriptorTests(unittest.TestCase):
    def test_ready_proxy_uses_the_relation_not_a_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Show"
            store = create_project(root, "Show")
            try:
                source_file = root / "clip.bin"
                source_file.write_bytes(b"clip")
                asset_id = store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source_file),
                    byte_size=4,
                    file_mtime_ns=source_file.stat().st_mtime_ns,
                )
                store.apply_probe(asset_id, _record(byte_size=4, file_mtime_ns=source_file.stat().st_mtime_ns, container_start_us=1_500_000))
                decoy = root / "proxy" / f"{asset_id}.mp4"
                decoy.parent.mkdir(parents=True, exist_ok=True)
                decoy.write_bytes(b"not-the-relation")
                real = root / "proxy" / "chosen.mp4"
                real.write_bytes(b"proxy-bytes")
                published = store.publish_proxy(
                    asset_id,
                    _record(byte_size=real.stat().st_size, file_mtime_ns=real.stat().st_mtime_ns, container_start_us=0, duration_us=2_000_000),
                    relative_path="proxy/chosen.mp4",
                    display_name="chosen.mp4",
                    profile="amix.proxy.v1",
                    proxy_tool="ffmpeg version test",
                    job_id="job-1",
                    source_size=4,
                    source_mtime_ns=source_file.stat().st_mtime_ns,
                    timestamp_policy="container_normalized_v1",
                )
                described = resolve_playback(store, asset_id)
                self.assertTrue(described.playable)
                self.assertEqual(described.status, "ready")
                self.assertEqual(described.playback_media_asset_id, published.asset_id)
                self.assertEqual(described.profile, "amix.proxy.v1")
                self.assertEqual(described.timestamp_policy, "container_normalized_v1")
                self.assertEqual(Path(described.resolved_path or ""), real.resolve())
                self.assertNotEqual(Path(described.resolved_path or ""), decoy.resolve())
                self.assertEqual(described.canonical_origin_us, 1_500_000)
                self.assertIsInstance(described.canonical_origin_us, int)
                self.assertEqual(described.playback_duration_us, 2_000_000)
                self.assertIsNone(described.warning)
                self.assertTrue(described.source_present)
                self.assertEqual(described.mime, "video/mp4")
            finally:
                store.close()

    def test_missing_source_with_a_valid_proxy_stays_playable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Show"
            store = create_project(root, "Show")
            try:
                source_file = root / "clip.bin"
                source_file.write_bytes(b"clip")
                mtime = source_file.stat().st_mtime_ns
                asset_id = store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source_file),
                    byte_size=4,
                    file_mtime_ns=mtime,
                )
                store.apply_probe(asset_id, _record(byte_size=4, file_mtime_ns=mtime))
                proxy = root / "proxy" / "chosen.mp4"
                proxy.parent.mkdir(parents=True, exist_ok=True)
                proxy.write_bytes(b"proxy")
                store.publish_proxy(
                    asset_id,
                    _record(byte_size=5, file_mtime_ns=proxy.stat().st_mtime_ns),
                    relative_path="proxy/chosen.mp4",
                    display_name="chosen.mp4",
                    profile="amix.proxy.v1",
                    proxy_tool="ffmpeg version test",
                    job_id="job-1",
                    source_size=4,
                    source_mtime_ns=mtime,
                    timestamp_policy="container_normalized_v1",
                )
                source_file.unlink()
                described = resolve_playback(store, asset_id)
                self.assertTrue(described.playable)
                self.assertFalse(described.source_present)
                self.assertEqual(described.warning, SOURCE_MISSING_WARNING)
                self.assertTrue(described.resolved_path)
            finally:
                store.close()

    def test_known_stale_proxy_is_not_playable_after_the_source_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Show"
            store = create_project(root, "Show")
            try:
                source_file = root / "clip.bin"
                source_file.write_bytes(b"clip-changed")
                asset_id = store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source_file),
                    byte_size=12,
                    file_mtime_ns=source_file.stat().st_mtime_ns,
                )
                store.apply_probe(asset_id, _record(byte_size=12, file_mtime_ns=source_file.stat().st_mtime_ns))
                proxy = root / "proxy" / "chosen.mp4"
                proxy.parent.mkdir(parents=True, exist_ok=True)
                proxy.write_bytes(b"proxy")
                store.publish_proxy(
                    asset_id,
                    _record(byte_size=5, file_mtime_ns=proxy.stat().st_mtime_ns),
                    relative_path="proxy/chosen.mp4",
                    display_name="chosen.mp4",
                    profile="amix.proxy.v1",
                    proxy_tool="ffmpeg version test",
                    job_id="job-1",
                    source_size=4,
                    source_mtime_ns=1,
                    timestamp_policy="container_normalized_v1",
                )
                source_file.unlink()
                described = resolve_playback(store, asset_id)
                self.assertFalse(described.playable)
                self.assertEqual(described.status, "stale")
                self.assertIsNone(described.resolved_path)
                self.assertIsNone(described.warning)
            finally:
                store.close()

    def test_stale_present_source_and_wrong_profile_are_not_playable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Show"
            store = create_project(root, "Show")
            try:
                source_file = root / "clip.bin"
                source_file.write_bytes(b"clip")
                asset_id = store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source_file),
                    byte_size=4,
                    file_mtime_ns=source_file.stat().st_mtime_ns,
                )
                store.apply_probe(asset_id, _record(byte_size=4, file_mtime_ns=source_file.stat().st_mtime_ns))
                proxy = root / "proxy" / "chosen.mp4"
                proxy.parent.mkdir(parents=True, exist_ok=True)
                proxy.write_bytes(b"proxy")
                store.publish_proxy(
                    asset_id,
                    _record(byte_size=5, file_mtime_ns=proxy.stat().st_mtime_ns),
                    relative_path="proxy/chosen.mp4",
                    display_name="chosen.mp4",
                    profile="amix.proxy.v1",
                    proxy_tool="ffmpeg version test",
                    job_id="job-1",
                    source_size=4,
                    source_mtime_ns=source_file.stat().st_mtime_ns,
                    timestamp_policy="container_normalized_v1",
                )
                source_file.write_bytes(b"clip-edited")
                stale = resolve_playback(store, asset_id)
                self.assertFalse(stale.playable)
                self.assertEqual(stale.status, "stale")
                self.assertIsNone(stale.resolved_path)

                fresh = root / "clip-fresh.bin"
                fresh.write_bytes(b"clip")
                other = store.add_media_asset(
                    display_name="clip-fresh.bin",
                    location_kind="external",
                    external_path=str(fresh),
                    byte_size=4,
                    file_mtime_ns=fresh.stat().st_mtime_ns,
                )
                store.apply_probe(other, _record(byte_size=4, file_mtime_ns=fresh.stat().st_mtime_ns))
                other_proxy = root / "proxy" / "other.mp4"
                other_proxy.write_bytes(b"proxy")
                store.publish_proxy(
                    other,
                    _record(byte_size=5, file_mtime_ns=other_proxy.stat().st_mtime_ns),
                    relative_path="proxy/other.mp4",
                    display_name="other.mp4",
                    profile="other.profile",
                    proxy_tool="ffmpeg version test",
                    job_id="job-2",
                    source_size=4,
                    source_mtime_ns=fresh.stat().st_mtime_ns,
                    timestamp_policy="container_normalized_v1",
                )
                unsupported = resolve_playback(store, other)
                self.assertFalse(unsupported.playable)
                self.assertEqual(unsupported.status, "unsupported")
                self.assertIsNone(unsupported.resolved_path)
            finally:
                store.close()

    def test_no_proxy_has_no_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Show"
            store = create_project(root, "Show")
            try:
                source_file = root / "clip.bin"
                source_file.write_bytes(b"clip")
                asset_id = store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source_file),
                    byte_size=4,
                )
                described = resolve_playback(store, asset_id)
                self.assertFalse(described.playable)
                self.assertEqual(described.status, "not_generated")
                self.assertIsNone(described.resolved_path)
                self.assertIsNone(described.canonical_origin_us)
            finally:
                store.close()


class PlaybackApiTests(unittest.TestCase):
    def test_playback_and_word_at_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, client = _client(tmp)
            try:
                project = _create(client, root / "Show", "Show")
                handle = project["handle"]
                media = root / "clip.bin"
                media.write_bytes(b"clip")
                linked = client.post(
                    f"/v1/projects/{handle}/media",
                    headers=_headers(),
                    json={"path": str(media)},
                )
                asset_id = linked.json()["asset_id"]
                store = runtime.session(handle).store
                store.apply_probe(asset_id, _record(byte_size=4, file_mtime_ns=media.stat().st_mtime_ns, container_start_us=1_500_000))
                proxy = root / "Show" / "proxy" / "chosen.mp4"
                proxy.parent.mkdir(parents=True, exist_ok=True)
                proxy.write_bytes(b"proxy")
                store.publish_proxy(
                    asset_id,
                    _record(byte_size=5, file_mtime_ns=proxy.stat().st_mtime_ns, container_start_us=0),
                    relative_path="proxy/chosen.mp4",
                    display_name="chosen.mp4",
                    profile="amix.proxy.v1",
                    proxy_tool="ffmpeg version test",
                    job_id="job-1",
                    source_size=4,
                    source_mtime_ns=media.stat().st_mtime_ns,
                    timestamp_policy="container_normalized_v1",
                )
                words = [
                    Word("w0", 0, 500_000, "one"),
                    Word("w1", 800_000, 1_200_000, "two"),
                ]
                run_id = store.save_transcript(
                    asset_id=asset_id,
                    words=words,
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="play",
                    window=TimeRange(0, 1_200_000),
                )
                store.set_active(asset_id, "transcript", run_id)
                store.correct_word_text("w0", "ONE", scope_id=run_id)

                playback = client.get(f"/v1/projects/{handle}/media/{asset_id}/playback", headers=_headers())
                self.assertEqual(playback.status_code, 200, playback.text)
                body = playback.json()
                self.assertTrue(body["playable"])
                self.assertEqual(body["canonical_origin_us"], 1_500_000)
                self.assertIsInstance(body["canonical_origin_us"], int)
                self.assertTrue(str(body["resolved_path"]).endswith("chosen.mp4"))
                self.assertNotIn(asset_id, Path(body["resolved_path"]).name)

                at_start = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/word-at/0",
                    headers=_headers(),
                )
                self.assertEqual(at_start.status_code, 200, at_start.text)
                self.assertEqual(at_start.json()["word_id"], "w0")
                self.assertEqual(at_start.json()["start_us"], 0)
                self.assertEqual(at_start.json()["end_us"], 500_000)
                self.assertNotIn("effective_text", at_start.json())

                at_end = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/word-at/500000",
                    headers=_headers(),
                )
                self.assertFalse(at_end.json()["found"])
                self.assertIsNone(at_end.json()["word_id"])

                gap = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/word-at/600000",
                    headers=_headers(),
                )
                self.assertFalse(gap.json()["found"])

                inside = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/word-at/800000",
                    headers=_headers(),
                )
                self.assertEqual(inside.json()["word_id"], "w1")
                self.assertEqual(inside.json()["sequence"], 1)

                rejected = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/word-at/-1",
                    headers=_headers(),
                )
                self.assertEqual(rejected.status_code, 400)
            finally:
                client.close()
                runtime.shutdown()


class WordAtStoreTests(unittest.TestCase):
    def test_half_open_containment_ignores_corrected_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = create_project(Path(tmp) / "Edit", "Edit")
            try:
                source = Path(tmp) / "clip.bin"
                source.write_bytes(b"clip")
                asset_id = store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=4,
                )
                run_id = store.save_transcript(
                    asset_id=asset_id,
                    words=[Word("w0", 0, 100, "one"), Word("w1", 100, 200, "two")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="edge",
                    window=TimeRange(0, 200),
                )
                store.set_active(asset_id, "transcript", run_id)
                store.correct_word_text("w0", "changed", scope_id=run_id)
                hit = store.word_at_time(asset_id, 0)
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertEqual(hit.word_id, "w0")
                still = store.word_at_time(asset_id, 99)
                self.assertIsNotNone(still)
                assert still is not None
                self.assertEqual(still.word_id, "w0")
                ended = store.word_at_time(asset_id, 100)
                self.assertIsNotNone(ended)
                assert ended is not None
                self.assertEqual(ended.word_id, "w1")
                self.assertIsNone(store.word_at_time(asset_id, 200))
            finally:
                store.close()
