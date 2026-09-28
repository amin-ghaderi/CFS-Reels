"""Manual shot overrides and the one multicam renderer. No Reels and no cut editing."""
from __future__ import annotations

import os
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
    Presentation,
    ProtectedRegion,
    Shot,
    ShotPlan,
    SpeakerAssignment,
    Turn,
    Word,
)
from amix.amix_engine.jobs.render import RENDER_MULTICAM
from amix.amix_engine.layout import layout_fingerprint
from amix.amix_engine.multicam.apply import build_automatic_plan
from amix.amix_engine.multicam.compile import compile_render, ffmpeg_args, filter_script
from amix.amix_engine.multicam.effective import (
    OverrideRejected,
    effective_fingerprint,
    resolve_effective,
    set_shot_override,
)
from amix.amix_engine.multicam.framegrid import frame_index
from amix.amix_engine.multicam.framing import center_fill, fit_picture
from amix.amix_engine.multicam.profile import PRESETS, output_frame_rate, preset_from_id
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.project import MediaProbeRecord, create_project, open_project
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


def _shot(shot_id, start, end, presentation, participant=None, reason="floor"):
    return {
        "shot_id": shot_id,
        "start_us": start,
        "end_us": end,
        "presentation": presentation,
        "participant_id": participant,
        "floor_participant_id": participant,
        "reason": reason,
    }


def _effective(shot_id, start, end, presentation, participant=None, locked=False, reason="floor"):
    from amix.amix_engine.multicam.effective import EffectiveShot
    return EffectiveShot(
        shot_id, start, end, reason, presentation, participant, "auto", None,
        presentation, participant, locked,
    )


class FrameGridTests(unittest.TestCase):
    def test_rational_indexes_do_not_use_float_thresholds(self) -> None:
        self.assertEqual(frame_index(1_000_000, 0, 25, 1), 25)
        self.assertEqual(frame_index(1_000_000, 0, 30, 1), 30)
        self.assertEqual(frame_index(1_000_000, 0, 30000, 1001), 30)
        self.assertEqual(frame_index(1001, 0, 30000, 1001), 0)
        self.assertEqual(output_frame_rate(None, None), (30, 1))
        self.assertEqual(output_frame_rate(24000, 1001), (24000, 1001))

    def test_adjacent_boundaries_telescope(self) -> None:
        cuts = [0, 400_000, 1_000_000, 2_500_000]
        indexes = [frame_index(cut, 0, 30000, 1001) for cut in cuts]
        counted = sum(right - left for left, right in zip(indexes, indexes[1:]))
        self.assertEqual(counted, indexes[-1] - indexes[0])

    def test_long_program_does_not_accumulate_per_shot_rounding(self) -> None:
        shot_us = 10_020_000
        count = 900
        per_shot = frame_index(shot_us, 0, 30, 1)
        independent = per_shot * count
        total_us = shot_us * count
        global_frames = frame_index(total_us, 0, 30, 1)
        self.assertEqual(per_shot, 301)
        self.assertEqual(independent, 270_900)
        self.assertEqual(global_frames, 270_540)
        self.assertNotEqual(independent, global_frames)
        shots = [
            _effective(str(index), index * shot_us, (index + 1) * shot_us, "untouched_wide")
            for index in range(count)
        ]
        preset = preset_from_id("landscape_720")
        plan = compile_render(
            shots=shots, bindings=[], preset=preset, fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=total_us, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=True,
        )
        counted = sum(segment.end_frame - segment.start_frame for segment in plan.segments)
        self.assertEqual(counted, global_frames)
        self.assertEqual(plan.total_frames, global_frames)
        self.assertNotEqual(counted, independent)

    def test_zero_frame_piece_is_dropped_without_changing_the_shot(self) -> None:
        shot = _effective("s", 0, 1_000_000, "full", "a")
        bindings = [
            LayoutBinding(A, 0, 0, 320, 180, TimeRange(0, 1)),
            LayoutBinding(A, 40, 0, 280, 180, TimeRange(1, 1_000_000)),
        ]
        preset = preset_from_id("landscape_720")
        plan = compile_render(
            shots=[shot], bindings=bindings, preset=preset, fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=1_000_000, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=False,
        )
        self.assertEqual(len(plan.segments), 1)
        self.assertGreaterEqual(plan.segments[0].crop_x, 40)
        self.assertLessEqual(plan.segments[0].crop_x + plan.segments[0].crop_w, 320)
        self.assertEqual(plan.total_frames, frame_index(1_000_000, 0, 30, 1))
        self.assertEqual(shot.end_us, 1_000_000)


