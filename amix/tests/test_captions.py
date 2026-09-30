"""Caption tracks, sequence timing, and subtitle sidecars. No network, model, or FFmpeg."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amix.amix_engine.captions.segment import (
    PROFILE_ID,
    CaptionRejected,
    CaptionWord,
    build_cues,
    cue_at_source,
    effective_text_fingerprint,
    ends_sentence,
    normalize_caption_text,
    stale_reasons,
    word_in_clip,
    word_midpoint_us,
)
from amix.amix_engine.captions.serialize import render_srt, render_vtt
from amix.amix_engine.captions.service import (
    caption_state,
    edit_cue_text,
    export_captions,
    generate_captions,
    reset_cue_text,
)
from amix.amix_engine.domain.types import Word
from amix.amix_engine.editorial.sequence import split_clip
from amix.amix_engine.storage.errors import NoActiveTranscript
from amix.amix_engine.storage.project import create_project


def _word(word_id: str, start: int, end: int, text: str, sequence: int = 0) -> CaptionWord:
    return CaptionWord(word_id, sequence, text, start, end)


class GenerationTests(unittest.TestCase):
    def test_simple_sentence_stays_one_cue(self) -> None:
        cues = build_cues([(0, 5_000_000)], [
            _word("a", 0, 400_000, "Hello", 0),
            _word("b", 400_000, 800_000, "there", 1),
        ])
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].generated_text, "Hello there")
        self.assertNotIn("\n", cues[0].generated_text)

    def test_punctuation_gap_duration_and_word_count_break_cues(self) -> None:
        self.assertTrue(ends_sentence("سلام."))
        self.assertTrue(ends_sentence("done?"))
        self.assertTrue(ends_sentence("چرا؟"))
        punctuated = build_cues([(0, 5_000_000)], [
            _word("a", 0, 200_000, "Hello.", 0),
            _word("b", 200_000, 400_000, "Next", 1),
        ])
        self.assertEqual([cue.generated_text for cue in punctuated], ["Hello.", "Next"])
        gapped = build_cues([(0, 5_000_000)], [
            _word("a", 0, 100_000, "one", 0),
            _word("b", 900_000, 1_000_000, "two", 1),
        ])
        self.assertEqual(len(gapped), 2)
        long_gap = build_cues([(0, 20_000_000)], [
            _word("a", 0, 100_000, "start", 0),
            _word("b", 6_200_000, 6_400_000, "later", 1),
        ])
        self.assertEqual(len(long_gap), 2)
        many = [
            _word(f"w{index}", index * 100_000, index * 100_000 + 50_000, "word", index)
            for index in range(13)
        ]
        counted = build_cues([(0, 5_000_000)], many)
        self.assertEqual([len(cue.generated_text.split()) for cue in counted], [12, 1])

    def test_clip_boundary_and_removed_gap(self) -> None:
        clips = [(0, 5_000_000), (5_000_000, 10_000_000)]
        words = [
            _word("a", 4_800_000, 5_000_000, "left", 0),
            _word("b", 5_000_000, 5_200_000, "right", 1),
        ]
        cues = build_cues(clips, words)
        self.assertEqual([cue.generated_text for cue in cues], ["left", "right"])
        self.assertEqual(cues[0].source_end_us, 5_000_000)
        self.assertEqual(cues[1].source_start_us, 5_000_000)
        removed = build_cues([(0, 10_000_000), (20_000_000, 30_000_000)], [
            _word("gap", 12_000_000, 14_000_000, "gone", 0),
            _word("kept", 20_000_000, 25_000_000, "stay", 1),
        ])
        self.assertEqual([cue.generated_text for cue in removed], ["stay"])

    def test_midpoint_inclusion_is_half_open(self) -> None:
        word = _word("w", 0, 10, "x")
        self.assertEqual(word_midpoint_us(0, 10), 5)
        self.assertTrue(word_in_clip(word, 5, 15))
        self.assertFalse(word_in_clip(word, 0, 5))
        cues = build_cues([(5, 15)], [word])
        self.assertEqual(len(cues), 1)
        self.assertEqual(build_cues([(0, 5)], [word]), [])

    def test_effective_text_rtl_and_mixed_text(self) -> None:
        cues = build_cues([(0, 2_000_000)], [
            _word("a", 0, 200_000, "سلام", 0),
            _word("b", 200_000, 400_000, "hello", 1),
        ])
        self.assertEqual(cues[0].generated_text, "سلام hello")
        self.assertEqual(build_cues([(0, 1_000_000)], []), [])
        blank = build_cues([(0, 1_000_000)], [_word("a", 0, 100_000, "   ", 0)])
        self.assertEqual(blank, [])

    def test_sequence_time_skips_the_removed_gap(self) -> None:
        clips = [(0, 10_000_000), (20_000_000, 30_000_000)]
        cues = build_cues(clips, [_word("w", 20_000_000, 25_000_000, "later")])
        self.assertEqual(cues[0].source_start_us, 20_000_000)
        self.assertEqual(cues[0].source_end_us, 25_000_000)
        self.assertEqual(cues[0].sequence_start_us, 10_000_000)
        self.assertEqual(cues[0].sequence_end_us, 15_000_000)
        rendered = render_srt([{
            "sequence_start_us": cues[0].sequence_start_us,
            "sequence_end_us": cues[0].sequence_end_us,
            "generated_text": "بعد",
            "manual_text": None,
        }])
        self.assertIn("00:00:10,000 --> 00:00:15,000", rendered)
        self.assertNotIn("00:00:20,000", rendered)
        self.assertIn("بعد", rendered)

    def test_cue_lookup_is_half_open_and_manual_text_is_one_line(self) -> None:
        cue = {"source_start_us": 0, "source_end_us": 10, "generated_text": "a", "manual_text": None}
        self.assertIs(cue_at_source([cue], 0), cue)
        self.assertIsNone(cue_at_source([cue], 10))
        self.assertEqual(normalize_caption_text("  سلام\nدنیا  "), "سلام دنیا")
        with self.assertRaises(CaptionRejected) as caught:
            normalize_caption_text(" \n\t ")
        self.assertEqual(caught.exception.code, "invalid_caption_text")

    def test_unrelated_axes_are_not_staleness_inputs(self) -> None:
        reasons = stale_reasons(
            sequence_revision=3,
            sequence_revision_at_generation=3,
            transcript_run_id="run",
            transcript_analysis_run_id="run",
            effective_fingerprint="abc",
            stored_fingerprint="abc",
        )
        self.assertEqual(reasons, [])
        self.assertEqual(
            stale_reasons(
                sequence_revision=4,
                sequence_revision_at_generation=3,
                transcript_run_id="other",
                transcript_analysis_run_id="run",
                effective_fingerprint="xyz",
                stored_fingerprint="abc",
            ),
            ["sequence_revision", "transcript", "effective_text"],
        )
        self.assertNotIn("render_profile", stale_reasons.__code__.co_varnames)
        self.assertNotIn("visual_treatment", stale_reasons.__code__.co_varnames)


class SrtVttTests(unittest.TestCase):
    def test_srt_and_vtt_use_sequence_time_manual_text_and_utf8(self) -> None:
        cues = [{
            "sequence_start_us": 10_000_000,
            "sequence_end_us": 15_000_000,
            "generated_text": "generated",
            "manual_text": "سلام",
        }]
        srt = render_srt(cues)
        vtt = render_vtt(cues)
        self.assertTrue(srt.startswith("1\n00:00:10,000 --> 00:00:15,000\nسلام"))
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("00:00:10.000 --> 00:00:15.000", vtt)
        self.assertIn("سلام", vtt)
        self.assertNotIn("generated", srt)
        self.assertEqual(srt.encode("utf-8").decode("utf-8"), srt)


class StoreTests(unittest.TestCase):
    def test_generation_edits_staleness_and_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            store = create_project(root, "Take")
            try:
                asset = store.add_media_asset(
                    display_name="clip.mov", location_kind="external", external_path=str(root / "clip.mov"),
                )
                store.insert_editorial_sequence(
                    asset_id=asset,
                    display_name="Edit",
                    source_start_us=0,
                    source_end_us=30_000_000,
                    clips=[(0, 10_000_000), (20_000_000, 30_000_000)],
                )
                sequence = store.load_editorial_sequence(asset)
                assert sequence is not None
                with self.assertRaises(NoActiveTranscript):
                    generate_captions(store, sequence["sequence_id"])
                empty_run = store.save_transcript(
                    asset_id=asset, words=[], algorithm_id="amix.transcript.import",
                    algorithm_version="1", fingerprint="empty",
                )
                store.set_active(asset, "transcript", empty_run)
                empty = generate_captions(store, sequence["sequence_id"])
                self.assertEqual(empty["status"], "ready")
                self.assertEqual(empty["cues"], [])
                self.assertEqual(empty["profile"], PROFILE_ID)
                words = [
                    Word("w1", 0, 400_000, "Hello."),
                    Word("w2", 400_000, 800_000, "machine"),
                    Word("w3", 20_000_000, 25_000_000, "later"),
                    Word("w4", 12_000_000, 13_000_000, "removed"),
                ]
                run = store.save_transcript(
                    asset_id=asset, words=words, algorithm_id="amix.transcript.import",
                    algorithm_version="1", fingerprint="words",
                )
                store.set_active(asset, "transcript", run)
                store.correct_word_text("w2", "corrected", scope_id=run)
                before_runs = store.count_analysis_runs()
                state = generate_captions(store, sequence["sequence_id"])
                self.assertEqual(state["status"], "ready")
                self.assertEqual([cue["generated_text"] for cue in state["cues"]], ["Hello.", "corrected", "later"])
                later = next(cue for cue in state["cues"] if cue["generated_text"] == "later")
                self.assertEqual(later["first_word_id"], "w3")
                self.assertEqual(later["source_start_us"], 20_000_000)
                self.assertEqual(later["sequence_start_us"], 10_000_000)
                self.assertEqual(later["sequence_end_us"], 15_000_000)
                self.assertNotIn("render_profile", state)
                self.assertNotIn("visual_treatment", state)
                self.assertEqual(store.machine_word_text("w2"), "machine")
                self.assertEqual(store.load_words(run)[1].effective_text, "corrected")
                edited = edit_cue_text(store, sequence["sequence_id"], later["cue_id"], "  دستی  ")
                cue = next(item for item in edited["cues"] if item["cue_id"] == later["cue_id"])
                self.assertEqual(cue["generated_text"], "later")
                self.assertEqual(cue["manual_text"], "دستی")
                self.assertEqual(cue["effective_text"], "دستی")
                self.assertEqual(edited["revision"], 2)
                self.assertEqual(store.load_editorial_sequence(asset)["revision"], sequence["revision"])
                self.assertEqual(store.machine_word_text("w2"), "machine")
                self.assertEqual(store.load_words(run)[1].effective_text, "corrected")
                self.assertEqual(store.count_analysis_runs(), before_runs)
                self.assertIsNone(store.get_active_run_id(asset, "conversation_map"))
                self.assertIsNone(store.get_active_run_id(asset, "reel_discovery"))
                with self.assertRaises(CaptionRejected):
                    edit_cue_text(store, sequence["sequence_id"], later["cue_id"], "   ")
                reset = reset_cue_text(store, sequence["sequence_id"], later["cue_id"])
                restored = next(item for item in reset["cues"] if item["cue_id"] == later["cue_id"])
                self.assertIsNone(restored["manual_text"])
                self.assertEqual(restored["effective_text"], "later")
                self.assertEqual(reset["revision"], 3)
                store.correct_word_text("w2", "again", scope_id=run)
                stale_text = caption_state(store, sequence["sequence_id"])
                self.assertEqual(stale_text["status"], "stale")
                self.assertIn("effective_text", stale_text["stale_reasons"])
                self.assertEqual(stale_text["track_id"], state["track_id"])
                replacement = store.save_transcript(
                    asset_id=asset, words=[Word("n1", 0, 200_000, "new")],
                    algorithm_id="amix.transcript.import", algorithm_version="1", fingerprint="new",
                )
                store.set_active(asset, "transcript", replacement)
                stale_run = caption_state(store, sequence["sequence_id"])
                self.assertIn("transcript", stale_run["stale_reasons"])
                store.set_active(asset, "transcript", run)
                ready_again = generate_captions(store, sequence["sequence_id"])
                self.assertEqual(ready_again["status"], "ready")
                self.assertNotEqual(ready_again["track_id"], state["track_id"])
                split_clip(store, sequence["sequence_id"], sequence["clips"][0]["clip_id"], 5_000_000)
                stale_sequence = caption_state(store, sequence["sequence_id"])
                self.assertEqual(stale_sequence["status"], "stale")
                self.assertIn("sequence_revision", stale_sequence["stale_reasons"])
                with self.assertRaises(CaptionRejected) as caught:
                    export_captions(store, sequence["sequence_id"], "srt")
                self.assertEqual(caught.exception.code, "captions_stale")
                fresh = generate_captions(store, sequence["sequence_id"])
                exported = export_captions(store, sequence["sequence_id"], "srt")
                vtt = export_captions(store, sequence["sequence_id"], "vtt")
                srt_path = root / exported["relative_path"]
                vtt_path = root / vtt["relative_path"]
                self.assertTrue(str(exported["relative_path"]).startswith("exports/captions/"))
                self.assertTrue(srt_path.is_file())
                self.assertTrue(vtt_path.is_file())
                self.assertTrue(srt_path.resolve().is_relative_to(root.resolve()))
                self.assertEqual(exported["role"], "sidecar")
                self.assertEqual(exported["sequence_id"], sequence["sequence_id"])
                self.assertEqual(exported["caption_track_id"], fresh["track_id"])
                self.assertEqual(exported["source_media_asset_id"], asset)
                self.assertNotIn("render_profile", exported)
                text = srt_path.read_text(encoding="utf-8")
                self.assertIn("00:00:10,000", text)
                self.assertNotIn("00:00:20,000", text)
                self.assertEqual(vtt["format"], "vtt")
                self.assertTrue(vtt_path.read_text(encoding="utf-8").startswith("WEBVTT\n"))
                generate_captions(store, sequence["sequence_id"])
                self.assertTrue(srt_path.is_file())
                self.assertTrue(vtt_path.is_file())
                reel_id = store.insert_editorial_sequence(
                    asset_id=asset,
                    display_name="Reel",
                    source_start_us=0,
                    source_end_us=10_000_000,
                    clips=[(0, 10_000_000)],
                    purpose="reel",
                    origin_candidate_id="candidate-1",
                )
                reel = generate_captions(store, reel_id)
                self.assertEqual(reel["purpose"], "reel")
                self.assertNotEqual(reel["track_id"], fresh["track_id"])
                self.assertEqual(caption_state(store, sequence["sequence_id"])["purpose"], "primary")
            finally:
                store.close()


class RouteTests(unittest.TestCase):
    def test_caption_route_rejects_an_output_path(self) -> None:
        import warnings

        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated",
        )
        from fastapi.testclient import TestClient

        from amix.amix_engine.service.app import create_app
        from amix.amix_engine.service.config import ServiceConfig
        from amix.amix_engine.service.runtime import EngineRuntime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Take"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="caption-test"))
            client = TestClient(create_app(runtime))
            try:
                created = client.post(
                    "/v1/projects/create",
                    headers={"Authorization": "Bearer caption-test"},
                    json={"path": str(root), "name": "Take"},
                )
                self.assertEqual(created.status_code, 200, created.text)
                handle = created.json()["handle"]
                session = next(iter(runtime._sessions.values()))
                asset = session.store.add_media_asset(
                    display_name="clip.mov", location_kind="external", external_path=str(root / "clip.mov"),
                )
                session.store.insert_editorial_sequence(
                    asset_id=asset, display_name="Edit", source_start_us=0, source_end_us=1_000_000,
                    clips=[(0, 1_000_000)],
                )
                sequence = session.store.load_editorial_sequence(asset)
                assert sequence is not None
                run = session.store.save_transcript(
                    asset_id=asset, words=[Word("w", 0, 200_000, "سلام")],
                    algorithm_id="amix.transcript.import", algorithm_version="1", fingerprint="t",
                )
                session.store.set_active(asset, "transcript", run)
                headers = {"Authorization": "Bearer caption-test"}
                generated = client.post(
                    f"/v1/projects/{handle}/sequences/{sequence['sequence_id']}/captions",
                    headers=headers,
                )
                self.assertEqual(generated.status_code, 200, generated.text)
                self.assertEqual(generated.json()["cues"][0]["generated_text"], "سلام")
                exported = client.post(
                    f"/v1/projects/{handle}/sequences/{sequence['sequence_id']}/captions/export",
                    headers=headers,
                    json={"format": "srt", "path": str(root.parent / "escape.srt")},
                )
                self.assertEqual(exported.status_code, 400, exported.text)
                self.assertEqual(exported.json()["error"]["code"], "invalid_request")
                self.assertFalse((root.parent / "escape.srt").exists())
                self.assertEqual(
                    effective_text_fingerprint([CaptionWord("w", 0, "سلام", 0, 200_000)]),
                    generated.json()["effective_text_fingerprint"],
                )
            finally:
                client.close()
                runtime.shutdown()
