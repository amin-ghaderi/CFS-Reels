"""Local transcription without a speech model and without the network.

The optional real-model test at the bottom runs only when AMIX_STT_MODEL_PATH
already points at a local CTranslate2 directory. It does not download weights.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import wave
from pathlib import Path
from unittest.mock import patch

from amix.amix_engine.adapters.stt.evidence import SttEvidence, SttWord, evidence_from_document
from amix.amix_engine.adapters.stt.faster_whisper import evidence_from_segments
from amix.amix_engine.adapters.stt.profile import PROFILE_ID, requested_language
from amix.amix_engine.adapters.stt.progress import transcription_progress_bp
from amix.amix_engine.adapters.stt.timing import canonical_source_us, external_seconds_to_us
from amix.amix_engine.jobs.transcribe import TRANSCRIBE, worker_command
from amix.amix_engine.playback import canonical_origin_us
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.stt.resolver import (
    SpeechResourceError,
    resolve_speech_model,
    speech_model_status,
)
from amix.amix_engine.storage.project import MediaProbeRecord, create_project, open_project
from amix.tests.test_service import _client, _headers


def _record(**overrides) -> MediaProbeRecord:
    values = dict(
        container="mov",
        duration_us=10_000_000,
        duration_source="video",
        container_start_us=5_000_000,
        bit_rate=1000,
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
        video_duration_us=10_000_000,
        rotation_degrees=0,
        audio_codec="aac",
        sample_rate=48000,
        audio_channels=2,
        channel_layout="stereo",
        audio_start_us=0,
        audio_duration_us=10_000_000,
        byte_size=12,
        file_mtime_ns=1,
        probe_tool="ffprobe test",
        probe_config="test",
    )
    values.update(overrides)
    return MediaProbeRecord(**values)


def _evidence(words: list[dict] | None = None, **overrides) -> str:
    document = {
        "language": "fa",
        "language_probability": 0.42,
        "faster_whisper_version": "test-fw",
        "ctranslate2_version": "test-ct2",
        "words": words if words is not None else [
            {"text": "alpha", "start_us": 0, "end_us": 500_000, "confidence": None, "segment": 0},
            {"text": "beta", "start_us": 1_250_000, "end_us": 1_400_000, "confidence": 0.75, "segment": 1},
        ],
    }
    document.update(overrides)
    return json.dumps(document)


def _env(model: Path, evidence: Path | None, mode: str) -> dict[str, str]:
    values = {
        "AMIX_STT_MODEL_PATH": str(model),
        "AMIX_STT_MODEL_ID": "dev-model",
        "AMIX_STT_MODEL_VERSION": "v-test",
        "AMIX_STT_DEVICE": "cpu",
        "AMIX_STT_COMPUTE_TYPE": "int8",
        "AMIX_STT_TEST_WORKER": mode,
    }
    if evidence is not None:
        values["AMIX_STT_TEST_EVIDENCE"] = str(evidence)
    return values


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


def _wait_job(store, job_id: str, timeout: float = 5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = store.get_processing_job(job_id)
        if last.status in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            return last
        time.sleep(0.02)
    raise AssertionError(last)


def _wait_pid(path: Path, timeout: float = 5) -> int:
    from amix.amix_engine.adapters.media.publish import read_pid

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            pid = read_pid(path)
            if pid is None:
                raise AssertionError(f"incomplete pid marker: {path.read_text(encoding='utf-8')!r}")
            return pid
        time.sleep(0.02)
    raise AssertionError("transcription worker did not start")


class Token:
    word: str
    start: float
    end: float

    def __init__(self, word: str, start: float, end: float, probability: float | None = None, include_probability: bool = True) -> None:
        self.word = word
        self.start = start
        self.end = end
        if include_probability:
            self.probability = probability


class Segment:
    def __init__(self, words: list[Token]) -> None:
        self.words = words


class Info:
    def __init__(self, language: str | None, probability: float | None) -> None:
        self.language = language
        self.language_probability = probability


class TimeTests(unittest.TestCase):
    def test_relative_seconds_become_canonical_source_microseconds(self) -> None:
        relative = external_seconds_to_us("1.250")
        self.assertEqual(relative, 1_250_000)
        self.assertIsInstance(relative, int)
        self.assertNotEqual(relative, 1)
        self.assertNotEqual(relative, 1_250)
        self.assertEqual(canonical_source_us(relative, 0), 1_250_000)
        self.assertEqual(canonical_source_us(relative, None), 1_250_000)
        self.assertEqual(canonical_source_us(1_250_000, 5_000_000), 6_250_000)
        self.assertNotEqual(canonical_source_us(1_250_000, 5_000_000), 5_000_000 - 1_250_000)
        playback = canonical_origin_us(5_000_000, 1_000_000)
        self.assertEqual(playback, 4_000_000)
        self.assertNotEqual(canonical_source_us(1_250_000, 5_000_000), playback + 1_250_000)

    def test_progress_is_monotonic_and_stops_before_activation(self) -> None:
        self.assertEqual(transcription_progress_bp(0, 10_000_000, 0), 0)
        first = transcription_progress_bp(5_000_000, 10_000_000, 0)
        self.assertEqual(first, 4999)
        self.assertEqual(transcription_progress_bp(1_000_000, 10_000_000, first), first)
        self.assertEqual(transcription_progress_bp(10_000_000, 10_000_000, first), 9999)
        self.assertEqual(transcription_progress_bp(4_000_000, None, 0), 0)
        self.assertLessEqual(transcription_progress_bp(99_000_000, 1_000, 0), 9999)


class AdapterTests(unittest.TestCase):
    def test_segments_keep_order_confidence_and_language(self) -> None:
        evidence = evidence_from_segments(
            [
                Segment([
                    Token("  hello", 0.0, 0.5, 0.9),
                    Token("there ", 0.5, 0.8, include_probability=False),
                ]),
                Segment([Token("friend", 1.25, 1.5, 0.2)]),
            ],
            Info("fa", 0.42),
        )
        self.assertEqual([word.text for word in evidence.words], ["hello", "there", "friend"])
        self.assertEqual([word.segment for word in evidence.words], [0, 0, 1])
        self.assertEqual(evidence.words[0].start_us, 0)
        self.assertEqual(evidence.words[0].confidence, 0.9)
        self.assertIsNone(evidence.words[1].confidence)
        self.assertEqual(evidence.words[2].start_us, 1_250_000)
        self.assertEqual(canonical_source_us(evidence.words[2].start_us, 5_000_000), 6_250_000)
        self.assertEqual(evidence.language, "fa")
        self.assertEqual(evidence.language_probability, 0.42)

    def test_blank_tokens_are_dropped_and_an_empty_result_is_valid(self) -> None:
        skipped = evidence_from_segments([Segment([Token("   ", 0.0, 0.2, 0.5)])], Info(None, None))
        self.assertEqual(skipped.words, ())
        empty = evidence_from_segments([], Info("en", None))
        self.assertEqual(empty.words, ())
        self.assertEqual(empty.language, "en")
        self.assertIsNone(empty.language_probability)

    def test_inference_import_is_confined_to_the_adapter(self) -> None:
        root = Path(__file__).resolve().parents[1] / "amix_engine"
        offenders = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "WhisperModel" in text or "from faster_whisper" in text:
                offenders.append(path)
        self.assertEqual([path.name for path in offenders], ["faster_whisper.py"])
        adapter = (root / "adapters" / "stt" / "faster_whisper.py").read_text(encoding="utf-8")
        self.assertIn("local_files_only=True", adapter)
        self.assertIn("HF_HUB_OFFLINE", adapter)
        resolver = (root / "stt" / "resolver.py").read_text(encoding="utf-8")
        self.assertNotIn("http", resolver)
        self.assertNotIn("WhisperModel", resolver)


class ResolverTests(unittest.TestCase):
    def test_missing_model_does_not_use_the_network_or_a_model_name(self) -> None:
        def blocked(*_args, **_kwargs):
            raise AssertionError("network")

        with patch("socket.create_connection", blocked), patch("socket.socket.connect", blocked), patch(
            "urllib.request.urlopen", blocked
        ), patch("pathlib.Path.home", side_effect=AssertionError("legacy cache")), patch(
            "amix.amix_engine.adapters.stt.faster_whisper.transcribe_file",
            side_effect=AssertionError("model load"),
        ):
            status = speech_model_status({"AMIX_STT_MODEL_PATH": ""})
            self.assertEqual(status.state, "MODEL_MISSING")
            self.assertIsNone(status.display_name)
            with self.assertRaises(SpeechResourceError) as missing:
                resolve_speech_model({"AMIX_STT_MODEL_PATH": ""})
            self.assertEqual(missing.exception.code, "speech_model_missing")
            named = speech_model_status({"AMIX_STT_MODEL_PATH": "small"})
            self.assertEqual(named.state, "INVALID_MODEL")
            with self.assertRaises(SpeechResourceError) as invalid:
                resolve_speech_model({"AMIX_STT_MODEL_PATH": "small"})
            self.assertEqual(invalid.exception.code, "invalid_speech_model")

    def test_explicit_device_does_not_fall_through_and_defaults_stay_cpu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model"
            model.mkdir()
            (model / "model.bin").write_bytes(b"weights")
            ready = resolve_speech_model({"AMIX_STT_MODEL_PATH": str(model)})
            self.assertEqual(ready.device, "cpu")
            self.assertEqual(ready.compute_type, "int8")
            status = speech_model_status({"AMIX_STT_MODEL_PATH": str(model)})
            self.assertEqual(status.state, "READY")
            self.assertNotIn(str(model), status.message)
            self.assertIsNone(getattr(status, "local_path", None))
            broken = speech_model_status({"AMIX_STT_MODEL_PATH": str(model), "AMIX_STT_DEVICE": "auto"})
            self.assertEqual(broken.state, "INVALID_MODEL")

    def test_runtime_unavailable_is_distinct(self) -> None:
        with patch("amix.amix_engine.stt.resolver.importlib.util.find_spec", return_value=None):
            status = speech_model_status({"AMIX_STT_MODEL_PATH": ""})
        self.assertEqual(status.state, "RUNTIME_UNAVAILABLE")
        self.assertIsNone(status.runtime)


class LanguageTests(unittest.TestCase):
    def test_auto_and_codes(self) -> None:
        self.assertIsNone(requested_language(None))
        self.assertEqual(requested_language("FA"), "fa")
        with self.assertRaises(Exception):
            requested_language("")
        with self.assertRaises(Exception):
            requested_language("persian")
        with self.assertRaises(Exception):
            requested_language("zz")


class TranscriptionJobTests(unittest.TestCase):
    def test_success_persists_integer_times_and_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase9"))
            try:
                session = runtime.create_project(root, "Take")
                source = root / "source-master.mov"
                source.write_bytes(b"source-bytes")
                asset_id = session.store.add_media_asset(
                    display_name="source-master.mov",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=source.stat().st_size,
                    file_mtime_ns=source.stat().st_mtime_ns,
                )
                session.store.apply_probe(asset_id, _record(byte_size=source.stat().st_size, file_mtime_ns=source.stat().st_mtime_ns))
                proxy_file = root / "proxy" / "preview.mp4"
                proxy_file.parent.mkdir(exist_ok=True)
                proxy_file.write_bytes(b"proxy-audio")
                session.store.publish_proxy(
                    asset_id,
                    _record(container_start_us=1_000_000, byte_size=11, file_mtime_ns=1),
                    relative_path="proxy/preview.mp4",
                    display_name="preview.mp4",
                    profile="amix.proxy.v1",
                    proxy_tool="test",
                    job_id="proxy-job",
                    source_size=source.stat().st_size,
                    source_mtime_ns=source.stat().st_mtime_ns,
                    timestamp_policy="container_normalized_v1",
                )
                model = root / "speech-model"
                model.mkdir()
                (model / "model.bin").write_bytes(b"local-model")
                evidence = root / "evidence.json"
                evidence.write_text(_evidence(), encoding="utf-8")
                with patch.dict(os.environ, _env(model, evidence, "emit"), clear=False):
                    job = runtime.jobs.submit(session.store, TRANSCRIBE, {"profile": PROFILE_ID}, asset_id)
                    finished = _wait_job(session.store, job.job_id)
                self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                self.assertEqual(finished.progress_bp, 10000)
                run_id = finished.result["transcript_run_id"]
                self.assertEqual(session.store.get_active_run_id(asset_id, "transcript"), run_id)
                words = session.store.load_words(run_id)
                self.assertEqual([word.machine_text for word in words], ["alpha", "beta"])
                self.assertEqual([word.start_us for word in words], [5_000_000, 6_250_000])
                self.assertEqual(words[1].end_us, 6_400_000)
                self.assertTrue(all(isinstance(word.start_us, int) and isinstance(word.end_us, int) for word in words))
                self.assertEqual(words[0].segment_ref, "0")
                self.assertIsNone(words[0].confidence)
                self.assertEqual(words[1].confidence, 0.75)
                self.assertEqual(words[1].segment_ref, "1")
                for word in words:
                    uuid.UUID(word.word_id)
                    self.assertNotIn(word.machine_text, word.word_id)
                record = session.store.analysis_record(run_id)
                self.assertEqual(record["algorithm_id"], PROFILE_ID)
                self.assertEqual(record["status"], "succeeded")
                self.assertEqual(record["window_start_us"], 5_000_000)
                self.assertEqual(record["window_end_us"], 15_000_000)
                self.assertEqual(record["config"]["canonical_origin_rule"], "source_container_start_us")
                self.assertEqual(record["config"]["source_container_start_us"], 5_000_000)
                self.assertNotEqual(record["config"]["source_container_start_us"], canonical_origin_us(5_000_000, 1_000_000))
                self.assertEqual(record["config"]["model_id"], "dev-model")
                self.assertEqual(record["config"]["model_runtime"], "faster-whisper")
                self.assertEqual(record["config"]["device"], "cpu")
                self.assertEqual(record["config"]["compute_type"], "int8")
                self.assertIsNone(record["config"]["requested_language"])
                self.assertEqual(record["config"]["detected_language"], "fa")
                self.assertEqual(record["config"]["detected_language_probability"], 0.42)
                self.assertEqual(record["config"]["analysis_window"], "full_source")
                self.assertEqual(record["config"]["faster_whisper_version"], "test-fw")
                self.assertEqual(record["config"]["ctranslate2_version"], "test-ct2")
                encoded = json.dumps(record["config"])
                self.assertNotIn(str(model), encoded)
                self.assertNotIn("source-master.mov", encoded)
                self.assertEqual(session.store.active_transcript(asset_id).language, "fa")
                self.assertFalse((root / ".stt" / job.job_id).exists())
            finally:
                runtime.shutdown()
            reopened = open_project(root)
            try:
                self.assertEqual(reopened.get_active_run_id(asset_id, "transcript"), run_id)
                reloaded = reopened.load_words(run_id)
                self.assertEqual([word.start_us for word in reloaded], [5_000_000, 6_250_000])
                self.assertEqual([word.end_us for word in reloaded], [5_500_000, 6_400_000])
            finally:
                reopened.close()

    def test_retranscription_keeps_the_old_correction_on_old_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase9"))
            try:
                session, asset_id, model = _prepared(runtime, root)
                first = root / "a.json"
                first.write_text(_evidence([
                    {"text": "one", "start_us": 0, "end_us": 100_000, "confidence": 0.5, "segment": 0},
                ], language="en", language_probability=0.8), encoding="utf-8")
                with patch.dict(os.environ, _env(model, first, "emit"), clear=False):
                    job_a = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    done_a = _wait_job(session.store, job_a.job_id)
                self.assertEqual(done_a.status, "SUCCEEDED", done_a.error_message)
                run_a = done_a.result["transcript_run_id"]
                word_a = session.store.load_words(run_a)[0]
                session.store.correct_word_text(word_a.word_id, "ONE", scope_id=run_a)
                second = root / "b.json"
                second.write_text(_evidence([
                    {"text": "two", "start_us": 200_000, "end_us": 300_000, "confidence": 0.4, "segment": 0},
                ], language="en", language_probability=0.7), encoding="utf-8")
                with patch.dict(os.environ, _env(model, second, "emit"), clear=False):
                    job_b = runtime.jobs.submit(session.store, TRANSCRIBE, {"language": "en"}, asset_id)
                    done_b = _wait_job(session.store, job_b.job_id)
                self.assertEqual(done_b.status, "SUCCEEDED", done_b.error_message)
                run_b = done_b.result["transcript_run_id"]
                self.assertEqual(session.store.get_active_run_id(asset_id, "transcript"), run_b)
                self.assertNotEqual(run_a, run_b)
                self.assertEqual(session.store.list_run_ids(asset_id, "transcript"), [run_a, run_b])
                kept = session.store.load_words(run_a)[0]
                self.assertEqual(kept.machine_text, "one")
                self.assertEqual(kept.effective_text, "ONE")
                self.assertEqual(kept.word_id, word_a.word_id)
                created = session.store.load_words(run_b)[0]
                self.assertEqual(created.machine_text, "two")
                self.assertEqual(created.effective_text, "two")
                self.assertNotEqual(created.word_id, word_a.word_id)
                self.assertEqual(session.store.analysis_record(run_b)["config"]["requested_language"], "en")
            finally:
                runtime.shutdown()

    def test_failed_retranscription_leaves_the_active_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase9"))
            try:
                session, asset_id, model = _prepared(runtime, root)
                evidence = root / "a.json"
                evidence.write_text(_evidence(), encoding="utf-8")
                with patch.dict(os.environ, _env(model, evidence, "emit"), clear=False):
                    job_a = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    done_a = _wait_job(session.store, job_a.job_id)
                run_a = done_a.result["transcript_run_id"]
                with patch.dict(os.environ, _env(model, evidence, "fail"), clear=False):
                    job_b = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    done_b = _wait_job(session.store, job_b.job_id)
                self.assertEqual(done_b.status, "FAILED")
                self.assertEqual(done_b.error_code, "speech_transcription_failed")
                self.assertEqual(session.store.get_active_run_id(asset_id, "transcript"), run_a)
                self.assertEqual(session.store.list_run_ids(asset_id, "transcript"), [run_a])
                self.assertEqual(len(session.store.load_words(run_a)), 2)
            finally:
                runtime.shutdown()

    def test_cancel_stops_the_worker_and_does_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase9"))
            try:
                session, asset_id, model = _prepared(runtime, root)
                evidence = root / "a.json"
                evidence.write_text(_evidence(), encoding="utf-8")
                with patch.dict(os.environ, _env(model, evidence, "emit"), clear=False):
                    job_a = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    done_a = _wait_job(session.store, job_a.job_id)
                run_a = done_a.result["transcript_run_id"]
                before = session.store.load_words(run_a)
                with patch.dict(os.environ, _env(model, None, "wait"), clear=False):
                    job_b = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    pid = _wait_pid(root / ".stt" / job_b.job_id / "worker.pid")
                    self.assertTrue(_alive(pid))
                    runtime.jobs.cancel(session.store, job_b.job_id)
                    self.assertTrue(runtime.jobs.wait_until_idle(session.store, 5))
                finished = session.store.get_processing_job(job_b.job_id)
                self.assertEqual(finished.status, "CANCELLED")
                self.assertFalse(_alive(pid))
                self.assertFalse((root / ".stt" / job_b.job_id).exists())
                self.assertEqual(session.store.get_active_run_id(asset_id, "transcript"), run_a)
                self.assertEqual(session.store.list_run_ids(asset_id, "transcript"), [run_a])
                self.assertEqual(session.store.load_words(run_a), before)
            finally:
                runtime.shutdown()

    def test_engine_shutdown_stops_the_worker_and_releases_the_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase9"))
            session = runtime.create_project(root, "Take")
            source = root / "source-master.mov"
            source.write_bytes(b"source-bytes")
            asset_id = session.store.add_media_asset(
                display_name="source-master.mov",
                location_kind="external",
                external_path=str(source),
                byte_size=4,
            )
            session.store.apply_probe(asset_id, _record(byte_size=4))
            model = root / "speech-model"
            model.mkdir()
            (model / "model.bin").write_bytes(b"local-model")
            try:
                with patch.dict(os.environ, _env(model, None, "wait"), clear=False):
                    job = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    pid = _wait_pid(root / ".stt" / job.job_id / "worker.pid")
                    self.assertTrue(_alive(pid))
                    runtime.shutdown()
                    self.assertFalse(_alive(pid))
            finally:
                runtime.shutdown()
            reopened = open_project(root)
            try:
                self.assertIsNone(reopened.get_active_run_id(asset_id, "transcript"))
                stored = reopened.get_processing_job(job.job_id)
                self.assertIn(stored.status, {"CANCELLED", "INTERRUPTED"})
            finally:
                reopened.close()

    def test_interrupted_work_is_not_resumed_and_retry_is_a_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            store = create_project(root, "Take")
            try:
                source = root / "source-master.mov"
                source.write_bytes(b"source-bytes")
                asset_id = store.add_media_asset(
                    display_name="source-master.mov",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=4,
                )
                job = store.create_processing_job(kind=TRANSCRIBE, spec={"profile": PROFILE_ID}, media_asset_id=asset_id)
                self.assertTrue(store.start_processing_job(job.job_id))
                partial = root / ".stt" / "orphan"
                partial.mkdir(parents=True)
                partial.joinpath("result.json").write_text(_evidence(), encoding="utf-8")
            finally:
                store.close()
            reopened = open_project(root)
            try:
                interrupted = reopened.get_processing_job(job.job_id)
                self.assertEqual(interrupted.status, "INTERRUPTED")
                self.assertIsNone(reopened.get_active_run_id(asset_id, "transcript"))
                retried = reopened.retry_processing_job(job.job_id)
                self.assertNotEqual(retried.job_id, job.job_id)
                self.assertEqual(retried.attempt, 2)
                self.assertEqual(retried.spec, {"profile": PROFILE_ID})
                self.assertEqual(retried.status, "QUEUED")
                self.assertIsNone(reopened.get_active_run_id(asset_id, "transcript"))
                self.assertTrue(partial.joinpath("result.json").is_file())
            finally:
                reopened.close()

    def test_rejected_spec_missing_source_and_silent_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase9"))
            try:
                session, asset_id, model = _prepared(runtime, root)
                evidence = root / "a.json"
                evidence.write_text(_evidence(), encoding="utf-8")
                with patch.dict(os.environ, _env(model, evidence, "emit"), clear=False):
                    rejected = runtime.jobs.submit(
                        session.store,
                        TRANSCRIBE,
                        {"profile": PROFILE_ID, "model_path": str(model), "command": "python"},
                        asset_id,
                    )
                    done = _wait_job(session.store, rejected.job_id)
                    self.assertEqual(done.status, "FAILED")
                    self.assertEqual(done.error_code, "job_spec_rejected")
                    self.assertIsNone(session.store.get_active_run_id(asset_id, "transcript"))
                    language = runtime.jobs.submit(session.store, TRANSCRIBE, {"language": "persian"}, asset_id)
                    bad_language = _wait_job(session.store, language.job_id)
                    self.assertEqual(bad_language.error_code, "invalid_language")
                    silent_id = session.store.add_media_asset(
                        display_name="silent.mov",
                        location_kind="external",
                        external_path=str(root / "source-master.mov"),
                        byte_size=4,
                    )
                    session.store.apply_probe(silent_id, _record(
                        audio_codec=None,
                        sample_rate=None,
                        audio_channels=None,
                        channel_layout=None,
                        audio_start_us=None,
                        audio_duration_us=None,
                    ))
                    silent = runtime.jobs.submit(session.store, TRANSCRIBE, {}, silent_id)
                    silent_done = _wait_job(session.store, silent.job_id)
                    self.assertEqual(silent_done.error_code, "media_has_no_audio")
                    session.store.get_media(asset_id)
                    source = Path(session.store.get_media(asset_id).external_path)
                    with patch.dict(os.environ, _env(model, evidence, "emit"), clear=False):
                        made = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                        made_done = _wait_job(session.store, made.job_id)
                    self.assertEqual(made_done.status, "SUCCEEDED", made_done.error_message)
                    run_id = made_done.result["transcript_run_id"]
                    source.unlink()
                    proxy = root / "proxy" / "preview.mp4"
                    self.assertTrue(proxy.is_file())
                    missing = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    missing_done = _wait_job(session.store, missing.job_id)
                    self.assertEqual(missing_done.error_code, "media_missing")
                    self.assertEqual(session.store.get_active_run_id(asset_id, "transcript"), run_id)
                    self.assertEqual(len(session.store.load_words(run_id)), 2)
                    command = worker_command(root / "worker.json")
                    self.assertEqual(command[0], sys.executable)
                    self.assertEqual(command[1:4], ["-m", "amix.amix_engine.workers.transcribe", "--spec"])
            finally:
                runtime.shutdown()

    def test_unprobed_source_is_not_treated_as_silent_and_empty_transcript_activates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase9"))
            try:
                session = runtime.create_project(root, "Take")
                source = root / "source-master.mov"
                source.write_bytes(b"source-bytes")
                asset_id = session.store.add_media_asset(
                    display_name="source-master.mov",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=4,
                )
                model = root / "speech-model"
                model.mkdir()
                (model / "model.bin").write_bytes(b"local-model")
                evidence = root / "empty.json"
                evidence.write_text(_evidence([], language=None, language_probability=None), encoding="utf-8")
                with patch.dict(os.environ, _env(model, evidence, "emit"), clear=False):
                    job = runtime.jobs.submit(session.store, TRANSCRIBE, {}, asset_id)
                    done = _wait_job(session.store, job.job_id)
                self.assertEqual(done.status, "SUCCEEDED", done.error_message)
                self.assertEqual(done.progress_bp, 10000)
                run_id = done.result["transcript_run_id"]
                self.assertEqual(session.store.active_transcript(asset_id).word_count, 0)
                self.assertEqual(session.store.load_words(run_id), [])
                self.assertEqual(session.store.analysis_record(run_id)["window_start_us"], 0)
            finally:
                runtime.shutdown()

    def test_speech_model_status_is_authenticated_and_hides_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "hidden-model"
            model.mkdir()
            (model / "model.bin").write_bytes(b"local-model")
            runtime, client = _client(tmp)
            try:
                denied = client.get("/v1/runtime/speech-model")
                self.assertEqual(denied.status_code, 401)
                with patch.dict(os.environ, _env(model, None, "emit"), clear=False):
                    response = client.get("/v1/runtime/speech-model", headers=_headers())
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["state"], "READY")
                self.assertEqual(body["display_name"], "dev-model")
                self.assertNotIn("local_path", body)
                self.assertNotIn("path", body)
                self.assertNotIn(str(model), response.text)
            finally:
                runtime.shutdown()


def _prepared(runtime: EngineRuntime, root: Path):
    session = runtime.create_project(root, "Take")
    source = root / "source-master.mov"
    source.write_bytes(b"source-bytes")
    asset_id = session.store.add_media_asset(
        display_name="source-master.mov",
        location_kind="external",
        external_path=str(source),
        byte_size=source.stat().st_size,
        file_mtime_ns=source.stat().st_mtime_ns,
    )
    session.store.apply_probe(asset_id, _record(
        byte_size=source.stat().st_size,
        file_mtime_ns=source.stat().st_mtime_ns,
    ))
    proxy_file = root / "proxy" / "preview.mp4"
    proxy_file.parent.mkdir(exist_ok=True)
    proxy_file.write_bytes(b"proxy-audio")
    session.store.publish_proxy(
        asset_id,
        _record(container_start_us=1_000_000, byte_size=11, file_mtime_ns=1),
        relative_path="proxy/preview.mp4",
        display_name="preview.mp4",
        profile="amix.proxy.v1",
        proxy_tool="test",
        job_id="proxy-job",
        source_size=source.stat().st_size,
        source_mtime_ns=source.stat().st_mtime_ns,
        timestamp_policy="container_normalized_v1",
    )
    model = root / "speech-model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"local-model")
    return session, asset_id, model


def _real_model_configured() -> bool:
    path = os.environ.get("AMIX_STT_MODEL_PATH", "").strip()
    return bool(path) and (Path(path) / "model.bin").is_file()


@unittest.skipUnless(_real_model_configured(), "AMIX_STT_MODEL_PATH is not a local model directory")
class RealModelTests(unittest.TestCase):
    def test_local_model_transcribes_silence_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=180, session_token="phase9"))
            try:
                session = runtime.create_project(root, "Take")
                source = root / "silence.wav"
                with wave.open(str(source), "w") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(16000)
                    handle.writeframes(b"\x00\x00" * 16000)
                asset_id = session.store.add_media_asset(
                    display_name="silence.wav",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=source.stat().st_size,
                )
                with patch.dict(os.environ, {"AMIX_STT_TEST_WORKER": "", "AMIX_STT_TEST_EVIDENCE": ""}, clear=False):
                    job = runtime.jobs.submit(session.store, TRANSCRIBE, {"profile": PROFILE_ID}, asset_id)
                    done = _wait_job(session.store, job.job_id, timeout=180)
                self.assertEqual(done.status, "SUCCEEDED", done.error_message)
                self.assertEqual(done.progress_bp, 10000)
                run_id = done.result["transcript_run_id"]
                record = session.store.analysis_record(run_id)
                self.assertEqual(record["config"]["profile_id"], PROFILE_ID)
                self.assertNotEqual(record["config"]["faster_whisper_version"], "unknown")
                evidence_from_document({"words": [], "faster_whisper_version": record["config"]["faster_whisper_version"], "ctranslate2_version": record["config"]["ctranslate2_version"]})
                self.assertIsNotNone(session.store.get_active_run_id(asset_id, "transcript"))
            finally:
                runtime.shutdown()


class EvidenceRoundTripTests(unittest.TestCase):
    def test_document_times_stay_integers(self) -> None:
        evidence = evidence_from_document(json.loads(_evidence()))
        self.assertIsInstance(evidence, SttEvidence)
        self.assertIsInstance(evidence.words[1], SttWord)
        self.assertEqual(evidence.words[1].start_us, 1_250_000)
        self.assertIsInstance(evidence.words[1].start_us, int)