class FramingTests(unittest.TestCase):
    def test_sixteen_by_nine_region_scales_without_a_crop(self) -> None:
        crop = center_fill(0, 0, 896, 504, 1920, 1080)
        self.assertEqual((crop.x, crop.y, crop.w, crop.h), (0, 0, 896, 504))
        self.assertEqual(crop.w * 1080, crop.h * 1920)

    def test_portrait_center_fill_crops_inside_the_region(self) -> None:
        crop = center_fill(0, 0, 896, 504, 1080, 1920)
        self.assertEqual((crop.w, crop.h), (270, 480))
        self.assertEqual(crop.x, 312)
        self.assertEqual(crop.y, 12)
        self.assertNotEqual((crop.w, crop.h), (896, 504))
        self.assertEqual(crop.w * 1920, crop.h * 1080)
        self.assertEqual(crop.w % 2, 0)
        self.assertEqual(crop.h % 2, 0)

    def test_center_fill_both_directions_and_fit_padding(self) -> None:
        landscape = center_fill(10, 20, 270, 480, 1920, 1080)
        self.assertLess(landscape.w, 270)
        self.assertEqual(landscape.w * 1080, landscape.h * 1920)
        portrait = center_fill(0, 0, 1920, 1080, 1080, 1920)
        self.assertLess(portrait.h, 1080)
        self.assertEqual(portrait.w * 1920, portrait.h * 1080)
        fitted = fit_picture(1920, 1080, 1080, 1920)
        self.assertLess(fitted.height, 1920)
        self.assertGreater(fitted.pad_y, 0)
        self.assertNotEqual(fitted.width * 1920, fitted.height * 1080)
        wide = fit_picture(1920, 1080, 1920, 1080)
        self.assertEqual((wide.width, wide.height, wide.pad_x, wide.pad_y), (1920, 1080, 0, 0))

    def test_layout_change_inside_a_full_shot_uses_each_region(self) -> None:
        shot = _effective("s", 0, 2_000_000, "full", "a")
        bindings = [
            LayoutBinding(A, 0, 0, 896, 504, TimeRange(0, 1_000_000)),
            LayoutBinding(A, 200, 100, 896, 504, TimeRange(1_000_000, 2_000_000)),
        ]
        preset = preset_from_id("portrait_1080")
        plan = compile_render(
            shots=[shot], bindings=bindings, preset=preset, fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=2_000_000, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=True,
        )
        self.assertEqual(len(plan.segments), 2)
        self.assertNotEqual(plan.segments[0].crop_x, plan.segments[1].crop_x)
        self.assertEqual(plan.segments[1].crop_x, 200 + 312)
        self.assertEqual(shot.start_us, 0)
        self.assertEqual(shot.end_us, 2_000_000)

    def test_display_space_crop_leaves_autorotate_on(self) -> None:
        shot = _effective("s", 0, 1_000_000, "full", "a")
        bindings = [LayoutBinding(A, 100, 200, 896, 504, TimeRange(0, 1_000_000))]
        preset = preset_from_id("landscape_1080")
        plan = compile_render(
            shots=[shot], bindings=bindings, preset=preset, fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=1_000_000, container_start_us=0,
            source_width=1080, source_height=1920, has_audio=False,
        )
        self.assertEqual(plan.segments[0].crop_x, 100)
        args = ffmpeg_args("ffmpeg", "clip.mp4", Path("graph.txt"), Path("out.mp4"), plan)
        self.assertNotIn("-noautorotate", args)


