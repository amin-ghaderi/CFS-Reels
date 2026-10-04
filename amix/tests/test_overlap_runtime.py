"""Overlap extraction and automatic multicam planning. No YuNet download and no master video."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from amix.amix_engine.adapters.vision.extract import measure_frames
from amix.amix_engine.adapters.vision.geometry import (
    binding_at,
    clip_rect,
    display_video_filter,
    participants_in_window,
)
from amix.amix_engine.adapters.vision.lips import FaceSample, frame_rms
from amix.amix_engine.adapters.vision.profile import PROFILE_ID
from amix.amix_engine.adapters.vision.resolver import resolve_vision_model, vision_model_status
from amix.amix_engine.analysis.overlap import overlap_regions
from amix.amix_engine.domain.types import (
    LayoutBinding,
    LipActivitySeries,
    OverlapRegion,
    ParticipantId,
    Presentation,
    ProtectedRegion,
    SpeakerAssignment,
    Turn,
    Word,
)
from amix.amix_engine.jobs.multicam import BUILD_MULTICAM_PLAN
from amix.amix_engine.jobs.overlap import DETECT_OVERLAP
from amix.amix_engine.layout import layout_fingerprint, protected_fingerprint
from amix.amix_engine.multicam.apply import build_automatic_plan, multicam_readiness
from amix.amix_engine.multicam.planner import plan_shots
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.project import MediaProbeRecord, create_project, private_directory
from amix.amix_engine.time.clock import TimeRange
from amix.amix_engine.workers.overlap import video_command

A = ParticipantId("a")
B = ParticipantId("b")
C = ParticipantId("c")
PERIOD = 125_000


def _alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False, shell=False,
    )
    return str(pid) in completed.stdout


def _wait_job(store, job_id: str, timeout: float = 8):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = store.get_processing_job(job_id)
        if last.status in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            return last
        time.sleep(0.02)
    raise AssertionError(last)


def _wait_file(path: Path, timeout: float = 5) -> str:
    from amix.amix_engine.adapters.media.publish import read_pid

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            pid = read_pid(path)
            if pid is None:
                raise AssertionError(f"incomplete pid marker: {path.read_text(encoding='utf-8')!r}")
            return str(pid)
        time.sleep(0.02)
    raise AssertionError(path)


def _probe(**overrides) -> MediaProbeRecord:
    values = dict(
        container="mov", duration_us=2_000_000, duration_source="container",
        container_start_us=0, bit_rate=1, video_codec="h264", width=320, height=180,
        pixel_format="yuv420p", fps_num=25, fps_den=1, r_fps_num=25, r_fps_den=1,
        time_base_num=1, time_base_den=12800, video_start_us=0, video_duration_us=2_000_000,
        rotation_degrees=0, audio_codec="aac", sample_rate=48000, audio_channels=2,
        channel_layout="stereo", audio_start_us=0, audio_duration_us=2_000_000,
        byte_size=4, file_mtime_ns=1, probe_tool="ffprobe version test", probe_config="amix.probe.v1",
    )
    values.update(overrides)
    return MediaProbeRecord(**values)


def _activity(start: int, frames: int, people: list[str]) -> dict:
    width = len(people)
    return {
        "profile_id": PROFILE_ID,
        "origin_us": start,
        "sample_period_us": PERIOD,
        "participant_ids": people,
        "scores": [[0.0] * width for _ in range(frames)],
        "audio_rms": [0.0] * frames,
        "model_identity": "test-model",
        "opencv_version": "test",
    }


class _Means:
    def __init__(self) -> None:
        self.means: list[float] = []

    def detect(self, frame: np.ndarray) -> list[FaceSample]:
        self.means.append(float(frame.mean()))
        return []


class VisionResolverTests(unittest.TestCase):
    def test_missing_model_does_not_download(self) -> None:
        source = Path(resolve_vision_model.__code__.co_filename).read_text(encoding="utf-8")
        self.assertNotIn("urlopen", source)
        self.assertNotIn("github.com", source)
        self.assertNotIn(".cache", source)
        with patch.dict(os.environ, {"AMIX_YUNET_MODEL_PATH": ""}, clear=False):
            os.environ.pop("AMIX_YUNET_MODEL_PATH", None)
            status = vision_model_status()
            self.assertIn(status.state, {"MODEL_MISSING", "RUNTIME_UNAVAILABLE"})
            if status.state == "MODEL_MISSING":
                with self.assertRaises(Exception) as caught:
                    resolve_vision_model()
                self.assertEqual(caught.exception.code, "vision_model_missing")

    def test_invalid_explicit_path_does_not_fall_through(self) -> None:
        with patch.dict(os.environ, {"AMIX_YUNET_MODEL_PATH": str(Path(tempfile.gettempdir()) / "missing-yunet.onnx")}):
            status = vision_model_status()
            if status.state == "RUNTIME_UNAVAILABLE":
                self.skipTest("opencv is not installed")
            self.assertEqual(status.state, "INVALID_MODEL")
            with self.assertRaises(Exception) as caught:
                resolve_vision_model()
            self.assertEqual(caught.exception.code, "invalid_vision_model")


@unittest.skipUnless(os.environ.get("AMIX_YUNET_MODEL_PATH"), "YuNet model is not configured")
class YunetIntegrationTests(unittest.TestCase):
    def test_configured_model_is_a_local_file(self) -> None:
        descriptor = resolve_vision_model()
        self.assertTrue(Path(descriptor.local_path).is_file())
        self.assertEqual(descriptor.runtime, "opencv")
        self.assertTrue(descriptor.identity)


class GeometryTests(unittest.TestCase):
    def test_crop_follows_the_binding_and_a_later_interval(self) -> None:
        early = LayoutBinding(A, 0, 0, 20, 20, TimeRange(0, 125_000))
        later = LayoutBinding(A, 20, 0, 20, 20, TimeRange(125_000, 250_000))
        other = LayoutBinding(B, 20, 0, 20, 20, TimeRange(0, 250_000))
        self.assertEqual(binding_at([early, later, other], A, 0), early)
        self.assertEqual(binding_at([early, later, other], A, 125_000), later)
        self.assertIsNone(binding_at([
            LayoutBinding(A, 0, 0, 20, 20, TimeRange(0, 200_000)),
            LayoutBinding(A, 20, 0, 20, 20, TimeRange(0, 200_000)),
        ], A, 0))
        frame = np.zeros((30, 40, 3), dtype=np.uint8)
        frame[:, :20] = 255
        detector = _Means()
        series = measure_frames(
            [frame, frame],
            np.zeros(4000, dtype=np.float32),
            [early, later, other],
            (A, B),
            origin_us=0,
            sample_period_us=PERIOD,
            detector=detector,
            width=40,
            height=30,
        )
        self.assertEqual(len(detector.means), 4)
        self.assertGreater(detector.means[0], detector.means[1])
        self.assertLess(detector.means[2], 10.0)
        self.assertEqual(series.participant_ids, (A, B))
        self.assertEqual(series.scores[0], (0.0, 0.0))

    def test_display_rotation_uses_display_pixels(self) -> None:
        self.assertEqual(display_video_filter(None), "fps=8")
        self.assertIn("transpose=1", display_video_filter(90))
        self.assertIn("transpose=2", display_video_filter(-90))
        self.assertIn("hflip,vflip", display_video_filter(180))
        display_w, display_h = 200, 100
        self.assertIsNotNone(clip_rect(display_w, display_h, 150, 10, 40, 40))
        self.assertIsNone(clip_rect(100, 200, 150, 10, 40, 40))
        command = video_command("ffmpeg", str(Path("مصدر.mov")), 0, 1_000_000, 0, 90, display_w, display_h)
        self.assertIsInstance(command, list)
        self.assertIn("-noautorotate", command)
        self.assertIn("مصدر.mov", command)
        self.assertNotIn("1920", " ".join(command))

    def test_audio_rms_follows_the_sample_index(self) -> None:
        audio = np.concatenate([np.ones(2000, dtype=np.float32), np.zeros(2000, dtype=np.float32)])
        self.assertAlmostEqual(frame_rms(audio, 0, 16000, 8), 1.0)
        self.assertAlmostEqual(frame_rms(audio, 1, 16000, 8), 0.0)
        series = measure_frames(
            [np.zeros((30, 40, 3), dtype=np.uint8), np.zeros((30, 40, 3), dtype=np.uint8)],
            audio,
            [LayoutBinding(A, 0, 0, 20, 20, TimeRange(0, 1_000_000))],
            (A,),
            origin_us=0,
            sample_period_us=PERIOD,
            detector=_Means(),
            width=40,
            height=30,
        )
        self.assertAlmostEqual(series.audio_rms[0], 1.0)
        self.assertAlmostEqual(series.audio_rms[1], 0.0)

    def test_product_overlap_code_has_no_fixed_frame(self) -> None:
        root = Path(__file__).resolve().parents[1] / "amix_engine"
        banned_files = [
            root / "adapters" / "vision" / "geometry.py",
            root / "adapters" / "vision" / "lips.py",
            root / "adapters" / "vision" / "extract.py",
            root / "jobs" / "overlap.py",
            root / "workers" / "overlap.py",
            root / "service" / "app.py",
        ]
        for path in banned_files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("1920", text, path.name)
            self.assertNotIn("speaker_a", text, path.name)
            if path.name in {"app.py", "overlap.py"} and "workers" not in str(path):
                self.assertNotIn("FaceDetectorYN", text, path.name)


class OverlapJobTests(unittest.TestCase):
    def _runtime(self, root: Path):
        runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase11"))
        session = runtime.create_project(root, "Take")
        return runtime, session

    def _source(self, root: Path, name: str = "master.mov") -> tuple[str, Path]:
        path = root / name
        path.write_bytes(b"source-bytes")
        return name, path

    def _prepare(self, session, root: Path, name: str = "master.mov"):
        _name, path = self._source(root, name)
        asset = session.store.add_media_asset(display_name=name, location_kind="external", external_path=str(path))
        session.store.add_participant("a", "Alice")
        session.store.add_participant("b", "Bea")
        span = TimeRange(0, 5_000_000)
        session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 80, 80, span))
        session.store.add_layout_binding(asset, LayoutBinding(B, 100, 0, 80, 80, span))
        return asset, path

    def _emit(self, runtime, session, asset, evidence: dict, spec: dict):
        path = session.store.root / "activity.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        with patch.dict(os.environ, {"AMIX_OVERLAP_TEST_WORKER": "emit", "AMIX_OVERLAP_TEST_EVIDENCE": str(path)}):
            job = runtime.jobs.submit(session.store, DETECT_OVERLAP, spec, asset)
            return _wait_job(session.store, job.job_id)

    def test_explicit_window_is_fingerprinted_and_activated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session = self._runtime(root)
            try:
                asset, path = self._prepare(session, root)
                session.store.apply_probe(asset, _probe(duration_us=2_000_000))
                finished = self._emit(runtime, session, asset, _activity(0, 8, ["a", "b"]), {"start_us": 0, "end_us": 1_000_000})
                self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                run_id = finished.result["overlap_run_id"]
                self.assertEqual(session.store.get_active_run_id(asset, "overlap"), run_id)
                self.assertEqual(session.store.run_dependencies(run_id), [])
                record = session.store.analysis_record(run_id)
                self.assertEqual(record["window_start_us"], 0)
                self.assertEqual(record["window_end_us"], 1_000_000)
                self.assertEqual(record["config"]["layout_fingerprint"], layout_fingerprint(session.store.list_layout_records(asset)))
                self.assertNotIn("turn_run_id", record["config"])
                self.assertEqual(record["config"]["profile_id"], PROFILE_ID)
                self.assertEqual(record["config"]["source_size"], path.stat().st_size)
                self.assertFalse(record["config"]["activity_retained"])
                wider = self._emit(runtime, session, asset, _activity(0, 16, ["a", "b"]), {"start_us": 0, "end_us": 2_000_000})
                self.assertEqual(wider.status, "SUCCEEDED", wider.error_message)
                self.assertNotEqual(record["fingerprint"], session.store.analysis_record(wider.result["overlap_run_id"])["fingerprint"])
                self.assertEqual(session.store.load_overlaps(run_id), [])
                self.assertEqual(len(session.store.list_run_ids(asset, "overlap")), 2)
            finally:
                runtime.shutdown()

    def test_default_window_is_the_full_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session = self._runtime(root)
            try:
                asset, _path = self._prepare(session, root)
                session.store.apply_probe(asset, _probe(duration_us=1_000_000))
                finished = self._emit(runtime, session, asset, _activity(0, 8, ["a", "b"]), {"profile": PROFILE_ID})
                self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                record = session.store.analysis_record(finished.result["overlap_run_id"])
                self.assertEqual(record["window_end_us"], 1_000_000)
            finally:
                runtime.shutdown()

    def test_unicode_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session = self._runtime(root)
            try:
                asset, path = self._prepare(session, root, "مصدر.mov")
                finished = self._emit(runtime, session, asset, _activity(0, 8, ["a", "b"]), {"start_us": 0, "end_us": 1_000_000})
                self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                self.assertEqual(session.store.analysis_record(finished.result["overlap_run_id"])["config"]["source_size"], path.stat().st_size)
            finally:
                runtime.shutdown()

    def test_layout_change_stales_overlap_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session = self._runtime(root)
            try:
                asset, _path = self._prepare(session, root)
                finished = self._emit(runtime, session, asset, _activity(0, 8, ["a", "b"]), {"start_us": 0, "end_us": 1_000_000})
                run_id = finished.result["overlap_run_id"]
                session.store.add_participant("c", "Cara")
                session.store.add_layout_binding(asset, LayoutBinding(C, 0, 90, 80, 40, TimeRange(0, 5_000_000)))
                ready = multicam_readiness(session.store, asset)
                self.assertTrue(ready["overlap_stale"])
                self.assertEqual(ready["overlap_run_id"], run_id)
                self.assertEqual(session.store.get_active_run_id(asset, "overlap"), run_id)
            finally:
                runtime.shutdown()

    def test_failure_and_cancel_keep_the_previous_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session = self._runtime(root)
            try:
                asset, _path = self._prepare(session, root)
                first = self._emit(runtime, session, asset, _activity(0, 8, ["a", "b"]), {"start_us": 0, "end_us": 1_000_000})
                run_id = first.result["overlap_run_id"]
                with patch.dict(os.environ, {"AMIX_OVERLAP_TEST_WORKER": "fail"}):
                    failed = runtime.jobs.submit(session.store, DETECT_OVERLAP, {"start_us": 0, "end_us": 1_000_000}, asset)
                    failed = _wait_job(session.store, failed.job_id)
                self.assertEqual(failed.status, "FAILED")
                self.assertEqual(session.store.get_active_run_id(asset, "overlap"), run_id)
                with patch.dict(os.environ, {"AMIX_OVERLAP_TEST_WORKER": "wait"}):
                    waiting = runtime.jobs.submit(session.store, DETECT_OVERLAP, {"start_us": 0, "end_us": 1_000_000}, asset)
                    child = int(_wait_file(private_directory(root) / ".overlap" / waiting.job_id / "child.pid"))
                    worker = int(_wait_file(private_directory(root) / ".overlap" / waiting.job_id / "worker.pid"))
                    self.assertTrue(_alive(worker))
                    self.assertTrue(_alive(child))
                    runtime.jobs.cancel(session.store, waiting.job_id)
                    self.assertTrue(runtime.jobs.wait_until_idle(session.store, 5))
                cancelled = session.store.get_processing_job(waiting.job_id)
                self.assertEqual(cancelled.status, "CANCELLED")
                self.assertFalse(_alive(worker))
                self.assertFalse(_alive(child))
                self.assertEqual(session.store.get_active_run_id(asset, "overlap"), run_id)
                self.assertEqual(session.store.list_run_ids(asset, "overlap"), [run_id])
                self.assertFalse((private_directory(root) / ".overlap" / waiting.job_id).exists())
            finally:
                runtime.shutdown()

    def test_rejected_spec_and_missing_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session = self._runtime(root)
            try:
                asset, _path = self._prepare(session, root)
                rejected = runtime.jobs.submit(session.store, DETECT_OVERLAP, {"threshold": 1, "model_path": "x"}, asset)
                rejected = _wait_job(session.store, rejected.job_id)
                self.assertEqual(rejected.status, "FAILED")
                self.assertEqual(rejected.error_code, "job_spec_rejected")
                bare = session.store.add_media_asset(
                    display_name="bare.mov",
                    location_kind="external",
                    external_path=str(root / "master.mov"),
                )
                missing = runtime.jobs.submit(session.store, DETECT_OVERLAP, {"start_us": 0, "end_us": 1_000_000}, bare)
                missing = _wait_job(session.store, missing.job_id)
                self.assertEqual(missing.error_code, "insufficient_layout")
                self.assertEqual(session.store.list_run_ids(asset, "overlap"), [])
            finally:
                runtime.shutdown()

    def test_turn_change_does_not_stale_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime, session = self._runtime(root)
            try:
                asset, _path = self._prepare(session, root)
                finished = self._emit(runtime, session, asset, _activity(0, 8, ["a", "b"]), {"start_us": 0, "end_us": 1_000_000})
                run_id = finished.result["overlap_run_id"]
                _seed_turns(session.store, asset, TimeRange(0, 1_000_000), prefix="w")
                ready = multicam_readiness(session.store, asset)
                self.assertFalse(ready["overlap_stale"])
                self.assertEqual(ready["overlap_run_id"], run_id)
            finally:
                runtime.shutdown()

    def test_regions_come_from_the_existing_builder(self) -> None:
        series = LipActivitySeries(0, PERIOD, (A, B), tuple((0.0, 0.0) for _ in range(8)), tuple(0.0 for _ in range(8)))
        self.assertEqual(overlap_regions(series, TimeRange(0, 1_000_000)), [])
        people = participants_in_window(
            [LayoutBinding(B, 0, 0, 10, 10, TimeRange(0, 10)), LayoutBinding(A, 0, 0, 10, 10, TimeRange(0, 10))],
            0,
            10,
        )
        self.assertEqual(people, (A, B))


def _seed_turns(store, asset: str, window: TimeRange, participant: ParticipantId = A, prefix: str = "w") -> str:
    words = [Word(f"{prefix}{index}", index * 1_000_000, index * 1_000_000 + 400_000, "hi") for index in range(6)]
    transcript = store.save_transcript(
        asset_id=asset, words=words, algorithm_id="amix.transcript.import",
        algorithm_version="1", fingerprint="t", window=window,
    )
    store.set_active(asset, "transcript", transcript)
    assignment = store.save_assignments(
        asset_id=asset,
        assignments=[SpeakerAssignment(word.word_id, participant) for word in words],
        depends_on=[transcript],
        algorithm_id="amix.assign.v1",
        algorithm_version="1",
        fingerprint="as",
        window=window,
    )
    store.set_active(asset, "participant_assignment", assignment)
    turn_id = store.save_turns(
        asset_id=asset,
        turns=[Turn("T0001", participant, window.start_us, window.end_us, tuple(word.word_id for word in words))],
        depends_on=[assignment],
        algorithm_id="amix.turns.v1",
        algorithm_version="1",
        fingerprint="tu",
        window=window,
    )
    store.set_active(asset, "turns", turn_id)
    return turn_id


def _publish_overlap(store, asset: str, window: TimeRange, regions: list[OverlapRegion]) -> str:
    return store.publish_overlap(
        asset_id=asset,
        regions=regions,
        algorithm_id=PROFILE_ID,
        algorithm_version="1",
        fingerprint="ov",
        window=window,
        config={
            "profile_id": PROFILE_ID,
            "layout_fingerprint": layout_fingerprint(store.list_layout_records(asset)),
        },
    )


class MulticamPlanTests(unittest.TestCase):
    def _base(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "Take"
        store = create_project(root, "Take")
        source = root / "master.mov"
        source.write_bytes(b"master")
        asset = store.add_media_asset(display_name="master.mov", location_kind="external", external_path=str(source))
        store.add_participant("a", "Alice")
        store.add_participant("b", "Bea")
        span = TimeRange(0, 60_000_000)
        store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 80, 80, span))
        store.add_layout_binding(asset, LayoutBinding(B, 100, 0, 80, 80, span))
        return tmp, store, asset

    def test_plan_reuses_the_planner_and_records_dependencies(self) -> None:
        tmp, store, asset = self._base()
        try:
            window = TimeRange(0, 6_000_000)
            _seed_turns(store, asset, window)
            _publish_overlap(store, asset, window, [OverlapRegion(2_000_000, 5_000_000, (A, B), 0.8)])
            store.add_protected_region(asset, ProtectedRegion(TimeRange(3_000_000, 4_000_000)))
            ready = multicam_readiness(store, asset)
            self.assertTrue(ready["plan_ready"])
            self.assertEqual(ready["blocking_reason"], None)
            run_id = build_automatic_plan(store, asset)
            plan = store.load_shot_plan(run_id)
            direct = plan_shots(
                window,
                store.load_turns(ready["turn_run_id"]),
                [Word(word.word_id, word.start_us, word.end_us, word.machine_text) for word in store.load_words(ready["transcript_run_id"])],
                store.load_overlaps(ready["overlap_run_id"]),
                store.load_layout_bindings(asset),
                store.load_protected_regions(asset),
            )
            self.assertEqual(plan.shots, direct.shots)
            self.assertTrue(any(shot.reason == "protected" and shot.presentation is Presentation.PROTECTED_MASTER for shot in plan.shots))
            self.assertTrue(any(shot.reason == "overlap" and shot.presentation is Presentation.UNTOUCHED_WIDE for shot in plan.shots))
            self.assertTrue(any(shot.presentation is Presentation.FULL and shot.participant_id == A for shot in plan.shots))
            record = store.analysis_record(run_id)
            self.assertEqual(set(store.run_dependencies(run_id)), {ready["turn_run_id"], ready["overlap_run_id"]})
            self.assertEqual(record["config"]["layout_fingerprint"], layout_fingerprint(store.list_layout_records(asset)))
            self.assertEqual(record["config"]["protected_fingerprint"], protected_fingerprint([(3_000_000, 4_000_000)]))
            self.assertFalse(record["config"]["reaction_shots"])
            second = build_automatic_plan(store, asset)
            self.assertEqual(store.get_active_run_id(asset, "shot_plan"), second)
            self.assertEqual(len(store.load_shot_plan(run_id).shots), len(plan.shots))
        finally:
            store.close()
            tmp.cleanup()

    def test_unbound_participant_is_wide_and_range_must_cover(self) -> None:
        tmp, store, asset = self._base()
        try:
            window = TimeRange(0, 6_000_000)
            store.add_participant("c", "Cara")
            _seed_turns(store, asset, window, C)
            _publish_overlap(store, asset, window, [])
            ready = multicam_readiness(store, asset)
            self.assertTrue(ready["plan_ready"])
            run_id = build_automatic_plan(store, asset)
            shots = store.load_shot_plan(run_id).shots
            self.assertTrue(all(shot.presentation is not Presentation.FULL for shot in shots))
            self.assertTrue(any(shot.reason == "unbound" for shot in shots))
            short = _seed_turns(store, asset, TimeRange(0, 1_000_000), C, prefix="q")
            blocked = multicam_readiness(store, asset)
            self.assertEqual(blocked["blocking_reason"], "analysis_not_covering")
            self.assertFalse(blocked["plan_ready"])
            self.assertEqual(blocked["turn_run_id"], short)
        finally:
            store.close()
            tmp.cleanup()

    def test_plan_stales_when_inputs_change(self) -> None:
        tmp, store, asset = self._base()
        try:
            window = TimeRange(0, 6_000_000)
            _seed_turns(store, asset, window)
            overlap_id = _publish_overlap(store, asset, window, [])
            build_automatic_plan(store, asset)
            _seed_turns(store, asset, window, prefix="v")
            self.assertTrue(multicam_readiness(store, asset)["plan_stale"])
            self.assertFalse(multicam_readiness(store, asset)["overlap_stale"])
            self.assertEqual(multicam_readiness(store, asset)["overlap_run_id"], overlap_id)
            _publish_overlap(store, asset, window, [])
            self.assertTrue(multicam_readiness(store, asset)["plan_stale"])
            build_automatic_plan(store, asset)
            store.add_participant("c", "Cara")
            store.add_layout_binding(asset, LayoutBinding(C, 0, 90, 80, 40, TimeRange(0, 60_000_000)))
            stale = multicam_readiness(store, asset)
            self.assertTrue(stale["plan_stale"])
            self.assertTrue(stale["overlap_stale"])
            self.assertEqual(stale["overlap_run_id"], store.get_active_run_id(asset, "overlap"))
        finally:
            store.close()
            tmp.cleanup()

    def test_protected_change_stales_the_plan_only(self) -> None:
        tmp, store, asset = self._base()
        try:
            window = TimeRange(0, 6_000_000)
            _seed_turns(store, asset, window)
            _publish_overlap(store, asset, window, [])
            build_automatic_plan(store, asset)
            store.add_protected_region(asset, ProtectedRegion(TimeRange(1_000_000, 2_000_000)))
            ready = multicam_readiness(store, asset)
            self.assertTrue(ready["plan_stale"])
            self.assertFalse(ready["overlap_stale"])
            self.assertTrue(ready["plan_ready"])
        finally:
            store.close()
            tmp.cleanup()


class PlanJobTests(unittest.TestCase):
    def test_job_activates_one_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase11"))
            try:
                session = runtime.create_project(root, "Take")
                source = root / "master.mov"
                source.write_bytes(b"master")
                asset = session.store.add_media_asset(display_name="master.mov", location_kind="external", external_path=str(source))
                session.store.add_participant("a", "Alice")
                session.store.add_participant("b", "Bea")
                span = TimeRange(0, 60_000_000)
                session.store.add_layout_binding(asset, LayoutBinding(A, 0, 0, 80, 80, span))
                session.store.add_layout_binding(asset, LayoutBinding(B, 100, 0, 80, 80, span))
                window = TimeRange(0, 6_000_000)
                _seed_turns(session.store, asset, window)
                _publish_overlap(session.store, asset, window, [])
                job = runtime.jobs.submit(session.store, BUILD_MULTICAM_PLAN, {}, asset)
                finished = _wait_job(session.store, job.job_id)
                self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                self.assertEqual(finished.progress_bp, 10000)
                self.assertEqual(session.store.get_active_run_id(asset, "shot_plan"), finished.result["shot_plan_run_id"])
            finally:
                runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
