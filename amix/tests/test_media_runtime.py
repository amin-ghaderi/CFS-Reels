"""Media probe and proxy behavior. Core cases do not require FFmpeg."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from amix.amix_engine.adapters.media.discovery import MediaTools, discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing, ProbeFailed
from amix.amix_engine.adapters.media.process import ProcessResult, run_process
from amix.amix_engine.adapters.media.publish import read_pid
from amix.amix_engine.adapters.media.probe import parse_probe_document, parse_probe_json
from amix.amix_engine.adapters.media.proxy import preview_size, progress_basis_points, proxy_command
from amix.amix_engine.adapters.media.timeparse import seconds_text_to_us
from amix.amix_engine.jobs.media import GENERATE_PROXY, GenerateProxyJob, proxy_state
from amix.amix_engine.jobs.runner import CancellationToken, JobContext, JobFailed
from amix.amix_engine.playback import resolve_playback
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.migrate import upgrade_database
from amix.amix_engine.storage.project import (
    DATABASE_NAME,
    MediaProbeRecord,
    create_project,
    open_project,
    private_directory,
)
from amix.amix_engine.storage.jobs import CANCELLED

_PID_SCRIPT = (
    "import os, sys, time; from pathlib import Path; "
    "from amix.amix_engine.adapters.media.publish import publish_pid; "
    "publish_pid(Path(sys.argv[1]), os.getpid()); time.sleep(60)"
)


def _wait_complete_pid(path: Path, timeout: float = 5) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            pid = read_pid(path)
            if pid is None:
                raise AssertionError(f"incomplete pid marker: {path.read_text(encoding='utf-8')!r}")
            return pid
        time.sleep(0.02)
    raise AssertionError(f"pid marker did not appear: {path}")


def _probe(**overrides) -> dict:
    video = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "pix_fmt": "yuv420p",
        "avg_frame_rate": "30000/1001",
        "r_frame_rate": "30000/1001",
        "time_base": "1/90000",
        "start_time": "0.000000",
        "duration": "10.000000",
    }
    audio = {
        "codec_type": "audio",
        "codec_name": "aac",
        "sample_rate": "48000",
        "channels": 2,
        "channel_layout": "stereo",
        "start_time": "0.000000",
        "duration": "10.000000",
    }
    document = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "10.000000",
            "start_time": "0.000000",
            "bit_rate": "800000",
        },
        "streams": [video, audio],
    }
    document.update(overrides)
    return document


def _record(**overrides) -> MediaProbeRecord:
    values = dict(
        container="mp4",
        duration_us=1_000_000,
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
        video_duration_us=1_000_000,
        rotation_degrees=0,
        audio_codec="aac",
        sample_rate=48000,
        audio_channels=2,
        channel_layout="stereo",
        audio_start_us=0,
        audio_duration_us=1_000_000,
        byte_size=4,
        file_mtime_ns=1,
        probe_tool="ffprobe version test",
        probe_config="amix.probe.v1",
    )
    values.update(overrides)
    return MediaProbeRecord(**values)


def _alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    return str(pid) in completed.stdout


class TimeAndProbeTests(unittest.TestCase):
    def test_decimal_seconds_become_exact_microseconds(self) -> None:
        self.assertEqual(seconds_text_to_us("1.5"), 1_500_000)
        self.assertEqual(seconds_text_to_us("2960.123"), 2_960_123_000)
        self.assertEqual(seconds_text_to_us("1.0000005"), 1_000_001)
        self.assertIsInstance(seconds_text_to_us("1.5"), int)

    def test_video_and_audio_keep_rational_rate_and_do_not_rebase_start(self) -> None:
        parsed = parse_probe_document(_probe())
        self.assertEqual(parsed.fps_num, 30000)
        self.assertEqual(parsed.fps_den, 1001)
        self.assertIsInstance(parsed.fps_num, int)
        self.assertNotIsInstance(parsed.fps_num, float)
        self.assertEqual(parsed.duration_us, 10_000_000)
        self.assertEqual(parsed.container_start_us, 0)
        self.assertEqual(parsed.audio_codec, "aac")
        self.assertEqual(parsed.sample_rate, 48000)
        self.assertEqual(parsed.width, 1920)
        self.assertEqual(parsed.height, 1080)

    def test_video_only_audio_only_and_disagreeing_duration(self) -> None:
        video_only = parse_probe_document(_probe(streams=[_probe()["streams"][0]]))
        self.assertTrue(video_only.has_video)
        self.assertFalse(video_only.has_audio)
        self.assertIsNone(video_only.audio_codec)
        audio_only = parse_probe_document(_probe(streams=[_probe()["streams"][1]]))
        self.assertFalse(audio_only.has_video)
        self.assertEqual(audio_only.duration_source, "format")
        audio_document = _probe(streams=[_probe()["streams"][1]])
        audio_document["format"].pop("duration")
        audio_stream = parse_probe_document(audio_document)
        self.assertEqual(audio_stream.duration_source, "audio")
        document = _probe()
        document["streams"][0]["duration"] = "1.000000"
        document["format"]["duration"] = "9.000000"
        chosen = parse_probe_document(document)
        self.assertEqual(chosen.duration_us, 1_000_000)
        self.assertEqual(chosen.duration_source, "video")
        self.assertEqual(chosen.video_duration_us, 1_000_000)
        self.assertNotEqual(chosen.duration_us, 5_000_000)

    def test_non_zero_start_is_stored_and_missing_duration_stays_unknown(self) -> None:
        document = _probe()
        document["format"]["start_time"] = "1.500000"
        document["streams"][0]["start_time"] = "1.500000"
        parsed = parse_probe_document(document)
        self.assertEqual(parsed.container_start_us, 1_500_000)
        self.assertEqual(parsed.video_start_us, 1_500_000)
        self.assertEqual(parsed.duration_us, 10_000_000)
        document["streams"][0].pop("duration")
        document["streams"][1].pop("duration")
        document["format"].pop("duration")
        missing = parse_probe_document(document)
        self.assertIsNone(missing.duration_us)
        self.assertIsNone(missing.duration_source)

    def test_rotation_swaps_display_size(self) -> None:
        document = _probe()
        document["streams"][0]["side_data_list"] = [{"rotation": -90}]
        parsed = parse_probe_document(document)
        self.assertEqual(parsed.rotation_degrees, -90)
        self.assertEqual((parsed.width, parsed.height), (1080, 1920))

    def test_malformed_and_failed_probe(self) -> None:
        with self.assertRaises(ProbeFailed):
            parse_probe_json("{")
        with patch(
            "amix.amix_engine.adapters.media.probe.run_process",
            return_value=ProcessResult(1, "", "raw ffmpeg boom"),
        ):
            from amix.amix_engine.adapters.media.probe import execute_probe
            with self.assertRaises(ProbeFailed) as caught:
                execute_probe(Path("ffprobe"), Path("clip.mp4"))
        self.assertNotIn("boom", str(caught.exception))


class ProxyCommandTests(unittest.TestCase):
    def test_scale_preserves_aspect_and_does_not_upscale(self) -> None:
        self.assertIsNone(preview_size(320, 240))
        self.assertEqual(preview_size(1920, 1080), (1280, 720))
        self.assertEqual(preview_size(1080, 1920), (404, 720))
        fitted = preview_size(161, 121)
        self.assertIsNotNone(fitted)
        assert fitted is not None
        self.assertLessEqual(fitted[0], 161)
        self.assertLessEqual(fitted[1], 121)

    def test_commands_keep_paths_as_arguments(self) -> None:
        from amix.amix_engine.adapters.media.probe import parse_probe_document
        landscape = parse_probe_document(_probe())
        landscape = _with_size(landscape, 320, 240, audio=True)
        portrait = _with_size(parse_probe_document(_probe()), 1080, 1920, audio=False)
        spaced = Path("C:/media/my clip.mp4")
        persian = Path("C:/رسانه/کلیپ نهایی.mp4")
        dest = Path("C:/project/proxy/out.mp4")
        ffmpeg = Path("C:/tools/ffmpeg")
        landscape_args = proxy_command(ffmpeg, spaced, dest, landscape)
        portrait_args = proxy_command(ffmpeg, persian, dest, portrait)
        self.assertIn(str(spaced), landscape_args)
        self.assertIn(str(persian), portrait_args)
        self.assertNotIn("-vf", landscape_args)
        self.assertIn("scale=404:720", portrait_args)
        self.assertNotIn("aac", portrait_args)
        self.assertNotIn("-an", portrait_args)
        self.assertIn("aac", landscape_args)
        self.assertIn("libx264", landscape_args)
        self.assertIn("yuv420p", landscape_args)
        self.assertEqual(progress_basis_points(500_000, 1_000_000, 0), 5000)
        self.assertEqual(progress_basis_points(100, 1_000_000, 5000), 5000)
        self.assertEqual(progress_basis_points(1, None, 0), 0)

    def test_unicode_argument_is_not_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "argv.txt"
            media = "پوشه کلیپ.mp4"
            run_process(
                [
                    sys.executable,
                    "-c",
                    "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')",
                    str(marker),
                    media,
                ],
                None,
            )
            self.assertEqual(marker.read_text(encoding="utf-8"), media)


def _with_size(parsed, width: int, height: int, *, audio: bool):
    from dataclasses import replace
    return replace(
        parsed,
        width=width,
        height=height,
        has_audio=audio,
        audio_codec="aac" if audio else None,
    )


class DiscoveryTests(unittest.TestCase):
    def test_explicit_missing_tool_does_not_fall_through(self) -> None:
        with patch("amix.amix_engine.adapters.media.discovery.shutil.which", side_effect=AssertionError("path")):
            with self.assertRaises(MediaToolMissing):
                discover_tools({"AMIX_FFMPEG": str(Path("Z:/missing/ffmpeg.exe"))}, root=Path("Z:/missing"))

    def test_repository_tools_are_preferred_over_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            ffmpeg = tools / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            ffprobe = tools / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
            ffmpeg.write_bytes(b"")
            ffprobe.write_bytes(b"")
            with patch("amix.amix_engine.adapters.media.discovery._version", return_value="version test"):
                found = discover_tools({}, root=Path(tmp))
            self.assertEqual(found.ffmpeg, ffmpeg)
            self.assertEqual(found.ffprobe, ffprobe)


class StoreAndJobTests(unittest.TestCase):
    def test_probe_updates_the_same_asset_and_proxy_can_be_stale(self) -> None:
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
                store.apply_probe(asset_id, _record(byte_size=4))
                store.apply_probe(asset_id, _record(byte_size=4, duration_us=2_000_000))
                self.assertEqual(len(store.list_media_assets()), 1)
                stored = store.get_media(asset_id)
                self.assertEqual(stored.asset_id, asset_id)
                self.assertEqual(stored.duration_us, 2_000_000)
                self.assertEqual(stored.fps_num, 25)
                self.assertIsInstance(stored.fps_num, int)
                proxy_file = private_directory(root) / "proxy" / f"{asset_id}.mp4"
                proxy_file.write_bytes(b"proxy")
                published = store.publish_proxy(
                    asset_id,
                    _record(byte_size=5, width=320, height=240),
                    relative_path=f"proxy/{asset_id}.mp4",
                    display_name=f"{asset_id}.mp4",
                    profile="amix.proxy.v1",
                    proxy_tool="ffmpeg version test",
                    job_id="job-1",
                    source_size=4,
                    source_mtime_ns=source_file.stat().st_mtime_ns,
                    timestamp_policy="container_normalized_v1",
                )
                self.assertEqual(published.source_media_asset_id, asset_id)
                self.assertEqual(published.role, "proxy")
                self.assertTrue(str(published.relative_path).startswith("proxy/"))
                ready = proxy_state(
                    store.get_media(asset_id),
                    published,
                    [],
                    source_size=4,
                    source_mtime_ns=published.proxy_source_mtime_ns,
                    proxy_file_present=True,
                )
                self.assertEqual(ready, "ready")
                stale = proxy_state(
                    store.get_media(asset_id),
                    published,
                    [],
                    source_size=9,
                    source_mtime_ns=published.proxy_source_mtime_ns,
                    proxy_file_present=True,
                )
                self.assertEqual(stale, "stale")
                junk = private_directory(root) / "proxy" / ".tmp" / "old.mp4"
                junk.parent.mkdir(parents=True, exist_ok=True)
                junk.write_bytes(b"partial")
                store.clean_proxy_tmp()
                self.assertFalse(junk.exists())
                self.assertTrue(proxy_file.is_file())
            finally:
                store.close()

    def test_bad_profile_and_cancelled_proxy_are_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Edit"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase7"))
            try:
                session = runtime.create_project(root, "Edit")
                source = root / "clip.bin"
                source.write_bytes(b"clip")
                asset_id = session.store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=4,
                    file_mtime_ns=source.stat().st_mtime_ns,
                )
                session.store.apply_probe(asset_id, _record(byte_size=4))
                with self.assertRaises(JobFailed):
                    GenerateProxyJob().run(JobContext(
                        session.store,
                        "job",
                        {"profile": "amix.proxy.v1", "command": "ffmpeg"},
                        CancellationToken(),
                        asset_id,
                    ))
                self.assertIsNone(session.store.find_proxy(asset_id))
                pid_path = root / "pid.txt"
                tools = MediaTools(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
                with patch("amix.amix_engine.jobs.media.discover_tools", return_value=tools), patch(
                    "amix.amix_engine.jobs.media.proxy_command",
                    return_value=[sys.executable, "-c", _PID_SCRIPT, str(pid_path)],
                ):
                    job = runtime.jobs.submit(
                        session.store,
                        GENERATE_PROXY,
                        {"profile": "amix.proxy.v1"},
                        asset_id,
                    )
                    pid = _wait_complete_pid(pid_path)
                    self.assertTrue(_alive(pid))
                    runtime.jobs.cancel(session.store, job.job_id)
                    self.assertTrue(runtime.jobs.wait_until_idle(session.store, 5))
                finished = next(item for item in session.store.list_processing_jobs() if item.job_id == job.job_id)
                self.assertEqual(finished.status, CANCELLED)
                self.assertIsNone(session.store.find_proxy(asset_id))
                self.assertFalse(_alive(pid))
                self.assertFalse((private_directory(root) / "proxy" / f"{asset_id}.mp4").exists())
            finally:
                runtime.shutdown()

    def test_engine_shutdown_stops_the_proxy_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Stop"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase7"))
            session = runtime.create_project(root, "Stop")
            source = root / "clip.bin"
            source.write_bytes(b"clip")
            asset_id = session.store.add_media_asset(
                display_name="clip.bin",
                location_kind="external",
                external_path=str(source),
                byte_size=4,
            )
            session.store.apply_probe(asset_id, _record(byte_size=4))
            pid_path = root / "pid.txt"
            tools = MediaTools(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
            try:
                with patch("amix.amix_engine.jobs.media.discover_tools", return_value=tools), patch(
                    "amix.amix_engine.jobs.media.proxy_command",
                    return_value=[sys.executable, "-c", _PID_SCRIPT, str(pid_path)],
                ):
                    runtime.jobs.submit(session.store, GENERATE_PROXY, {"profile": "amix.proxy.v1"}, asset_id)
                    pid = _wait_complete_pid(pid_path)
                    runtime.shutdown()
                    self.assertFalse(_alive(pid))
            finally:
                if runtime is not None:
                    try:
                        runtime.shutdown()
                    except Exception:
                        pass


class MigrationTests(unittest.TestCase):
    def test_revision_0002_upgrades_and_a_fresh_project_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "step.sqlite"
            upgrade_database(database, "0002_processing_job")
            connection = sqlite3.connect(database)
            try:
                revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                columns = {row[1] for row in connection.execute("PRAGMA table_info(media_asset)")}
            finally:
                connection.close()
            self.assertEqual(revision, "0002_processing_job")
            self.assertNotIn("source_media_asset_id", columns)
            upgrade_database(database)
            connection = sqlite3.connect(database)
            try:
                revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                columns = {row[1] for row in connection.execute("PRAGMA table_info(media_asset)")}
                types = {row[1]: row[2] for row in connection.execute("PRAGMA table_info(media_asset)")}
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                connection.close()
            self.assertEqual(revision, "0011_reel_dismissal")
            self.assertIn("shot_override", tables)
            self.assertIn("editorial_sequence", tables)
            self.assertIn("sequence_clip", tables)
            self.assertIn("conversation_thread", tables)
            self.assertIn("reel_candidate", tables)
            self.assertIn("source_media_asset_id", columns)
            self.assertIn("fps_num", columns)
            self.assertNotIn("REAL", types["fps_num"].upper())
            self.assertNotIn("REAL", types["duration_us"].upper())
            root = Path(tmp) / "Fresh"
            store = create_project(root, "Fresh")
            try:
                self.assertEqual(store.alembic_revision(), "0011_reel_dismissal")
            finally:
                store.close()


def _ffmpeg_available() -> bool:
    try:
        discover_tools()
    except MediaToolMissing:
        return False
    return True


@unittest.skipUnless(_ffmpeg_available(), "ffmpeg/ffprobe are not installed")
class FfmpegIntegrationTests(unittest.TestCase):
    def test_probe_of_a_compatible_file_does_not_queue_a_proxy(self) -> None:
        tools = discover_tools()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Picture"
            source = Path(tmp) / "landscape.mp4"
            _synthetic(tools.ffmpeg, source, 320, 240)
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=60, session_token="direct", worker_count=1))
            try:
                session = runtime.create_project(root, "Picture")
                asset_id = _link(session.store, source)
                runtime.jobs.submit(session.store, "media_probe", {}, asset_id)
                self.assertTrue(runtime.jobs.wait_until_idle(session.store, 60))
                jobs = session.store.list_processing_jobs()
                self.assertTrue(jobs)
                self.assertTrue(all(job.kind != GENERATE_PROXY for job in jobs))
                self.assertTrue(all(job.status == "SUCCEEDED" for job in jobs))
                described = resolve_playback(session.store, asset_id)
                self.assertEqual(described.playback_kind, "source")
                self.assertEqual(Path(described.resolved_path or ""), source.resolve())
                self.assertEqual(described.playback_duration_us, session.store.get_media(asset_id).duration_us)
                listed = session.store.get_media(asset_id)
                from amix.amix_engine.jobs.media import prepare_state
                self.assertEqual(prepare_state(
                    listed, None, jobs,
                    source_present=True,
                    source_size=source.stat().st_size,
                    source_mtime_ns=source.stat().st_mtime_ns,
                    proxy_file_present=False,
                ), "ready")
                proxy_dir = private_directory(root) / "proxy"
                published = [] if not proxy_dir.exists() else [path for path in proxy_dir.rglob("*") if path.is_file()]
                self.assertEqual(published, [])
            finally:
                runtime.shutdown()

    def test_probe_and_proxy_round_trip(self) -> None:
        tools = discover_tools()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Picture"
            landscape = Path(tmp) / "landscape.mp4"
            portrait = Path(tmp) / "portrait.mp4"
            _synthetic(tools.ffmpeg, landscape, 320, 240)
            _synthetic(tools.ffmpeg, portrait, 1080, 1920)
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=60, session_token="phase7", worker_count=1))
            try:
                session = runtime.create_project(root, "Picture")
                landscape_id = _link(session.store, landscape)
                portrait_id = _link(session.store, portrait)
                for asset_id in (landscape_id, portrait_id):
                    probe = runtime.jobs.submit(session.store, "media_probe", {}, asset_id)
                    proxy = runtime.jobs.submit(
                        session.store, GENERATE_PROXY, {"profile": "amix.proxy.v1"}, asset_id,
                    )
                    self.assertNotEqual(probe.job_id, proxy.job_id)
                self.assertTrue(runtime.jobs.wait_until_idle(session.store, 60))
                for job in session.store.list_processing_jobs():
                    self.assertEqual(job.status, "SUCCEEDED", job.error_message)
                wide = session.store.get_media(landscape_id)
                tall = session.store.get_media(portrait_id)
                self.assertEqual(wide.asset_id, landscape_id)
                self.assertEqual(wide.width, 320)
                self.assertEqual(wide.height, 240)
                self.assertIsInstance(wide.duration_us, int)
                self.assertGreater(wide.container_start_us or 0, -1)
                wide_proxy = session.store.find_proxy(landscape_id)
                tall_proxy = session.store.find_proxy(portrait_id)
                assert wide_proxy is not None and tall_proxy is not None
                self.assertEqual(wide_proxy.source_media_asset_id, landscape_id)
                self.assertEqual((wide_proxy.width, wide_proxy.height), (320, 240))
                self.assertLessEqual(tall_proxy.width or 0, 1280)
                self.assertLessEqual(tall_proxy.height or 0, 720)
                self.assertGreater(tall_proxy.height or 0, tall_proxy.width or 0)
                self.assertNotEqual((tall_proxy.width, tall_proxy.height), (1280, 720))
                self.assertTrue((private_directory(root) / "proxy" / f"{landscape_id}.mp4").is_file())
                self.assertFalse((landscape.parent / "proxy").exists())
                described = resolve_playback(session.store, landscape_id)
                self.assertTrue(described.playable)
                self.assertEqual(described.playback_kind, "source")
                self.assertEqual(Path(described.resolved_path or ""), landscape.resolve())
                chosen = resolve_playback(session.store, landscape_id, prefer="proxy")
                self.assertEqual(chosen.playback_kind, "proxy")
                self.assertEqual(chosen.playback_media_asset_id, wide_proxy.asset_id)
                self.assertEqual(chosen.profile, "amix.proxy.v1")
                self.assertIsInstance(chosen.canonical_origin_us, int)
                self.assertTrue((chosen.resolved_path or "").endswith(f"{landscape_id}.mp4"))
                project_id = session.store.project_id
            finally:
                runtime.shutdown()
            reopened = open_project(root)
            try:
                self.assertEqual(reopened.project_id, project_id)
                again = reopened.find_proxy(landscape_id)
                assert again is not None
                self.assertEqual(again.source_media_asset_id, landscape_id)
                self.assertEqual(again.proxy_profile, "amix.proxy.v1")
            finally:
                reopened.close()


def _link(store, path: Path) -> str:
    stat = path.stat()
    return store.add_media_asset(
        display_name=path.name,
        location_kind="external",
        external_path=str(path),
        byte_size=stat.st_size,
        file_mtime_ns=stat.st_mtime_ns,
    )


def _synthetic(ffmpeg: Path, dest: Path, width: int, height: int) -> None:
    completed = subprocess.run(
        [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:d=0.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(dest),
        ],
        check=False,
        shell=False,
    )
    if completed.returncode != 0 or not dest.is_file():
        raise AssertionError("synthetic media was not created")
