"""Participants, layout, and classical diarization. No FFmpeg, media, or network."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np

from amix.amix_engine.adapters.diarize.mfcc_kmeans import (
    FRAME,
    HOP,
    N_MELS,
    N_MFCC,
    N_SPEAKERS,
    SR,
    cluster_speech,
    diarize_pcm,
    frame_features,
    mel_bank,
    segments_from_labels,
    speech_mask,
    window_matrix,
    zscore,
    DiarizationFailed,
)
from amix.amix_engine.adapters.diarize.profile import PROFILE_ID, V1, profile_from_spec
from amix.amix_engine.analysis.assign import assign_words
from amix.amix_engine.analysis.turns import build_turns
from amix.amix_engine.domain.types import DiarizationSegment, ParticipantId, SpeakerAssignment, Word
from amix.amix_engine.jobs.diarize import DIARIZE_AUDIO, _load_result, worker_command
from amix.amix_engine.layout import validate_layout
from amix.amix_engine.playback import canonical_origin_us
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.speakers import apply_cluster_map, representative_ranges, summarize_clusters
from amix.amix_engine.storage.project import create_project, private_directory
from amix.amix_engine.time.clock import TimeRange, legacy_seconds_to_us
from amix.tests.test_service import _client, _create, _headers

FEATURES = Path(__file__).resolve().parent / "golden" / "cfs03_49_59" / "inputs" / "diarization_features.npz"
EXPECTED_SEGMENTS = Path(__file__).resolve().parent / "golden" / "cfs03_49_59" / "inputs" / "diarization_segments.json"


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
    raise AssertionError("diarization worker did not start")


def _evidence(origin: int = 5_000_000) -> dict:
    return {
        "profile_id": PROFILE_ID,
        "cluster_count": 3,
        "window_start_us": origin,
        "window_end_us": origin + 4_000_000,
        "segments": [
            {"cluster_key": "SPEAKER_00", "start_us": origin + 100_000, "end_us": origin + 1_500_000},
            {"cluster_key": "SPEAKER_01", "start_us": origin + 1_800_000, "end_us": origin + 3_000_000},
        ],
        "diagnostics": {
            "speech_windows": 12,
            "silence_windows": 1,
            "cluster_count": 3,
            "overlap_supported": False,
            "feature_config": {"cluster_count": 3},
            "decode": {"sample_rate": 16000, "channels": 1},
        },
    }


class FeatureTests(unittest.TestCase):
    def test_profile_is_fixed_at_three_clusters(self) -> None:
        self.assertEqual(V1.cluster_count, 3)
        self.assertEqual(N_SPEAKERS, 3)
        self.assertEqual(profile_from_spec(None).profile_id, PROFILE_ID)
        with self.assertRaises(Exception):
            profile_from_spec("amix.diarize.generic")

    def test_frame_hop_mel_and_window_shapes(self) -> None:
        audio = np.zeros(SR, dtype=np.float32)
        audio[::40] = 0.2
        cep, centroid, rms = frame_features(audio)
        expected = 1 + (audio.size - FRAME) // HOP
        self.assertEqual(cep.shape, (expected, N_MFCC - 1))
        self.assertEqual(centroid.shape, (expected,))
        self.assertEqual(rms.shape, (expected,))
        self.assertEqual(mel_bank(FRAME).shape, (N_MELS, FRAME // 2 + 1))
        features, times, energy = window_matrix(cep, centroid, rms)
        self.assertEqual(features.shape[1], (N_MFCC - 1) * 2 + 1)
        self.assertEqual(len(times), len(energy))
        self.assertGreater(len(times), 0)
        self.assertTrue(np.isfinite(centroid).all())
        self.assertTrue(np.isfinite(rms).all())

    def test_zscore_speech_gate_and_segment_clock(self) -> None:
        raw = np.array([[1.0, 5.0], [3.0, 5.0], [5.0, 5.0]], dtype=np.float64)
        scaled = zscore(raw)
        self.assertAlmostEqual(float(scaled[:, 1].std()), 0.0)
        self.assertAlmostEqual(float(scaled[:, 0].mean()), 0.0, places=6)
        energy = np.array([0.0, 1.0, 2.0, 3.0, 9.0])
        mask = speech_mask(energy)
        self.assertEqual(int(mask.sum()), int((energy >= np.percentile(energy, 18)).sum()))
        labels = np.array([0, 0, 1, 1, -1])
        times = np.array([1.0, 1.25, 2.0, 2.25, 3.0])
        segments = segments_from_labels(labels, times, 0.0)
        self.assertEqual([item["cluster_key"] for item in segments], ["SPEAKER_00", "SPEAKER_01"])
        origin = 2_960_000_000
        start_us = legacy_seconds_to_us(segments[0]["start"]) + origin
        self.assertEqual(start_us, origin + legacy_seconds_to_us(segments[0]["start"]))
        self.assertNotEqual(start_us, legacy_seconds_to_us(segments[0]["start"]))
        self.assertIsInstance(start_us, int)

    def test_clustering_separates_three_blobs_without_naming_people(self) -> None:
        rng = np.random.default_rng(0)
        blobs = [rng.normal(0.0, 0.01, size=(60, 6)) + offset for offset in (0.0, 8.0, 16.0)]
        labels = cluster_speech(np.vstack(blobs))
        self.assertEqual(set(int(value) for value in labels), {0, 1, 2})
        self.assertGreaterEqual(min(int((labels == key).sum()) for key in range(3)), 40)

    def test_short_audio_fails_closed(self) -> None:
        with self.assertRaises(DiarizationFailed):
            diarize_pcm(np.zeros(SR, dtype=np.float32), 0)

    def test_result_rejects_participant_identity(self) -> None:
        payload = _evidence()
        payload["segments"][0]["participant_id"] = "person"
        with self.assertRaises(ValueError):
            _load_result(json.dumps(payload), PROFILE_ID, 3)


class LayoutRuleTests(unittest.TestCase):
    def test_rejects_invalid_geometry_and_keeps_canonical_time(self) -> None:
        binding = validate_layout(
            participant_id="p1",
            start_us=5_000_000,
            end_us=8_000_000,
            x=10,
            y=20,
            w=30,
            h=40,
            picture_width=320,
            picture_height=240,
        )
        self.assertEqual(binding.span.start_us, 5_000_000)
        self.assertEqual(binding.w, 30)
        with self.assertRaises(Exception):
            validate_layout(
                participant_id="p1", start_us=1, end_us=1, x=0, y=0, w=10, h=10,
                picture_width=100, picture_height=80,
            )
        with self.assertRaises(Exception):
            validate_layout(
                participant_id="p1", start_us=0, end_us=10, x=100, y=0, w=10, h=10,
                picture_width=100, picture_height=80,
            )
        with self.assertRaises(Exception):
            validate_layout(
                participant_id="p1", start_us=0, end_us=10, x=-1, y=0, w=10, h=10,
                picture_width=None, picture_height=None,
            )
        with self.assertRaises(Exception):
            validate_layout(
                participant_id="p1", start_us=0, end_us=10, x=0, y=0, w=0, h=10,
                picture_width=None, picture_height=None,
            )


class RepresentativeTests(unittest.TestCase):
    def test_samples_are_few_and_deterministic(self) -> None:
        ranges = [(index * 1_000_000, index * 1_000_000 + 200_000) for index in range(9)]
        ranges[4] = (4_000_000, 4_900_000)
        first = representative_ranges(ranges)
        second = representative_ranges(list(reversed(ranges)))
        self.assertLessEqual(len(first), 3)
        self.assertEqual(first, second)
        self.assertIn((4_000_000, 4_900_000), first)
        segments = [
            DiarizationSegment(start, end, "SPEAKER_00")
            for start, end in ranges
        ]
        summary = summarize_clusters(segments)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["segment_count"], 9)
        self.assertLessEqual(len(summary[0]["samples"]), 3)
        self.assertNotIn("confidence", summary[0])


class ApiTests(unittest.TestCase):
    def test_participants_layout_and_speaker_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Room"
            runtime, client = _client(tmp)
            try:
                created = _create(client, root, "Room")
                handle = created["handle"]
                store = runtime.session(handle).store
                first = client.post(
                    f"/v1/projects/{handle}/participants",
                    headers=_headers(),
                    json={"display_name": "  Ava  "},
                )
                self.assertEqual(first.status_code, 200, first.text)
                ava = first.json()
                uuid.UUID(ava["participant_id"])
                self.assertNotEqual(ava["participant_id"], "Ava")
                self.assertEqual(ava["display_name"], "Ava")
                second = client.post(
                    f"/v1/projects/{handle}/participants",
                    headers=_headers(),
                    json={"display_name": "Ben"},
                )
                ben = second.json()["participant_id"]
                renamed = client.post(
                    f"/v1/projects/{handle}/participants/{ava['participant_id']}/rename",
                    headers=_headers(),
                    json={"display_name": "Ava More"},
                )
                self.assertEqual(renamed.status_code, 200, renamed.text)
                listed = client.get(f"/v1/projects/{handle}/participants", headers=_headers())
                self.assertEqual(
                    [(row["participant_id"], row["display_name"]) for row in listed.json()],
                    [(ava["participant_id"], "Ava More"), (ben, "Ben")],
                )
                self.assertNotIn("speaker_a", json.dumps(listed.json()))
                source = root / "master.mov"
                source.write_bytes(b"master-bytes")
                asset = store.add_media_asset(
                    display_name="master.mov",
                    location_kind="external",
                    external_path=str(source),
                    container_start_us=5_000_000,
                    duration_us=10_000_000,
                    width=320,
                    height=240,
                    byte_size=source.stat().st_size,
                )
                saved = client.post(
                    f"/v1/projects/{handle}/media/{asset}/layout",
                    headers=_headers(),
                    json={
                        "participant_id": ava["participant_id"],
                        "start_us": 5_000_000,
                        "end_us": 9_000_000,
                        "x": 12,
                        "y": 8,
                        "w": 40,
                        "h": 30,
                    },
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertEqual(saved.json()["start_us"], 5_000_000)
                self.assertEqual(saved.json()["coordinate_space"], "display_pixels")
                later = client.post(
                    f"/v1/projects/{handle}/media/{asset}/layout",
                    headers=_headers(),
                    json={
                        "participant_id": ben,
                        "start_us": 9_000_000,
                        "end_us": 15_000_000,
                        "x": 0,
                        "y": 0,
                        "w": 20,
                        "h": 20,
                    },
                )
                self.assertEqual(later.status_code, 200, later.text)
                loaded = client.get(f"/v1/projects/{handle}/media/{asset}/layout", headers=_headers())
                self.assertEqual(
                    [(row["participant_id"], row["start_us"], row["end_us"]) for row in loaded.json()],
                    [(ava["participant_id"], 5_000_000, 9_000_000), (ben, 9_000_000, 15_000_000)],
                )
                outside = client.post(
                    f"/v1/projects/{handle}/media/{asset}/layout",
                    headers=_headers(),
                    json={
                        "participant_id": ben,
                        "start_us": 5_000_000,
                        "end_us": 6_000_000,
                        "x": 400,
                        "y": 0,
                        "w": 10,
                        "h": 10,
                    },
                )
                self.assertEqual(outside.status_code, 400)
                self.assertEqual(outside.json()["error"]["code"], "invalid_layout")
                self.assertEqual(len(store.load_layout_bindings(asset)), 2)

                words = [
                    Word("w0", 5_100_000, 5_400_000, "one"),
                    Word("w1", 7_000_000, 7_400_000, "two"),
                ]
                transcript = store.save_transcript(
                    asset_id=asset,
                    words=words,
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="t1",
                    window=TimeRange(5_000_000, 15_000_000),
                )
                store.set_active(asset, "transcript", transcript)
                diarization = store.publish_diarization(
                    asset_id=asset,
                    segments=[
                        DiarizationSegment(5_000_000, 6_000_000, "SPEAKER_00"),
                        DiarizationSegment(6_500_000, 8_000_000, "SPEAKER_01"),
                    ],
                    algorithm_id=PROFILE_ID,
                    algorithm_version="1",
                    fingerprint="d1",
                    window=TimeRange(5_000_000, 15_000_000),
                    config={"profile_id": PROFILE_ID, "cluster_count": 3, "clock": "source_container_start"},
                )
                record = store.analysis_record(diarization)
                self.assertNotIn("cluster_map", record["config"])
                self.assertNotIn("participant_id", record["config"])
                self.assertEqual(store.get_active_run_id(asset, "participant_assignment"), None)
                status = client.get(f"/v1/projects/{handle}/media/{asset}/speaker-analysis", headers=_headers())
                self.assertEqual(status.status_code, 200, status.text)
                self.assertEqual(status.json()["state"], "clusters_ready")
                self.assertEqual(status.json()["cluster_count"], 3)
                self.assertIn("three anonymous clusters", status.json()["limitation"])
                self.assertEqual(status.json()["clusters"][0]["segment_count"], 1)
                self.assertLessEqual(len(status.json()["clusters"][0]["samples"]), 3)

                old_assignment = store.save_assignments(
                    asset_id=asset,
                    assignments=[SpeakerAssignment("w0", ParticipantId(ben))],
                    depends_on=[transcript],
                    algorithm_id="amix.assign",
                    algorithm_version="1",
                    fingerprint="old",
                    window=TimeRange(5_000_000, 15_000_000),
                )
                old_turns = store.save_turns(
                    asset_id=asset,
                    turns=[],
                    depends_on=[old_assignment],
                    algorithm_id="amix.turns",
                    algorithm_version="1",
                    fingerprint="old-turns",
                    window=TimeRange(5_000_000, 15_000_000),
                )
                store.set_active(asset, "participant_assignment", old_assignment)
                store.set_active(asset, "turns", old_turns)
                refused = client.post(
                    f"/v1/projects/{handle}/media/{asset}/speaker-map",
                    headers=_headers(),
                    json={
                        "diarization_run_id": diarization,
                        "mappings": [
                            {"cluster_key": "SPEAKER_00", "participant_id": "missing-person"},
                            {"cluster_key": "SPEAKER_01", "participant_id": None},
                        ],
                    },
                )
                self.assertEqual(refused.status_code, 404, refused.text)
                self.assertEqual(refused.json()["error"]["code"], "unknown_participant")
                self.assertEqual(store.get_active_run_id(asset, "participant_assignment"), old_assignment)
                self.assertEqual(store.get_active_run_id(asset, "turns"), old_turns)

                applied = client.post(
                    f"/v1/projects/{handle}/media/{asset}/speaker-map",
                    headers=_headers(),
                    json={
                        "diarization_run_id": diarization,
                        "mappings": [
                            {"cluster_key": "SPEAKER_00", "participant_id": ava["participant_id"]},
                            {"cluster_key": "SPEAKER_01", "participant_id": ava["participant_id"]},
                        ],
                    },
                )
                self.assertEqual(applied.status_code, 200, applied.text)
                assignment_id = applied.json()["assignment_run_id"]
                turn_id = applied.json()["turns_run_id"]
                self.assertEqual(store.get_active_run_id(asset, "participant_assignment"), assignment_id)
                self.assertEqual(store.get_active_run_id(asset, "turns"), turn_id)
                self.assertEqual(store.get_active_run_id(asset, "diarization"), diarization)
                self.assertIn(old_assignment, store.list_run_ids(asset, "participant_assignment"))
                self.assertIn(transcript, store.run_dependencies(assignment_id))
                self.assertIn(diarization, store.run_dependencies(assignment_id))
                self.assertEqual(store.run_dependencies(turn_id), [assignment_id])
                expected_words = words
                expected_segments = store.load_diarization_segments(diarization)
                expected_map = {
                    "SPEAKER_00": ParticipantId(ava["participant_id"]),
                    "SPEAKER_01": ParticipantId(ava["participant_id"]),
                }
                self.assertEqual(
                    store.load_assignments(assignment_id),
                    assign_words(expected_words, expected_segments, expected_map),
                )
                self.assertEqual(
                    store.load_turns(turn_id),
                    build_turns(expected_words, assign_words(expected_words, expected_segments, expected_map)),
                )
                page = client.get(
                    f"/v1/projects/{handle}/media/{asset}/transcript/words/0/10",
                    headers=_headers(),
                )
                self.assertEqual(page.json()["words"][0]["participant_name"], "Ava More")
                self.assertEqual(page.json()["words"][1]["participant_name"], "Ava More")

                unknown = client.post(
                    f"/v1/projects/{handle}/media/{asset}/speaker-map",
                    headers=_headers(),
                    json={
                        "diarization_run_id": diarization,
                        "mappings": [
                            {"cluster_key": "SPEAKER_00", "participant_id": ava["participant_id"]},
                            {"cluster_key": "SPEAKER_01", "participant_id": None},
                        ],
                    },
                )
                self.assertEqual(unknown.status_code, 200, unknown.text)
                unknown_assignment = unknown.json()["assignment_run_id"]
                page = client.get(
                    f"/v1/projects/{handle}/media/{asset}/transcript/words/0/10",
                    headers=_headers(),
                )
                self.assertEqual(page.json()["words"][0]["participant_name"], "Ava More")
                self.assertEqual(page.json()["words"][1]["participant_name"], "Unknown")
                self.assertIsNone(page.json()["words"][1]["participant_id"])

                second = store.save_transcript(
                    asset_id=asset,
                    words=[Word("n0", 5_100_000, 5_400_000, "one")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="t2",
                    window=TimeRange(5_000_000, 15_000_000),
                )
                store.set_active(asset, "transcript", second)
                stale = client.get(
                    f"/v1/projects/{handle}/media/{asset}/transcript/words/0/10",
                    headers=_headers(),
                )
                self.assertIsNone(stale.json()["words"][0]["participant_name"])
                self.assertIsNone(stale.json()["words"][0]["participant_id"])
                analysis = client.get(
                    f"/v1/projects/{handle}/media/{asset}/speaker-analysis",
                    headers=_headers(),
                )
                self.assertEqual(analysis.json()["state"], "stale")
                self.assertNotIn(second, store.run_dependencies(unknown_assignment))
                reapplied = client.post(
                    f"/v1/projects/{handle}/media/{asset}/speaker-map",
                    headers=_headers(),
                    json={
                        "diarization_run_id": diarization,
                        "mappings": [
                            {"cluster_key": "SPEAKER_00", "participant_id": ben},
                            {"cluster_key": "SPEAKER_01", "participant_id": None},
                        ],
                    },
                )
                self.assertEqual(reapplied.status_code, 200, reapplied.text)
                fresh = reapplied.json()["assignment_run_id"]
                self.assertIn(second, store.run_dependencies(fresh))
                self.assertIn(diarization, store.run_dependencies(fresh))
                self.assertIn(unknown_assignment, store.list_run_ids(asset, "participant_assignment"))
                named = client.get(
                    f"/v1/projects/{handle}/media/{asset}/transcript/words/0/10",
                    headers=_headers(),
                )
                self.assertEqual(named.json()["words"][0]["participant_name"], "Ben")
                self.assertEqual(
                    store.get_active_run_id(asset, "turns"),
                    reapplied.json()["turns_run_id"],
                )
            finally:
                client.close()
                runtime.shutdown()


class JobTests(unittest.TestCase):
    def test_worker_command_is_fixed(self) -> None:
        command = worker_command(Path("worker.json"))
        self.assertEqual(command[1:3], ["-m", "amix.amix_engine.workers.diarize"])
        self.assertNotIn("ffmpeg", command)

    def test_emit_persists_anonymous_segments_without_touching_speakers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase10"))
            try:
                session = runtime.create_project(root, "Take")
                source = root / "master.mov"
                source.write_bytes(b"master-bytes")
                proxy = root / "proxy.mov"
                proxy.write_bytes(b"proxy-bytes")
                asset = session.store.add_media_asset(
                    display_name="master.mov",
                    location_kind="external",
                    external_path=str(source),
                    container_start_us=5_000_000,
                    byte_size=source.stat().st_size,
                )
                session.store.add_media_asset(
                    display_name="proxy.mov",
                    role="proxy",
                    location_kind="external",
                    external_path=str(proxy),
                    container_start_us=1_000_000,
                )
                session.store.save_transcript(
                    asset_id=asset,
                    words=[Word("w0", 5_100_000, 5_200_000, "hi")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="t",
                    window=TimeRange(5_000_000, 9_000_000),
                )
                transcript = session.store.list_run_ids(asset, "transcript")[0]
                session.store.set_active(asset, "transcript", transcript)
                evidence = root / "evidence.json"
                evidence.write_text(json.dumps(_evidence()), encoding="utf-8")
                with patch.dict(os.environ, {"AMIX_DIARIZE_TEST_WORKER": "emit", "AMIX_DIARIZE_TEST_EVIDENCE": str(evidence)}):
                    job = runtime.jobs.submit(session.store, DIARIZE_AUDIO, {"profile": PROFILE_ID}, asset)
                    finished = _wait_job(session.store, job.job_id)
                self.assertEqual(finished.status, "SUCCEEDED", finished.error_message)
                self.assertEqual(finished.progress_bp, 10000)
                run_id = finished.result["diarization_run_id"]
                self.assertEqual(session.store.get_active_run_id(asset, "diarization"), run_id)
                self.assertIsNone(session.store.get_active_run_id(asset, "participant_assignment"))
                self.assertIsNone(session.store.get_active_run_id(asset, "turns"))
                segments = session.store.load_diarization_segments(run_id)
                self.assertEqual(segments[0].start_us, 5_100_000)
                self.assertNotEqual(segments[0].start_us, canonical_origin_us(5_000_000, 1_000_000))
                record = session.store.analysis_record(run_id)
                self.assertEqual(record["config"]["clock"], "source_container_start")
                self.assertEqual(record["config"]["cluster_count"], 3)
                self.assertNotIn("cluster_map", record["config"])
                self.assertFalse((private_directory(root) / ".diarize" / job.job_id).exists())
            finally:
                runtime.shutdown()

    def test_cancel_does_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase10"))
            try:
                session = runtime.create_project(root, "Take")
                source = root / "master.mov"
                source.write_bytes(b"master-bytes")
                asset = session.store.add_media_asset(
                    display_name="master.mov",
                    location_kind="external",
                    external_path=str(source),
                )
                transcript = session.store.save_transcript(
                    asset_id=asset,
                    words=[Word("w0", 0, 1000, "hi")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="t",
                    window=TimeRange(0, 1000),
                )
                session.store.set_active(asset, "transcript", transcript)
                with patch.dict(os.environ, {"AMIX_DIARIZE_TEST_WORKER": "wait"}):
                    job = runtime.jobs.submit(session.store, DIARIZE_AUDIO, {}, asset)
                    pid = _wait_pid(private_directory(root) / ".diarize" / job.job_id / "worker.pid")
                    self.assertTrue(_alive(pid))
                    runtime.jobs.cancel(session.store, job.job_id)
                    self.assertTrue(runtime.jobs.wait_until_idle(session.store, 5))
                finished = session.store.get_processing_job(job.job_id)
                self.assertEqual(finished.status, "CANCELLED")
                self.assertFalse(_alive(pid))
                self.assertIsNone(session.store.get_active_run_id(asset, "diarization"))
                self.assertEqual(session.store.list_run_ids(asset, "diarization"), [])
                self.assertFalse((private_directory(root) / ".diarize" / job.job_id).exists())
            finally:
                runtime.shutdown()

    def test_rejected_requests_do_not_start_dsp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="phase10"))
            try:
                session = runtime.create_project(root, "Take")
                source = root / "master.mov"
                source.write_bytes(b"master-bytes")
                asset = session.store.add_media_asset(
                    display_name="master.mov",
                    location_kind="external",
                    external_path=str(source),
                )
                proxy = session.store.add_media_asset(
                    display_name="proxy.mov",
                    role="proxy",
                    location_kind="external",
                    external_path=str(source),
                )
                with patch.dict(os.environ, {"AMIX_DIARIZE_TEST_WORKER": "emit", "AMIX_DIARIZE_TEST_EVIDENCE": str(root / "missing.json")}):
                    extra = runtime.jobs.submit(session.store, DIARIZE_AUDIO, {"cluster_count": 2}, asset)
                    proxy_job = runtime.jobs.submit(session.store, DIARIZE_AUDIO, {}, proxy)
                    missing_transcript = runtime.jobs.submit(session.store, DIARIZE_AUDIO, {}, asset)
                    extra_done = _wait_job(session.store, extra.job_id)
                    proxy_done = _wait_job(session.store, proxy_job.job_id)
                    quiet = _wait_job(session.store, missing_transcript.job_id)
                self.assertEqual(extra_done.error_code, "job_spec_rejected")
                self.assertEqual(proxy_done.error_code, "diarization_requires_source")
                self.assertEqual(quiet.error_code, "no_active_transcript")
                self.assertEqual(session.store.list_run_ids(asset, "diarization"), [])
            finally:
                runtime.shutdown()


def _same_partition(got: list[dict], expected: list[dict]) -> bool:
    """True when segment boundaries match after one cluster-label permutation."""
    got_keys = sorted({item["cluster_key"] for item in got})
    expected_keys = sorted({item["cluster_key"] for item in expected})
    if len(got_keys) != len(expected_keys):
        return False

    def bounds(rows: list[dict], key: str) -> set[tuple[int, int]]:
        return {(int(row["start_us"]), int(row["end_us"])) for row in rows if row["cluster_key"] == key}

    from itertools import permutations

    for order in permutations(expected_keys):
        mapping = dict(zip(got_keys, order))
        if all(bounds(got, key) == bounds(expected, mapping[key]) for key in got_keys):
            return True
    return False


@unittest.skipUnless(FEATURES.is_file(), "CFS03 feature fixture is not in the tree")
class FeatureFixtureTests(unittest.TestCase):
    def test_clustering_matches_the_proof_modulo_labels(self) -> None:
        from amix.amix_engine.adapters.diarize.mfcc_kmeans import cluster_windows

        loaded = np.load(FEATURES)
        segments, _meta = cluster_windows(loaded["features"], loaded["times"], loaded["energy"], 2960.0)
        got = [
            {
                "cluster_key": item["cluster_key"],
                "start_us": legacy_seconds_to_us(item["start"]),
                "end_us": legacy_seconds_to_us(item["end"]),
            }
            for item in segments
        ]
        document = json.loads(EXPECTED_SEGMENTS.read_text(encoding="utf-8"))
        expected = [
            {
                "cluster_key": item["cluster_id"],
                "start_us": legacy_seconds_to_us(str(item["start"])),
                "end_us": legacy_seconds_to_us(str(item["end"])),
            }
            for item in document["segments"]
        ]
        self.assertTrue(_same_partition(got, expected))
