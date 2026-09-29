"""Generic sequence rendering. Reel is content. Canvas and picture are separate."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing
from amix.amix_engine.adapters.media.process import run_process
from amix.amix_engine.adapters.media.probe import execute_probe
from amix.amix_engine.domain.types import (
    LayoutBinding,
    OverlapRegion,
    ParticipantId,
    SpeakerAssignment,
    Turn,
    Word,
)
from amix.amix_engine.editorial.sequence import create_reel_draft, sequence_fingerprint, split_clip
from amix.amix_engine.jobs.media import _record
from amix.amix_engine.jobs.render import (
    MULTICAM,
    RENDER_MULTICAM,
    RENDER_SEQUENCE,
    SOURCE_PROGRAM,
    sequence_render_readiness,
)
from amix.amix_engine.layout import layout_fingerprint
from amix.amix_engine.multicam.apply import build_automatic_plan
from amix.amix_engine.multicam.compile import (
    compile_kept_render,
    compile_render,
    compile_source_program,
)
from amix.amix_engine.multicam.effective import EffectiveShot, set_shot_override
from amix.amix_engine.multicam.profile import PRESETS, preset_from_id
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.migrate import upgrade_database
from amix.amix_engine.storage.project import MediaProbeRecord, create_project
from amix.amix_engine.time.clock import TimeRange

A = ParticipantId("a")
B = ParticipantId("b")


def _probe(**overrides) -> MediaProbeRecord:
    values = dict(
        container="mov", duration_us=6_000_000, duration_source="container",
        container_start_us=0, bit_rate=1, video_codec="h264", width=1920, height=1080,
        pixel_format="yuv420p", fps_num=30, fps_den=1, r_fps_num=30, r_fps_den=1,
        time_base_num=1, time_base_den=30, video_start_us=0, video_duration_us=6_000_000,
        rotation_degrees=0, audio_codec="aac", sample_rate=48000, audio_channels=2,
        channel_layout="stereo", audio_start_us=0, audio_duration_us=6_000_000,
        byte_size=4, file_mtime_ns=1, probe_tool="ffprobe version test", probe_config="amix.probe.v1",
    )
    values.update(overrides)
    return MediaProbeRecord(**values)


def _shot(shot_id, start, end, presentation="untouched_wide", participant=None, locked=False):
    return EffectiveShot(
        shot_id, start, end, "floor", presentation, participant, "auto", None,
        presentation, participant, locked,
    )


def _seed_turns(store, asset: str, window: TimeRange) -> None:
    words = [
        Word("w1", window.start_us, window.start_us + 100_000, "hello"),
        Word("w2", window.start_us + 100_000, window.end_us, "there"),
    ]
    transcript = store.save_transcript(
        asset_id=asset, words=words, algorithm_id="amix.transcript.import",
        algorithm_version="1", fingerprint="t", window=window,
    )
    store.set_active(asset, "transcript", transcript)
    assignment = store.save_assignments(
        asset_id=asset,
        assignments=[SpeakerAssignment("w1", A), SpeakerAssignment("w2", B)],
        depends_on=[transcript], algorithm_id="amix.assign.v1",
        algorithm_version="1", fingerprint="as", window=window,
    )
    store.set_active(asset, "participant_assignment", assignment)
    turns = store.save_turns(
        asset_id=asset,
        turns=[
            Turn("T1", A, window.start_us, window.start_us + 100_000, ("w1",)),
            Turn("T2", B, window.start_us + 100_000, window.end_us, ("w2",)),
        ],
        depends_on=[assignment], algorithm_id="amix.turns.v1",
        algorithm_version="1", fingerprint="tu", window=window,
    )
    store.set_active(asset, "turns", turns)


def _wait(store, job_id: str, timeout: float = 8):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = store.get_processing_job(job_id)
        if last.status in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            return last
        time.sleep(0.02)
    raise AssertionError(last.status if last else "missing")


def _ffmpeg_installed() -> bool:
    try:
        discover_tools()
    except MediaToolMissing:
        return False
    return True


class SourceProgramCompileTests(unittest.TestCase):
    def test_kept_clips_fit_without_a_shot_plan(self) -> None:
        clips = [(1_000_000, 2_000_000), (3_000_000, 4_000_000)]
        landscape = compile_source_program(
            clips=clips, preset=preset_from_id("landscape_720"), fps_num=30, fps_den=1,
            container_start_us=0, source_width=1920, source_height=1080, has_audio=True,
        )
        portrait = compile_source_program(
            clips=clips, preset=preset_from_id("portrait_720"), fps_num=30, fps_den=1,
            container_start_us=0, source_width=1920, source_height=1080, has_audio=True,
        )
        self.assertEqual(landscape.total_frames, portrait.total_frames)
        self.assertEqual(len(landscape.segments), 2)
        self.assertEqual(landscape.segments[0].presentation, "source_program")
        self.assertEqual(landscape.segments[0].framing, "fit")
        self.assertIsNone(landscape.segments[0].crop_w)
        self.assertEqual(landscape.audio_spans, ((1_000_000, 2_000_000), (3_000_000, 4_000_000)))
        self.assertEqual(portrait.audio_spans, landscape.audio_spans)
        self.assertEqual(landscape.output_width, 1280)
        self.assertEqual(portrait.output_width, 720)
        self.assertEqual(portrait.output_height, 1280)

    def test_portrait_source_to_landscape_also_fits(self) -> None:
        plan = compile_source_program(
            clips=[(0, 1_000_000)], preset=preset_from_id("landscape_1080"), fps_num=25, fps_den=1,
            container_start_us=0, source_width=1080, source_height=1920, has_audio=False,
        )
        self.assertEqual(plan.segments[0].framing, "fit")
        self.assertEqual(plan.total_frames, 25)


class AxisIndependenceTests(unittest.TestCase):
    def test_picture_and_canvas_do_not_mutate_the_reel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=5, session_token="phase16"))
            session = runtime.create_project(root, "Take")
            try:
                source = root / "master.mov"
                source.write_bytes(b"master")
                asset = session.store.add_media_asset(
                    display_name="master.mov", location_kind="external", external_path=str(source),
                )
                session.store.apply_probe(asset, _probe())
                session.store.add_participant("a", "Alice")
                session.store.add_participant("b", "Bea")
                window = TimeRange(0, 4_000_000)
                session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 960, 1080, window))
                session.store.add_layout_binding(asset, LayoutBinding(B, 960, 0, 960, 1080, window))
                _seed_turns(session.store, asset, window)
                session.store.publish_overlap(
                    asset_id=asset, regions=[], algorithm_id="amix.overlap.lip_audio.v1",
                    algorithm_version="1", fingerprint="ov", window=window,
                    config={
                        "profile_id": "amix.overlap.lip_audio.v1",
                        "layout_fingerprint": layout_fingerprint(session.store.list_layout_records(asset)),
                    },
                )
                plan_id = build_automatic_plan(session.store, asset)
                candidate_id = _fake_candidate(session.store, asset, window)
                reel = create_reel_draft(session.store, asset, candidate_id)
                split = split_clip(session.store, reel["sequence_id"], reel["clips"][0]["clip_id"], 2_000_000)
                before = session.store.load_editorial_sequence_by_id(reel["sequence_id"])
                fingerprint = sequence_fingerprint(
                    before["source_start_us"], before["source_end_us"],
                    [(clip["source_start_us"], clip["source_end_us"]) for clip in before["clips"]],
                )
                discovery = session.store.get_active_run_id(asset, "reel_discovery")
                readiness = sequence_render_readiness(session.store, asset, reel["sequence_id"])
                self.assertTrue(readiness["source_program_ready"])
                self.assertTrue(readiness["multicam_ready"])
                self.assertIsNone(session.store.load_primary_sequence(asset))
                with patch.dict(os.environ, {"AMIX_RENDER_TEST_WORKER": "fail"}):
                    for treatment, profile in (
                        (SOURCE_PROGRAM, "landscape_1080"),
                        (SOURCE_PROGRAM, "portrait_1080"),
                        (MULTICAM, "portrait_1080"),
                    ):
                        job = runtime.jobs.submit(
                            session.store, RENDER_SEQUENCE,
                            {
                                "sequence_id": reel["sequence_id"],
                                "sequence_revision": before["revision"],
                                "visual_treatment": treatment,
                                "render_profile_id": profile,
                            },
                            asset,
                        )
                        finished = _wait(session.store, job.job_id)
                        self.assertEqual(finished.status, "FAILED")
                after = session.store.load_editorial_sequence_by_id(reel["sequence_id"])
                self.assertEqual(after["sequence_id"], before["sequence_id"])
                self.assertEqual(after["revision"], before["revision"])
                self.assertEqual(after["origin_candidate_id"], before["origin_candidate_id"])
                self.assertEqual(
                    [(clip["source_start_us"], clip["source_end_us"]) for clip in after["clips"]],
                    [(clip["source_start_us"], clip["source_end_us"]) for clip in before["clips"]],
                )
                self.assertEqual(session.store.get_active_run_id(asset, "reel_discovery"), discovery)
                self.assertEqual(
                    sequence_fingerprint(
                        after["source_start_us"], after["source_end_us"],
                        [(clip["source_start_us"], clip["source_end_us"]) for clip in after["clips"]],
                    ),
                    fingerprint,
                )
                self.assertEqual(session.store.list_run_ids(asset, "shot_plan"), [plan_id])
                self.assertEqual(split["revision"], before["revision"])
            finally:
                runtime.shutdown()

    def test_audio_spans_match_across_picture_treatments(self) -> None:
        clips = [(0, 1_000_000), (2_000_000, 3_000_000)]
        source = compile_source_program(
            clips=clips, preset=preset_from_id("landscape_720"), fps_num=30, fps_den=1,
            container_start_us=0, source_width=1920, source_height=1080, has_audio=True,
        )
        multicam = compile_kept_render(
            shots=[_shot("w", 0, 3_000_000)],
            clips=clips,
            bindings=[],
            preset=preset_from_id("landscape_720"),
            fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=3_000_000, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=True,
        )
        self.assertEqual(source.audio_spans, multicam.audio_spans)
        self.assertEqual(source.total_frames, multicam.total_frames)

    def test_primary_multicam_compatibility_path(self) -> None:
        shots = [_shot("w", 0, 2_000_000), _shot("f", 2_000_000, 4_000_000, "full", "a")]
        bindings = [LayoutBinding(A, 0, 0, 960, 1080, TimeRange(0, 4_000_000))]
        shared = dict(
            shots=shots, bindings=bindings, preset=preset_from_id("landscape_720"),
            fps_num=30, fps_den=1, render_start_us=0, render_end_us=4_000_000,
            container_start_us=0, source_width=1920, source_height=1080, has_audio=True,
        )
        original = compile_render(**shared)
        kept = compile_kept_render(clips=[(0, 4_000_000)], **shared)
        self.assertEqual(kept.total_frames, original.total_frames)
        self.assertEqual(
            [(item.start_frame, item.end_frame, item.presentation) for item in kept.segments],
            [(item.start_frame, item.end_frame, item.presentation) for item in original.segments],
        )


class MulticamReelTests(unittest.TestCase):
    def test_stale_plan_blocks_multicam_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            store = create_project(root, "Take")
            try:
                source = root / "master.mov"
                source.write_bytes(b"master")
                asset = store.add_media_asset(
                    display_name="master.mov", location_kind="external", external_path=str(source),
                )
                store.apply_probe(asset, _probe())
                store.add_participant("a", "Alice")
                store.add_participant("b", "Bea")
                window = TimeRange(0, 4_000_000)
                store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 960, 1080, window))
                store.add_layout_binding(asset, LayoutBinding(B, 960, 0, 960, 1080, window))
                _seed_turns(store, asset, window)
                store.publish_overlap(
                    asset_id=asset, regions=[], algorithm_id="amix.overlap.lip_audio.v1",
                    algorithm_version="1", fingerprint="ov", window=window,
                    config={
                        "profile_id": "amix.overlap.lip_audio.v1",
                        "layout_fingerprint": layout_fingerprint(store.list_layout_records(asset)),
                    },
                )
                build_automatic_plan(store, asset)
                candidate_id = _fake_candidate(store, asset, window)
                reel = create_reel_draft(store, asset, candidate_id)
                ready = sequence_render_readiness(store, asset, reel["sequence_id"])
                self.assertTrue(ready["source_program_ready"])
                self.assertTrue(ready["multicam_ready"])
                store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 100, 100, TimeRange(0, 500_000)))
                stale = sequence_render_readiness(store, asset, reel["sequence_id"])
                self.assertTrue(stale["source_program_ready"])
                self.assertFalse(stale["multicam_ready"])
                self.assertIn(stale["multicam_reason"], {"shot_plan_stale", "layout_incompatible"})
            finally:
                store.close()


class ProducingJobMigrationTests(unittest.TestCase):
    def test_proxy_job_column_renames_and_keeps_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "old.sqlite"
            upgrade_database(database, "0008_reel_discovery")
            connection = sqlite3.connect(database)
            connection.execute("INSERT INTO project (id, name, created_at) VALUES ('p', 'Old', 't')")
            connection.execute(
                "INSERT INTO media_asset (id, project_id, role, display_name, location_kind, proxy_job_id) "
                "VALUES ('m', 'p', 'proxy', 'proxy.mp4', 'managed', 'job-1')"
            )
            connection.commit()
            columns = {row[1] for row in connection.execute("PRAGMA table_info(media_asset)")}
            self.assertIn("proxy_job_id", columns)
            connection.close()
            upgrade_database(database)
            connection = sqlite3.connect(database)
            try:
                revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                columns = {row[1] for row in connection.execute("PRAGMA table_info(media_asset)")}
                value = connection.execute("SELECT producing_job_id FROM media_asset WHERE id = 'm'").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(revision, "0009_producing_job")
            self.assertIn("producing_job_id", columns)
            self.assertNotIn("proxy_job_id", columns)
            self.assertEqual(value, "job-1")


def _fake_candidate(store, asset: str, window: TimeRange) -> str:
    from amix.amix_engine.storage.kinds import REEL_DISCOVERY

    run_id = store.publish_reel_discovery(
        asset_id=asset,
        candidates=[{
            "conversation_thread_id": "thread",
            "first_turn_id": "T1",
            "last_turn_id": "T2",
            "first_word_id": "w1",
            "last_word_id": "w2",
            "start_us": window.start_us,
            "end_us": window.end_us,
            "title": "Moment",
            "summary": "A short beat",
            "hook": "It starts cleanly",
        }],
        parents=[],
        window=window,
        config={
            "profile_id": "amix.reel.discover.v1",
            "text_fingerprint": "fp",
            "transcript_run_id": store.get_active_run_id(asset, "transcript"),
            "turns_run_id": store.get_active_run_id(asset, "turns"),
            "conversation_map_run_id": "map",
            "candidate_count": 1,
        },
        origin="local",
    )
    assert store.get_active_run_id(asset, REEL_DISCOVERY) == run_id
    return store.load_reel_candidates(run_id)[0]["candidate_id"]


@unittest.skipUnless(_ffmpeg_installed(), "ffmpeg is not installed")
class SequenceRenderIntegrationTests(unittest.TestCase):
    def test_one_reel_renders_four_picture_and_canvas_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            tools = discover_tools()
            source = Path(tmp) / "synthetic.mp4"
            completed = run_process([
                str(tools.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(source),
            ], None)
            self.assertEqual(completed.code, 0, completed.stderr_tail)
            metadata = execute_probe(tools.ffprobe, source)
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=180, session_token="phase16"))
            session = runtime.create_project(root, "Take")
            try:
                asset = session.store.add_media_asset(
                    display_name="synthetic.mp4", location_kind="external", external_path=str(source),
                )
                session.store.apply_probe(
                    asset,
                    _record(metadata, source.stat().st_size, source.stat().st_mtime_ns, tools.ffprobe_version),
                )
                session.store.add_participant("a", "Alice")
                session.store.add_participant("b", "Bea")
                duration = metadata.duration_us or 1_000_000
                window = TimeRange(0, duration)
                session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 160, 180, window))
                session.store.add_layout_binding(asset, LayoutBinding(B, 160, 0, 160, 180, window))
                _seed_turns(session.store, asset, window)
                session.store.publish_overlap(
                    asset_id=asset,
                    regions=[OverlapRegion(0, min(duration, 100_000), (A, B), 0.5)],
                    algorithm_id="amix.overlap.lip_audio.v1", algorithm_version="1", fingerprint="ov",
                    window=window,
                    config={
                        "profile_id": "amix.overlap.lip_audio.v1",
                        "layout_fingerprint": layout_fingerprint(session.store.list_layout_records(asset)),
                    },
                )
                plan_id = build_automatic_plan(session.store, asset)
                candidate_id = _fake_candidate(session.store, asset, window)
                reel = create_reel_draft(session.store, asset, candidate_id)
                revision = reel["revision"]
                results = []
                for treatment, preset in (
                    (SOURCE_PROGRAM, "landscape_720"),
                    (SOURCE_PROGRAM, "portrait_720"),
                    (MULTICAM, "landscape_720"),
                    (MULTICAM, "portrait_720"),
                ):
                    job = runtime.jobs.submit(
                        session.store, RENDER_SEQUENCE,
                        {
                            "sequence_id": reel["sequence_id"],
                            "sequence_revision": revision,
                            "visual_treatment": treatment,
                            "render_profile_id": preset,
                        },
                        asset,
                    )
                    finished = _wait(session.store, job.job_id, timeout=120)
                    self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                    results.append(finished.result)
                after = session.store.load_editorial_sequence_by_id(reel["sequence_id"])
                self.assertEqual(after["revision"], revision)
                self.assertEqual(after["purpose"], "reel")
                for result in results:
                    self.assertEqual(result["sequence_id"], reel["sequence_id"])
                    self.assertEqual(result["sequence_revision"], revision)
                    self.assertEqual(result["sequence_purpose"], "reel")
                self.assertEqual(results[0]["visual_treatment"], SOURCE_PROGRAM)
                self.assertFalse(results[0]["camera_analysis_used"])
                self.assertIsNone(results[0]["shot_plan_run_id"])
                self.assertEqual(results[2]["visual_treatment"], MULTICAM)
                self.assertEqual(results[2]["shot_plan_run_id"], plan_id)
                exports = [item for item in session.store.list_media_assets() if item.role == "export"]
                self.assertEqual(len(exports), 4)
                for item in exports:
                    self.assertEqual(item.source_media_asset_id, asset)
                    self.assertIsNotNone(item.producing_job_id)
                    self.assertTrue(item.audio_codec)
                    frame_us = 1_000_000 * item.fps_den / item.fps_num
                    self.assertLess(abs(item.video_duration_us - item.audio_duration_us), max(frame_us * 4, 80_000))
                widths = {(item.width, item.height) for item in exports}
                self.assertIn((PRESETS["landscape_720"].width, PRESETS["landscape_720"].height), widths)
                self.assertIn((PRESETS["portrait_720"].width, PRESETS["portrait_720"].height), widths)
                compatibility = runtime.jobs.submit(
                    session.store, RENDER_MULTICAM, {"preset": "landscape_720", "shot_plan_run_id": plan_id}, asset,
                )
                finished = _wait(session.store, compatibility.job_id, timeout=120)
                self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                self.assertEqual(finished.result["visual_treatment"], MULTICAM)
            finally:
                runtime.shutdown()