class CompilerTests(unittest.TestCase):
    def test_one_renderer_compiles_landscape_and_portrait(self) -> None:
        shot = _effective("s", 0, 1_000_000, "full", "a")
        wide = _effective("w", 1_000_000, 2_000_000, "untouched_wide", reason="overlap")
        protected = _effective("p", 2_000_000, 3_000_000, "protected_master", locked=True, reason="protected")
        bindings = [LayoutBinding(A, 0, 0, 896, 504, TimeRange(0, 3_000_000))]
        shared = dict(
            shots=[shot, wide, protected], bindings=bindings, fps_num=30, fps_den=1,
            render_start_us=0, render_end_us=3_000_000, container_start_us=0,
            source_width=1920, source_height=1080, has_audio=True,
        )
        landscape = compile_render(preset=preset_from_id("landscape_1080"), **shared)
        portrait = compile_render(preset=preset_from_id("portrait_1080"), **shared)
        self.assertEqual(landscape.profile_id, portrait.profile_id)
        self.assertEqual((landscape.output_width, landscape.output_height), (1920, 1080))
        self.assertEqual((portrait.output_width, portrait.output_height), (1080, 1920))
        self.assertEqual(landscape.segments[0].framing, "center_fill")
        self.assertEqual(portrait.segments[0].crop_w, 270)
        self.assertEqual(landscape.segments[1].framing, "fit")
        self.assertEqual(landscape.segments[2].framing, "fit")
        self.assertEqual(effective_fingerprint(shared["shots"]), effective_fingerprint(shared["shots"]))
        script = filter_script(portrait)
        self.assertEqual(script.count("fps="), 1)
        self.assertEqual(script.count("atrim="), 1)
        self.assertIn("force_original_aspect_ratio=decrease", script)
        self.assertIn("pad=", script)
        self.assertIn("black", script)
        self.assertIn("crop=270:480", script)
        silent = compile_render(preset=preset_from_id("landscape_720"), has_audio=False, **{
            key: value for key, value in shared.items() if key != "has_audio"
        })
        quiet = filter_script(silent)
        self.assertNotIn("atrim=", quiet)
        args = ffmpeg_args("ffmpeg", "clip.mp4", Path("graph.txt"), Path("out.mp4"), silent)
        self.assertNotIn("-c:a", args)
        self.assertIn("-filter_complex_script", args)
        self.assertNotIn("-filter_complex", [arg for arg in args if arg != "-filter_complex_script"])

    def test_source_start_and_unicode_path_stay_on_the_ffmpeg_boundary(self) -> None:
        shot = _effective("s", 1_500_000, 2_500_000, "untouched_wide")
        plan = compile_render(
            shots=[shot], bindings=[], preset=preset_from_id("landscape_720"),
            fps_num=25, fps_den=1, render_start_us=1_500_000, render_end_us=2_500_000,
            container_start_us=1_500_000, source_width=1280, source_height=720, has_audio=True,
        )
        self.assertEqual(plan.source_start_us, 0)
        self.assertEqual(shot.start_us, 1_500_000)
        script = filter_script(plan)
        self.assertIn("trim=start=0.000000:end=1.000000", script)
        self.assertIn("atrim=start=0.000000:end=1.000000", script)
        source = "C:/رسانه/برنامه.mp4"
        args = ffmpeg_args("ffmpeg", source, Path("graph.txt"), Path("out.mp4"), plan)
        self.assertIn(source, args)
        self.assertEqual(args[0], "ffmpeg")

    def test_many_shots_use_one_filter_script(self) -> None:
        shots = [
            _effective(str(index), index * 1_000_000, (index + 1) * 1_000_000, "untouched_wide")
            for index in range(40)
        ]
        plan = compile_render(
            shots=shots, bindings=[], preset=preset_from_id("portrait_720"),
            fps_num=30, fps_den=1, render_start_us=0, render_end_us=40_000_000,
            container_start_us=0, source_width=1920, source_height=1080, has_audio=True,
        )
        script = filter_script(plan)
        self.assertIn("split=40", script)
        self.assertEqual(script.count("fps="), 1)
        self.assertEqual(script.count("atrim="), 1)
        args = ffmpeg_args("ffmpeg", "clip.mp4", Path("graph.txt"), Path("out.mp4"), plan)
        self.assertIn("-filter_complex_script", args)
        self.assertTrue(all(not arg.startswith("[0:v]") for arg in args))


