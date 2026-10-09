"""Dogfood UX: project folder, automatic ingest, layout candidates, transcription errors."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amix.amix_engine.jobs.media import prepare_state
from amix.amix_engine.layout_detect import candidate_regions, expand_face
from amix.amix_engine.storage.project import DATABASE_NAME, create_project, database_file, open_project
from amix.amix_engine.workers.transcribe import classify_transcription_error, main
from amix.tests.test_service import _client, _create, _headers


class ProjectLayoutTests(unittest.TestCase):
    def test_new_projects_keep_internals_beside_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Show"
            store = create_project(root, "Show")
            try:
                self.assertEqual(store.project_id, store.project_id)
                self.assertTrue((root / "exports").is_dir())
                self.assertTrue((root / ".amix" / DATABASE_NAME).is_file())
                self.assertFalse((root / DATABASE_NAME).exists())
                self.assertTrue((root / ".amix" / "manifest.json").is_file())
            finally:
                store.close()
            again = open_project(root)
            try:
                self.assertEqual(again.project_id, store.project_id)
            finally:
                again.close()

    def test_previous_layout_still_opens_without_a_second_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Old"
            store = create_project(root, "Old")
            project_id = store.project_id
            store.close()
            private = root / ".amix"
            (root / DATABASE_NAME).write_bytes((private / DATABASE_NAME).read_bytes())
            (private / DATABASE_NAME).unlink()
            (root / "manifest.json").write_text((private / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
            opened = open_project(root)
            try:
                self.assertEqual(opened.project_id, project_id)
                self.assertEqual(opened.private, root.resolve())
                self.assertFalse((root / ".amix" / DATABASE_NAME).exists())
            finally:
                opened.close()


class IngestTests(unittest.TestCase):
    def test_import_queues_one_probe_for_one_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, client = _client(tmp)
            try:
                project = _create(client, root / "Show", "Show")
                handle = project["handle"]
                media = root / "clip.bin"
                media.write_bytes(b"not-a-media-file")
                linked = client.post(
                    f"/v1/projects/{handle}/media",
                    headers=_headers(),
                    json={"path": str(media)},
                )
                self.assertEqual(linked.status_code, 200, linked.text)
                asset_id = linked.json()["asset_id"]
                self.assertEqual(linked.json()["prepare_state"], "preparing")
                listed = client.get(f"/v1/projects/{handle}/media", headers=_headers())
                masters = [item for item in listed.json() if item["role"] == "master"]
                self.assertEqual([item["asset_id"] for item in masters], [asset_id])
                jobs = client.get(f"/v1/projects/{handle}/jobs", headers=_headers())
                probes = [job for job in jobs.json() if job["kind"] == "media_probe"]
                self.assertEqual(len(probes), 1)
                self.assertEqual(probes[0]["media_asset_id"], asset_id)
                self.assertTrue(runtime.jobs.wait_until_idle(runtime.session(handle).store, 30))
                after = client.get(f"/v1/projects/{handle}/media", headers=_headers()).json()
                master = next(item for item in after if item["asset_id"] == asset_id)
                self.assertEqual(master["prepare_state"], "failed")
                self.assertEqual(master["status"], "present")
            finally:
                client.close()
                runtime.shutdown()


class LayoutCandidateTests(unittest.TestCase):
    def test_two_and_three_faces_become_editable_regions_without_names(self) -> None:
        picture = (1920, 1080)
        two = [(100.0, 80.0, 120.0, 140.0), (900.0, 100.0, 110.0, 130.0)]
        three = two + [(1500.0, 90.0, 100.0, 120.0)]
        first = candidate_regions(two, *picture)
        second = candidate_regions(three, *picture)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 3)
        self.assertLess(first[0]["x"], first[1]["x"])
        for region in second:
            self.assertGreaterEqual(region["x"], 0)
            self.assertGreaterEqual(region["y"], 0)
            self.assertLessEqual(region["x"] + region["w"], picture[0])
            self.assertLessEqual(region["y"] + region["h"], picture[1])
            self.assertNotIn("participant_id", region)
        grown = expand_face(100, 80, 120, 140, *picture)
        assert grown is not None
        self.assertGreater(grown[2], 120)
        self.assertGreater(grown[3], 140)

    def test_prepare_state_is_not_ready_while_preview_is_running(self) -> None:
        from amix.amix_engine.storage.jobs import StoredJob
        from amix.tests.test_playback import _record
        with tempfile.TemporaryDirectory() as tmp:
            store = create_project(Path(tmp) / "Show", "Show")
            try:
                source = Path(tmp) / "clip.mp4"
                source.write_bytes(b"clip")
                asset_id = store.add_media_asset(
                    display_name="clip.mp4",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=4,
                    file_mtime_ns=1,
                )
                store.apply_probe(asset_id, _record(byte_size=4, file_mtime_ns=1))
                asset = store.get_media(asset_id)
                running = StoredJob(
                    "job", store.project_id, asset_id, "generate_proxy", "RUNNING", 0,
                    {}, None, None, None, "now", "now", None, False, 1, None, None,
                )
                self.assertEqual(prepare_state(
                    asset, None, [running],
                    source_present=True, source_size=4, source_mtime_ns=1, proxy_file_present=False,
                ), "ready")
                hevc = store.apply_probe(asset_id, _record(byte_size=4, file_mtime_ns=1, video_codec="hevc"))
                self.assertEqual(prepare_state(
                    hevc, None, [running],
                    source_present=True, source_size=4, source_mtime_ns=1, proxy_file_present=False,
                ), "preparing")
                self.assertEqual(prepare_state(
                    hevc, None, [],
                    source_present=True, source_size=4, source_mtime_ns=1, proxy_file_present=False,
                ), "preview_required")
            finally:
                store.close()


class TranscriptionErrorTests(unittest.TestCase):
    def test_missing_ffmpeg_is_not_internal_error(self) -> None:
        code = classify_transcription_error(FileNotFoundError(2, "The system cannot find the file specified", "ffmpeg"))
        self.assertEqual(code, "ffmpeg_unavailable")
        self.assertNotEqual(code, "internal_error")

    def test_worker_emits_ffmpeg_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = {
                "mode": "transcribe",
                "source_path": str(root / "clip.mov"),
                "model_path": str(root / "model"),
                "device": "cpu",
                "compute_type": "int8",
                "language": None,
                "result_path": str(root / "result.json"),
                "pid_path": str(root / "worker.pid"),
            }
            spec_path = root / "worker.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            from io import StringIO
            output = StringIO()
            with patch(
                "amix.amix_engine.adapters.stt.faster_whisper.transcribe_file",
                side_effect=FileNotFoundError(2, "The system cannot find the file specified", "ffmpeg"),
            ), patch("sys.stdout", output):
                status = main(["--spec", str(spec_path)])
            self.assertEqual(status, 1)
            self.assertIn("ffmpeg_unavailable", output.getvalue())
            self.assertNotIn("internal_error", output.getvalue())
