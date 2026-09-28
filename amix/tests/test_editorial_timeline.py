"""Editorial sequence cuts. Analyses stay on source time."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amix.amix_engine.domain.types import LayoutBinding, ParticipantId, Presentation, Shot, ShotPlan
from amix.amix_engine.editorial.sequence import (
    SequenceRejected,
    create_sequence,
    remove_clip,
    reset_sequence,
    sequence_duration_us,
    sequence_to_source_us,
    source_to_sequence_us,
    split_clip,
    validate_clips,
)
from amix.amix_engine.multicam.compile import compile_kept_render, compile_render, filter_script
from amix.amix_engine.multicam.effective import EffectiveShot, set_shot_override
from amix.amix_engine.multicam.framegrid import frame_index
from amix.amix_engine.multicam.profile import preset_from_id
from amix.amix_engine.storage.project import create_project, open_project
from amix.amix_engine.time.clock import TimeRange

A = ParticipantId("a")


def _shot(shot_id, start, end, presentation="untouched_wide", participant=None, locked=False):
    return EffectiveShot(
        shot_id, start, end, "floor", presentation, participant, "auto", None,
        presentation, participant, locked,
    )


class MappingTests(unittest.TestCase):
    def test_half_open_mapping_skips_removed_source(self) -> None:
        clips = [(0, 20), (30, 50), (70, 100)]
        self.assertEqual(sequence_duration_us(clips), 70)
        self.assertEqual(source_to_sequence_us(clips, 0), 0)
        self.assertEqual(source_to_sequence_us(clips, 19), 19)
        self.assertIsNone(source_to_sequence_us(clips, 20))
        self.assertIsNone(source_to_sequence_us(clips, 29))
        self.assertEqual(source_to_sequence_us(clips, 30), 20)
        self.assertEqual(sequence_to_source_us(clips, 20), 30)
        self.assertEqual(sequence_to_source_us(clips, 69), 99)
        self.assertIsNone(sequence_to_source_us(clips, 70))
        with self.assertRaises(SequenceRejected) as empty:
            validate_clips([(0, 0)], 0, 100)
        self.assertEqual(empty.exception.code, "invalid_clip")
        with self.assertRaises(SequenceRejected) as outside:
            validate_clips([(0, 101)], 0, 100)
        self.assertEqual(outside.exception.code, "clip_out_of_range")


class SequenceStoreTests(unittest.TestCase):
    def test_edits_keep_the_sequence_id_and_leave_the_plan(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "Take"
        store = create_project(root, "Take")
        asset = ""
        sequence_id = ""
        run_id = ""
        try:
            source = root / "master.mov"
            source.write_bytes(b"master")
            asset = store.add_media_asset(display_name="master.mov", location_kind="external", external_path=str(source))
            store.add_participant("a", "Alice")
            plan = ShotPlan(TimeRange(0, 100), (
                Shot(0, 40, Presentation.FULL, A, A, "floor"),
                Shot(40, 100, Presentation.UNTOUCHED_WIDE, None, A, "overlap"),
            ))
            run_id = store.publish_shot_plan(
                asset_id=asset, plan=plan, depends_on=[], algorithm_id="amix.multicam.plan.v1",
                algorithm_version="1", fingerprint="p", config={},
            )
            before = store.load_shot_plan(run_id)
            with self.assertRaises(SequenceRejected) as stale:
                create_sequence(store, asset)
            self.assertEqual(stale.exception.code, "plan_required")
            sequence_id = store.insert_editorial_sequence(
                asset_id=asset, display_name="Edit", source_start_us=0, source_end_us=100,
                clips=[(0, 100)],
            )
            created = store.load_editorial_sequence(asset)
            self.assertEqual(created["sequence_id"], sequence_id)
            self.assertEqual(created["revision"], 1)
            clip_id = created["clips"][0]["clip_id"]
            with self.assertRaises(SequenceRejected) as boundary:
                split_clip(store, sequence_id, clip_id, 0)
            self.assertEqual(boundary.exception.code, "split_out_of_range")
            split = split_clip(store, sequence_id, clip_id, 40)
            self.assertEqual(split["sequence_id"], sequence_id)
            self.assertEqual(split["revision"], 2)
            self.assertEqual(sequence_duration_us([(c["source_start_us"], c["source_end_us"]) for c in split["clips"]]), 100)
            removed = remove_clip(store, sequence_id, split["clips"][1]["clip_id"])
            self.assertEqual(removed["revision"], 3)
            self.assertEqual([(c["source_start_us"], c["source_end_us"]) for c in removed["clips"]], [(0, 40)])
            self.assertIsNone(source_to_sequence_us([(0, 40)], 40))
            reset = reset_sequence(store, sequence_id)
            self.assertEqual(reset["sequence_id"], sequence_id)
            self.assertEqual(reset["revision"], 4)
            self.assertEqual(store.load_shot_plan(run_id), before)
            shot_id = store.list_shot_records(run_id)[0]["shot_id"]
            set_shot_override(store, asset, run_id, shot_id, "wide", None)
            self.assertEqual(len(store.list_shot_overrides(run_id)), 1)
            self.assertEqual(store.load_shot_plan(run_id), before)
            with self.assertRaises(SequenceRejected) as overlap:
                store.replace_sequence_clips(sequence_id, [(0, 20), (10, 30)])
            self.assertEqual(overlap.exception.code, "clip_overlap")
        finally:
            store.close()
        reopened = open_project(root)
        try:
            loaded = reopened.load_editorial_sequence(asset)
            self.assertEqual(loaded["sequence_id"], sequence_id)
            self.assertEqual(loaded["revision"], 4)
            self.assertEqual(len(loaded["clips"]), 1)
            self.assertEqual(len(reopened.list_shot_overrides(run_id)), 1)
        finally:
            reopened.close()
            tmp.cleanup()


class KeptRenderTests(unittest.TestCase):
    def test_one_full_clip_matches_the_phase12_frame_count(self) -> None:
        shot = _shot("s", 0, 3_000_000)
        shared = dict(
            shots=[shot], bindings=[], preset=preset_from_id("landscape_720"), fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=3_000_000, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=True,
        )
        original = compile_render(**shared)
        kept = compile_kept_render(clips=[(0, 3_000_000)], **shared)
        self.assertEqual(kept.total_frames, original.total_frames)
        self.assertEqual(
            [segment.end_frame - segment.start_frame for segment in kept.segments],
            [segment.end_frame - segment.start_frame for segment in original.segments],
        )
        self.assertIsNone(kept.audio_spans)

    def test_removed_ranges_and_camera_intersection(self) -> None:
        shot = _shot("full", 10_000_000, 40_000_000, "full", "a")
        clips = [(0, 20_000_000), (30_000_000, 50_000_000), (70_000_000, 100_000_000)]
        plan = compile_kept_render(
            shots=[_shot("wide", 0, 10_000_000), shot, _shot("tail", 40_000_000, 100_000_000)],
            clips=clips,
            bindings=[LayoutBinding(A, 0, 0, 896, 504, TimeRange(0, 100_000_000))],
            preset=preset_from_id("portrait_720"), fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=100_000_000, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=True,
        )
        self.assertEqual(plan.end_us, 70_000_000)
        self.assertEqual(plan.total_frames, frame_index(70_000_000, 0, 30, 1))
        covered = [(segment.start_us, segment.end_us, segment.presentation) for segment in plan.segments]
        self.assertIn((10_000_000, 20_000_000, "full"), covered)
        self.assertIn((30_000_000, 40_000_000, "full"), covered)
        self.assertFalse(any(20_000_000 <= start < 30_000_000 or 50_000_000 <= start < 70_000_000 for start, _end, _kind in covered))
        self.assertEqual(shot.end_us, 40_000_000)
        script = filter_script(plan)
        self.assertEqual(script.count("fps="), 1)
        self.assertEqual(script.count("atrim="), 3)

    def test_layout_boundary_inside_a_kept_clip(self) -> None:
        shot = _shot("full", 0, 20_000_000, "full", "a")
        plan = compile_kept_render(
            shots=[shot], clips=[(0, 20_000_000)],
            bindings=[
                LayoutBinding(A, 0, 0, 896, 504, TimeRange(0, 15_000_000)),
                LayoutBinding(A, 200, 0, 896, 504, TimeRange(15_000_000, 20_000_000)),
            ],
            preset=preset_from_id("landscape_1080"), fps_num=25, fps_den=1,
            render_start_us=0, render_end_us=20_000_000, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=False,
        )
        self.assertEqual(len(plan.segments), 2)
        self.assertNotEqual(plan.segments[0].crop_x, plan.segments[1].crop_x)
        self.assertEqual(sum(item.end_frame - item.start_frame for item in plan.segments), plan.total_frames)

    def test_many_cuts_use_one_sequence_frame_grid(self) -> None:
        kept = 10_020_000
        gap = 1_000_000
        count = 400
        clips = []
        shots = []
        cursor = 0
        for index in range(count):
            clips.append((cursor, cursor + kept))
            shots.append(_shot(str(index), cursor, cursor + kept))
            cursor += kept
            if index + 1 < count:
                shots.append(_shot(f"g{index}", cursor, cursor + gap))
                cursor += gap
        duration = sequence_duration_us(clips)
        independent = frame_index(kept, 0, 30, 1) * count
        global_frames = frame_index(duration, 0, 30, 1)
        self.assertNotEqual(independent, global_frames)
        plan = compile_kept_render(
            shots=shots, clips=clips, bindings=[], preset=preset_from_id("landscape_720"),
            fps_num=30, fps_den=1, render_start_us=0, render_end_us=cursor,
            container_start_us=0, source_width=1280, source_height=720, has_audio=True,
        )
        counted = sum(segment.end_frame - segment.start_frame for segment in plan.segments)
        self.assertEqual(plan.total_frames, global_frames)
        self.assertEqual(counted, global_frames)
        self.assertNotEqual(counted, independent)
        self.assertEqual(len(plan.audio_spans), count)


def _ffmpeg_installed() -> bool:
    from amix.amix_engine.adapters.media.discovery import discover_tools
    from amix.amix_engine.adapters.media.errors import MediaToolMissing

    try:
        discover_tools()
    except MediaToolMissing:
        return False
    return True


@unittest.skipUnless(_ffmpeg_installed(), "ffmpeg is not installed")
class CutRenderIntegrationTests(unittest.TestCase):
    def test_kept_clips_render_landscape_and_portrait(self) -> None:
        from amix.amix_engine.adapters.media.discovery import discover_tools
        from amix.amix_engine.adapters.media.process import run_process
        from amix.amix_engine.adapters.media.probe import execute_probe
        from amix.amix_engine.domain.types import OverlapRegion, SpeakerAssignment, Turn, Word
        from amix.amix_engine.jobs.media import _record
        from amix.amix_engine.jobs.render import RENDER_MULTICAM
        from amix.amix_engine.layout import layout_fingerprint
        from amix.amix_engine.multicam.apply import build_automatic_plan
        from amix.amix_engine.multicam.profile import PRESETS
        from amix.amix_engine.service.config import ServiceConfig
        from amix.amix_engine.service.runtime import EngineRuntime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            tools = discover_tools()
            source = Path(tmp) / "synthetic.mp4"
            completed = run_process([
                str(tools.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(source),
            ], None)
            self.assertEqual(completed.code, 0, completed.stderr_tail)
            metadata = execute_probe(tools.ffprobe, source)
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=120, session_token="phase13"))
            session = runtime.create_project(root, "Take")
            try:
                asset = session.store.add_media_asset(
                    display_name="synthetic.mp4", location_kind="external", external_path=str(source),
                )
                session.store.apply_probe(asset, _record(metadata, source.stat().st_size, source.stat().st_mtime_ns, tools.ffprobe_version))
                session.store.add_participant("a", "Alice")
                session.store.add_participant("b", "Bea")
                duration = metadata.duration_us or 2_000_000
                window = TimeRange(0, duration)
                session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 160, 180, window))
                session.store.add_layout_binding(asset, LayoutBinding(ParticipantId("b"), 160, 0, 160, 180, window))
                words = [Word(f"w{index}", index * 400_000, index * 400_000 + 200_000, "hi") for index in range(4)]
                transcript = session.store.save_transcript(
                    asset_id=asset, words=words, algorithm_id="amix.transcript.import",
                    algorithm_version="1", fingerprint="t", window=window,
                )
                session.store.set_active(asset, "transcript", transcript)
                assignment = session.store.save_assignments(
                    asset_id=asset,
                    assignments=[SpeakerAssignment(word.word_id, A) for word in words],
                    depends_on=[transcript], algorithm_id="amix.assign.v1",
                    algorithm_version="1", fingerprint="as", window=window,
                )
                session.store.set_active(asset, "participant_assignment", assignment)
                turn_id = session.store.save_turns(
                    asset_id=asset,
                    turns=[Turn("T0001", A, window.start_us, window.end_us, tuple(word.word_id for word in words))],
                    depends_on=[assignment], algorithm_id="amix.turns.v1",
                    algorithm_version="1", fingerprint="tu", window=window,
                )
                session.store.set_active(asset, "turns", turn_id)
                session.store.publish_overlap(
                    asset_id=asset, regions=[OverlapRegion(0, min(duration, 100_000), (A, ParticipantId("b")), 0.5)],
                    algorithm_id="amix.overlap.lip_audio.v1", algorithm_version="1", fingerprint="ov",
                    window=window, config={
                        "profile_id": "amix.overlap.lip_audio.v1",
                        "layout_fingerprint": layout_fingerprint(session.store.list_layout_records(asset)),
                    },
                )
                plan_id = build_automatic_plan(session.store, asset)
                created = create_sequence(session.store, asset)
                span = created["source_end_us"] - created["source_start_us"]
                first = split_clip(session.store, created["sequence_id"], created["clips"][0]["clip_id"], created["source_start_us"] + span // 3)
                second = next(clip for clip in first["clips"] if clip["source_start_us"] > created["source_start_us"])
                cut = split_clip(session.store, created["sequence_id"], second["clip_id"], created["source_start_us"] + (2 * span) // 3)
                middle = next(clip for clip in cut["clips"] if clip["source_start_us"] == created["source_start_us"] + span // 3)
                kept = remove_clip(session.store, created["sequence_id"], middle["clip_id"])
                kept_us = sequence_duration_us([(clip["source_start_us"], clip["source_end_us"]) for clip in kept["clips"]])
                self.assertLess(kept_us, span)
                shot_id = session.store.list_shot_records(plan_id)[0]["shot_id"]
                if session.store.list_shot_records(plan_id)[0]["presentation"] != "protected_master":
                    set_shot_override(session.store, asset, plan_id, shot_id, "wide", None)
                results = []
                for preset in ("landscape_720", "portrait_720"):
                    job = runtime.jobs.submit(
                        session.store, RENDER_MULTICAM, {
                            "preset": preset,
                            "shot_plan_run_id": plan_id,
                            "sequence_id": kept["sequence_id"],
                            "sequence_revision": kept["revision"],
                        }, asset,
                    )
                    finished = _wait_job(session.store, job.job_id)
                    self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                    results.append(finished.result)
                self.assertEqual(results[0]["sequence_id"], kept["sequence_id"])
                self.assertEqual(results[0]["sequence_revision"], results[1]["sequence_revision"])
                self.assertEqual(results[0]["sequence_fingerprint"], results[1]["sequence_fingerprint"])
                self.assertNotEqual(results[0]["preset_id"], results[1]["preset_id"])
                self.assertEqual(session.store.load_editorial_sequence(asset)["revision"], kept["revision"])
                self.assertEqual(session.store.list_run_ids(asset, "shot_plan"), [plan_id])
                self.assertEqual(session.store.list_run_ids(asset, "turns"), [turn_id])
                exports = [item for item in session.store.list_media_assets() if item.role == "export"]
                self.assertEqual(len(exports), 2)
                expected = {
                    PRESETS["landscape_720"].width: PRESETS["landscape_720"].height,
                    PRESETS["portrait_720"].width: PRESETS["portrait_720"].height,
                }
                for item in exports:
                    self.assertEqual(expected[item.width], item.height)
                    frame_us = 1_000_000 * item.fps_den / item.fps_num
                    self.assertLess(abs(item.video_duration_us - item.audio_duration_us), max(frame_us * 4, 80_000))
                    self.assertLess(abs(item.duration_us - kept_us), max(frame_us * 4, 80_000))
                    self.assertGreater(abs(item.duration_us - duration), max(frame_us * 4, 80_000))
                later = split_clip(session.store, kept["sequence_id"], kept["clips"][0]["clip_id"], kept["clips"][0]["source_start_us"] + 50_000)
                self.assertGreater(later["revision"], kept["revision"])
                self.assertEqual(len([item for item in session.store.list_media_assets() if item.role == "export"]), 2)
                self.assertEqual(session.store.list_run_ids(asset, "shot_plan"), [plan_id])
            finally:
                runtime.shutdown()


def _wait_job(store, job_id: str, timeout: float = 90):
    import time
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = store.get_processing_job(job_id)
        if last.status in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            return last
        time.sleep(0.05)
    raise AssertionError(last.status if last else "missing")