class OverrideTests(unittest.TestCase):
    def test_effective_plan_precedence(self) -> None:
        records = [
            _shot("wide", 0, 2, "untouched_wide", reason="overlap"),
            _shot("full", 2, 4, "full", "a"),
            _shot("lock", 4, 6, "protected_master", reason="protected"),
        ]
        overrides = [
            {"shot_id": "wide", "decision": "full", "participant_id": "b"},
            {"shot_id": "lock", "decision": "wide", "participant_id": None},
        ]
        resolved = resolve_effective(records, overrides)
        self.assertEqual(resolved[0].effective_presentation, "full")
        self.assertEqual(resolved[0].effective_participant_id, "b")
        self.assertEqual(resolved[0].automatic_presentation, "untouched_wide")
        self.assertEqual(resolved[2].effective_presentation, "protected_master")
        self.assertTrue(resolved[2].locked)
        self.assertEqual(resolved[2].override_decision, "auto")

    def _project(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "Take"
        store = create_project(root, "Take")
        source = root / "master.mov"
        source.write_bytes(b"master")
        asset = store.add_media_asset(display_name="master.mov", location_kind="external", external_path=str(source))
        store.apply_probe(asset, _probe())
        store.add_participant("a", "Alice")
        store.add_participant("b", "Bea")
        store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 896, 504, TimeRange(0, 5_000_000)))
        store.add_layout_binding(asset, LayoutBinding(B, 900, 0, 896, 504, TimeRange(0, 1_000_000)))
        plan = ShotPlan(TimeRange(0, 5_000_000), (
            Shot(0, 2_000_000, Presentation.FULL, A, A, "floor"),
            Shot(2_000_000, 4_000_000, Presentation.UNTOUCHED_WIDE, None, A, "overlap"),
            Shot(4_000_000, 5_000_000, Presentation.PROTECTED_MASTER, None, None, "protected"),
        ))
        run_id = store.publish_shot_plan(
            asset_id=asset, plan=plan, depends_on=[], algorithm_id="amix.multicam.plan.v1",
            algorithm_version="1", fingerprint="p", config={},
        )
        return tmp, store, asset, run_id

    def test_overrides_are_stored_beside_the_automatic_plan(self) -> None:
        tmp, store, asset, run_id = self._project()
        try:
            before = store.load_shot_plan(run_id)
            records = store.list_shot_records(run_id)
            wide_id = records[1]["shot_id"]
            full_id = records[0]["shot_id"]
            locked_id = records[2]["shot_id"]
            set_shot_override(store, asset, run_id, wide_id, "wide", None)
            set_shot_override(store, asset, run_id, wide_id, "full", "a")
            self.assertEqual(len(store.list_shot_overrides(run_id)), 1)
            self.assertEqual(store.list_shot_overrides(run_id)[0]["decision"], "full")
            self.assertEqual(store.load_shot_plan(run_id), before)
            described = __import__("amix.amix_engine.multicam.effective", fromlist=["describe_shots"]).describe_shots(store, asset)
            chosen = next(shot for shot in described["shots"] if shot["shot_id"] == wide_id)
            self.assertTrue(chosen["overridden"])
            self.assertEqual(chosen["presentation"], "full")
            self.assertEqual(chosen["automatic_presentation"], "untouched_wide")
            set_shot_override(store, asset, run_id, wide_id, "auto", None)
            self.assertEqual(store.list_shot_overrides(run_id), [])
            with self.assertRaises(OverrideRejected) as protected:
                set_shot_override(store, asset, run_id, locked_id, "wide", None)
            self.assertEqual(protected.exception.code, "protected_locked")
            with self.assertRaises(OverrideRejected) as missing:
                set_shot_override(store, asset, run_id, full_id, "full", "missing")
            self.assertEqual(missing.exception.code, "unknown_participant")
            with self.assertRaises(OverrideRejected) as uncovered:
                set_shot_override(store, asset, run_id, full_id, "full", "b")
            self.assertEqual(uncovered.exception.code, "layout_not_covering")
            self.assertEqual(store.load_shot_plan(run_id), before)
            choices = next(shot for shot in described["shots"] if shot["shot_id"] == full_id)["full_choices"]
            self.assertEqual([choice["participant_id"] for choice in choices], ["a"])
        finally:
            store.close()
            tmp.cleanup()

    def test_a_new_plan_does_not_inherit_overrides(self) -> None:
        tmp, store, asset, run_id = self._project()
        try:
            shot_id = store.list_shot_records(run_id)[1]["shot_id"]
            set_shot_override(store, asset, run_id, shot_id, "wide", None)
            replacement = ShotPlan(TimeRange(0, 5_000_000), (
                Shot(0, 5_000_000, Presentation.UNTOUCHED_WIDE, None, A, "floor"),
            ))
            second = store.publish_shot_plan(
                asset_id=asset, plan=replacement, depends_on=[], algorithm_id="amix.multicam.plan.v1",
                algorithm_version="1", fingerprint="q", config={},
            )
            self.assertEqual(len(store.list_shot_overrides(run_id)), 1)
            self.assertEqual(store.list_shot_overrides(second), [])
            from amix.amix_engine.multicam.effective import describe_shots
            current = describe_shots(store, asset)
            self.assertEqual(current["run_id"], second)
            self.assertTrue(all(not shot["overridden"] for shot in current["shots"]))
            self.assertEqual(store.load_shot_plan(run_id).shots[1].presentation, Presentation.UNTOUCHED_WIDE)
        finally:
            store.close()
            tmp.cleanup()


