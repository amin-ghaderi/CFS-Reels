"""Media link/relink and active-transcript reads. Temporary files only."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amix.amix_engine.domain.types import ParticipantId, SpeakerAssignment, Word
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.project import create_project
from amix.amix_engine.time.clock import TimeRange
from amix.tests.test_service import _client, _create, _headers


class MediaTranscriptApiTests(unittest.TestCase):
    def test_link_list_status_relink_and_transcript_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, client = _client(tmp)
            try:
                project = _create(client, root / "Show", "Show")
                handle = project["handle"]
                media = root / "clip.bin"
                media.write_bytes(b"amix-media")
                linked = client.post(
                    f"/v1/projects/{handle}/media",
                    headers=_headers(),
                    json={"path": str(media)},
                )
                self.assertEqual(linked.status_code, 200, linked.text)
                asset = linked.json()
                self.assertEqual(asset["role"], "master")
                self.assertEqual(asset["display_name"], "clip.bin")
                self.assertEqual(asset["location_kind"], "external")
                self.assertEqual(asset["byte_size"], len(b"amix-media"))
                self.assertEqual(asset["status"], "present")
                self.assertIsNone(asset["duration_us"])
                self.assertIsNone(asset["width"])
                self.assertIsNone(asset["height"])
                asset_id = asset["asset_id"]

                listed = client.get(f"/v1/projects/{handle}/media", headers=_headers())
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()[0]["asset_id"], asset_id)

                empty = client.get(f"/v1/projects/{handle}/media/{asset_id}/transcript", headers=_headers())
                self.assertEqual(empty.status_code, 200, empty.text)
                self.assertFalse(empty.json()["active"])
                missing_words = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/words/0/10",
                    headers=_headers(),
                )
                self.assertEqual(missing_words.status_code, 404)
                self.assertEqual(missing_words.json()["error"]["code"], "no_active_transcript")

                self._seed_transcript(runtime, handle, asset_id)
                described = client.get(f"/v1/projects/{handle}/media/{asset_id}/transcript", headers=_headers())
                self.assertTrue(described.json()["active"])
                self.assertEqual(described.json()["word_count"], 5)
                self.assertEqual(described.json()["analysis_run_id"], self.run_id)

                first = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/words/0/2",
                    headers=_headers(),
                )
                self.assertEqual(first.status_code, 200, first.text)
                page = first.json()
                self.assertEqual([word["sequence"] for word in page["words"]], [0, 1])
                self.assertEqual(page["words"][0]["machine_text"], "one")
                self.assertEqual(page["words"][0]["effective_text"], "one")
                self.assertFalse(page["words"][0]["text_corrected"])
                self.assertEqual(page["words"][0]["participant_id"], "p1")
                self.assertEqual(page["words"][0]["participant_name"], "Ava")
                self.assertEqual(page["words"][1]["participant_id"], None)
                self.assertEqual(page["word_count"], 5)
                self.assertIsInstance(page["words"][0]["start_us"], int)

                second = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/words/2/2",
                    headers=_headers(),
                )
                self.assertEqual([word["word_id"] for word in second.json()["words"]], ["w2", "w3"])
                self.assertEqual(second.json()["words"][0]["machine_text"], "سه")

                too_big = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/words/0/401",
                    headers=_headers(),
                )
                self.assertEqual(too_big.status_code, 400)
                self.assertEqual(too_big.json()["error"]["code"], "invalid_word_page")

                edited = client.post(
                    f"/v1/projects/{handle}/media/{asset_id}/words/w0/text",
                    headers=_headers(),
                    json={"text": "ONE"},
                )
                self.assertEqual(edited.status_code, 200, edited.text)
                self.assertEqual(edited.json()["effective_text"], "ONE")
                self.assertEqual(edited.json()["machine_text"], "one")
                self.assertTrue(edited.json()["text_corrected"])

                reverted = client.post(
                    f"/v1/projects/{handle}/media/{asset_id}/words/w0/text/clear",
                    headers=_headers(),
                )
                self.assertEqual(reverted.status_code, 200, reverted.text)
                self.assertEqual(reverted.json()["effective_text"], "one")
                self.assertEqual(reverted.json()["machine_text"], "one")
                self.assertFalse(reverted.json()["text_corrected"])

                media.unlink()
                status = client.get(f"/v1/projects/{handle}/media/{asset_id}/status", headers=_headers())
                self.assertEqual(status.json()["status"], "missing")
                still = client.get(
                    f"/v1/projects/{handle}/media/{asset_id}/transcript/words/0/5",
                    headers=_headers(),
                )
                self.assertEqual(still.status_code, 200, still.text)
                self.assertEqual(len(still.json()["words"]), 5)
                self.assertEqual(still.json()["words"][0]["word_id"], "w0")

                replacement = root / "clip-relinked.bin"
                replacement.write_bytes(b"relinked-bytes")
                again = client.post(
                    f"/v1/projects/{handle}/media/{asset_id}/relink",
                    headers=_headers(),
                    json={"path": str(replacement)},
                )
                self.assertEqual(again.status_code, 200, again.text)
                self.assertEqual(again.json()["asset_id"], asset_id)
                self.assertEqual(again.json()["status"], "present")
                self.assertEqual(again.json()["byte_size"], len(b"relinked-bytes"))
                self.assertEqual(again.json()["display_name"], "clip-relinked.bin")
                after = client.get(f"/v1/projects/{handle}/media/{asset_id}/transcript", headers=_headers())
                self.assertEqual(after.json()["analysis_run_id"], self.run_id)
                self.assertEqual(after.json()["transcript_id"], self.transcript_id)

                rejected = client.post(
                    f"/v1/projects/{handle}/media",
                    headers=_headers(),
                    json={"path": str(root), "role": "master"},
                )
                self.assertEqual(rejected.status_code, 400)
                self.assertEqual(rejected.json()["error"]["code"], "invalid_media_path")
                bad_role = client.post(
                    f"/v1/projects/{handle}/media",
                    headers=_headers(),
                    json={"path": str(replacement), "role": "raw_source"},
                )
                self.assertEqual(bad_role.status_code, 400)
                self.assertEqual(bad_role.json()["error"]["code"], "invalid_media_role")
            finally:
                client.close()
                runtime.shutdown()

    def _seed_transcript(self, runtime: EngineRuntime, handle: str, asset_id: str) -> None:
        opened = runtime.session(handle).store
        opened.add_participant("p1", "Ava")
        words = [
            Word("w0", 0, 500_000, "one"),
            Word("w1", 500_000, 1_000_000, "two"),
            Word("w2", 1_000_000, 1_500_000, "سه"),
            Word("w3", 1_500_000, 2_000_000, "four"),
            Word("w4", 2_000_000, 2_500_000, "five"),
        ]
        run_id = opened.save_transcript(
            asset_id=asset_id,
            words=words,
            algorithm_id="amix.transcript.import",
            algorithm_version="1",
            fingerprint="page",
            language="fa",
            window=TimeRange(0, 2_500_000),
            confidences={"w0": 0.9},
        )
        opened.set_active(asset_id, "transcript", run_id)
        assignment = opened.save_assignments(
            asset_id=asset_id,
            assignments=[
                SpeakerAssignment("w0", ParticipantId("p1")),
                SpeakerAssignment("w1", None),
            ],
            depends_on=[run_id],
            algorithm_id="amix.assign",
            algorithm_version="1",
            fingerprint="assign",
            window=TimeRange(0, 2_500_000),
        )
        opened.set_active(asset_id, "participant_assignment", assignment)
        self.run_id = run_id
        self.transcript_id = opened.transcript_id(run_id)


class DirectStoreTests(unittest.TestCase):
    def test_clearing_a_correction_restores_machine_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = create_project(Path(tmp) / "Edit", "Edit")
            try:
                asset = store.add_media_asset(
                    display_name="clip",
                    location_kind="external",
                    external_path=str(Path(tmp) / "missing.mp4"),
                )
                run_id = store.save_transcript(
                    asset_id=asset,
                    words=[Word("w", 10, 20, "foo")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="t",
                    window=TimeRange(0, 20),
                )
                store.set_active(asset, "transcript", run_id)
                store.correct_word_text("w", "bar", scope_id=run_id)
                self.assertEqual(store.machine_word_text("w"), "foo")
                view = store.active_word_view(asset, "w")
                self.assertEqual(view.effective_text, "bar")
                self.assertIsNone(view.participant_id)
                store.clear_word_text("w")
                restored = store.active_word_view(asset, "w")
                self.assertEqual(restored.machine_text, "foo")
                self.assertEqual(restored.effective_text, "foo")
                self.assertFalse(restored.text_corrected)
                self.assertEqual(store.media_status(asset), "missing")
                self.assertEqual(store.page_active_words(asset, 0, 10)[1][0].effective_text, "foo")
            finally:
                store.close()