def _seed_turns(store, asset: str, window: TimeRange) -> None:
    words = [Word(f"w{index}", index * 500_000, index * 500_000 + 200_000, "hi") for index in range(8)]
    transcript = store.save_transcript(
        asset_id=asset, words=words, algorithm_id="amix.transcript.import",
        algorithm_version="1", fingerprint="t", window=window,
    )
    store.set_active(asset, "transcript", transcript)
    assignment = store.save_assignments(
        asset_id=asset,
        assignments=[SpeakerAssignment(word.word_id, A) for word in words],
        depends_on=[transcript], algorithm_id="amix.assign.v1",
        algorithm_version="1", fingerprint="as", window=window,
    )
    store.set_active(asset, "participant_assignment", assignment)
    turn_id = store.save_turns(
        asset_id=asset,
        turns=[Turn("T0001", A, window.start_us, window.end_us, tuple(word.word_id for word in words))],
        depends_on=[assignment], algorithm_id="amix.turns.v1",
        algorithm_version="1", fingerprint="tu", window=window,
    )
    store.set_active(asset, "turns", turn_id)


class RenderJobTests(unittest.TestCase):
    def _ready(self, root: Path):
        runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=5, session_token="phase12"))
        session = runtime.create_project(root, "Take")
        source = root / "master.mov"
        source.write_bytes(b"master")
        asset = session.store.add_media_asset(
            display_name="master.mov", location_kind="external", external_path=str(source),
        )
        session.store.apply_probe(asset, _probe(width=320, height=180))
        session.store.add_participant("a", "Alice")
        session.store.add_participant("b", "Bea")
        window = TimeRange(0, 4_000_000)
        session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 160, 180, window))
        session.store.add_layout_binding(asset, LayoutBinding(B, 160, 0, 160, 180, window))
        _seed_turns(session.store, asset, window)
        session.store.publish_overlap(
            asset_id=asset, regions=[], algorithm_id="amix.overlap.lip_audio.v1",
            algorithm_version="1", fingerprint="ov", window=window,
            config={"profile_id": "amix.overlap.lip_audio.v1", "layout_fingerprint": layout_fingerprint(session.store.list_layout_records(asset))},
        )
        session.store.add_protected_region(asset, ProtectedRegion(TimeRange(3_000_000, 3_200_000)))
        plan_id = build_automatic_plan(session.store, asset)
        return runtime, session, asset, plan_id, source

    def test_cancel_and_failure_do_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session, asset, plan_id, _source = self._ready(root)
            try:
                before = session.store.load_shot_plan(plan_id)
                shot_id = session.store.list_shot_records(plan_id)[0]["shot_id"]
                set_shot_override(session.store, asset, plan_id, shot_id, "wide", None)
                with patch.dict(os.environ, {"AMIX_RENDER_TEST_WORKER": "fail"}):
                    failed = runtime.jobs.submit(
                        session.store, RENDER_MULTICAM, {"preset": "landscape_720", "shot_plan_run_id": plan_id}, asset,
                    )
                    failed = _wait(session.store, failed.job_id)
                self.assertEqual(failed.status, "FAILED")
                self.assertFalse(any(item.role == "export" for item in session.store.list_media_assets()))
                with patch.dict(os.environ, {"AMIX_RENDER_TEST_WORKER": "wait"}):
                    waiting = runtime.jobs.submit(
                        session.store, RENDER_MULTICAM, {"preset": "portrait_720", "shot_plan_run_id": plan_id}, asset,
                    )
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if session.store.get_processing_job(waiting.job_id).status == "RUNNING":
                            break
                        time.sleep(0.02)
                    runtime.jobs.cancel(session.store, waiting.job_id)
                    self.assertTrue(runtime.jobs.wait_until_idle(session.store, 5))
                cancelled = session.store.get_processing_job(waiting.job_id)
                self.assertEqual(cancelled.status, "CANCELLED")
                self.assertFalse((root / "exports" / f"{waiting.job_id}.mp4").exists())
                self.assertFalse((root / "exports" / ".tmp" / f"{waiting.job_id}.mp4").exists())
                self.assertEqual(session.store.load_shot_plan(plan_id), before)
                self.assertEqual(len(session.store.list_shot_overrides(plan_id)), 1)
                self.assertFalse(any(item.role == "export" for item in session.store.list_media_assets()))
            finally:
                runtime.shutdown()

    def test_shutdown_cancels_the_renderer_before_the_lock_drops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session, asset, plan_id, _source = self._ready(root)
            with patch.dict(os.environ, {"AMIX_RENDER_TEST_WORKER": "wait"}):
                waiting = runtime.jobs.submit(
                    session.store, RENDER_MULTICAM, {"preset": "landscape_1080", "shot_plan_run_id": plan_id}, asset,
                )
                job_id = waiting.job_id
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if session.store.get_processing_job(job_id).status == "RUNNING":
                        break
                    time.sleep(0.02)
                runtime.shutdown()
            store = open_project(root)
            try:
                self.assertEqual(store.get_processing_job(job_id).status, "CANCELLED")
                self.assertFalse(any(item.role == "export" for item in store.list_media_assets()))
            finally:
                store.close()

    def test_invalid_requests_fail_before_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session, asset, plan_id, source = self._ready(root)
            try:
                rejected = runtime.jobs.submit(session.store, RENDER_MULTICAM, {"preset": "reel"}, asset)
                rejected = _wait(session.store, rejected.job_id)
                self.assertEqual(rejected.error_code, "invalid_render_preset")
                session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 80, 80, TimeRange(0, 1_000_000)))
                stale = runtime.jobs.submit(
                    session.store, RENDER_MULTICAM, {"preset": "landscape_720", "shot_plan_run_id": plan_id}, asset,
                )
                stale = _wait(session.store, stale.job_id)
                self.assertEqual(stale.error_code, "plan_stale")
                source.unlink()
                missing = runtime.jobs.submit(
                    session.store, RENDER_MULTICAM, {"preset": "landscape_720"}, asset,
                )
                missing = _wait(session.store, missing.job_id)
                self.assertEqual(missing.error_code, "media_missing")
                self.assertFalse(any(item.role == "export" for item in session.store.list_media_assets()))
            finally:
                runtime.shutdown()


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


@unittest.skipUnless(_ffmpeg_installed(), "ffmpeg is not installed")
class RenderIntegrationTests(unittest.TestCase):
    def test_one_plan_renders_landscape_and_portrait(self) -> None:
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
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=120, session_token="phase12"))
            session = runtime.create_project(root, "Take")
            try:
                asset = session.store.add_media_asset(
                    display_name="synthetic.mp4", location_kind="external", external_path=str(source),
                )
                from amix.amix_engine.jobs.media import _record
                session.store.apply_probe(asset, _record(metadata, source.stat().st_size, source.stat().st_mtime_ns, tools.ffprobe_version))
                session.store.add_participant("a", "Alice")
                session.store.add_participant("b", "Bea")
                duration = metadata.duration_us or 1_000_000
                window = TimeRange(0, duration)
                session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 160, 180, window))
                session.store.add_layout_binding(asset, LayoutBinding(B, 160, 0, 160, 180, window))
                _seed_turns(session.store, asset, window)
                session.store.publish_overlap(
                    asset_id=asset, regions=[OverlapRegion(0, min(duration, 100_000), (A, B), 0.5)],
                    algorithm_id="amix.overlap.lip_audio.v1", algorithm_version="1", fingerprint="ov",
                    window=window, config={
                        "profile_id": "amix.overlap.lip_audio.v1",
                        "layout_fingerprint": layout_fingerprint(session.store.list_layout_records(asset)),
                    },
                )
                plan_id = build_automatic_plan(session.store, asset)
                results = []
                for preset in ("landscape_720", "portrait_720"):
                    job = runtime.jobs.submit(
                        session.store, RENDER_MULTICAM, {"preset": preset, "shot_plan_run_id": plan_id}, asset,
                    )
                    finished = _wait(session.store, job.job_id, timeout=90)
                    self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                    self.assertEqual(finished.progress_bp, 10000)
                    results.append(finished.result)
                self.assertEqual(results[0]["shot_plan_run_id"], results[1]["shot_plan_run_id"])
                self.assertEqual(session.store.list_run_ids(asset, "shot_plan"), [plan_id])
                self.assertEqual(results[0]["effective_fingerprint"], results[1]["effective_fingerprint"])
                self.assertNotEqual(results[0]["preset_id"], results[1]["preset_id"])
                exports = [item for item in session.store.list_media_assets() if item.role == "export"]
                self.assertEqual(len(exports), 2)
                expected = {PRESETS["landscape_720"].width: PRESETS["landscape_720"].height, PRESETS["portrait_720"].width: PRESETS["portrait_720"].height}
                for item in exports:
                    self.assertEqual(item.source_media_asset_id, asset)
                    self.assertEqual(expected[item.width], item.height)
                    self.assertEqual((item.fps_num, item.fps_den), (metadata.fps_num, metadata.fps_den))
                    self.assertTrue(item.audio_codec)
                    self.assertIsNotNone(item.duration_us)
                    self.assertIsNotNone(item.video_duration_us)
                    self.assertIsNotNone(item.audio_duration_us)
                    frame_us = 1_000_000 * item.fps_den / item.fps_num
                    self.assertLess(abs(item.video_duration_us - item.audio_duration_us), max(frame_us * 4, 80_000))
                    self.assertLess(abs(item.duration_us - duration), max(frame_us * 4, 80_000))
            finally:
                runtime.shutdown()
