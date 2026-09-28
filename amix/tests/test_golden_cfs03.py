"""CFS03 49–59 minute golden. Inputs are evidence. Expected files are assertions."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from amix.amix_engine.analysis.assign import assign_words
from amix.amix_engine.analysis.overlap import overlap_regions
from amix.amix_engine.analysis.turns import build_turns
from amix.amix_engine.domain.types import (
    DiarizationSegment,
    LayoutBinding,
    LipActivitySeries,
    OverlapRegion,
    ParticipantId,
    Word,
)
from amix.amix_engine.multicam.planner import plan_shots
from amix.amix_engine.time.clock import TimeRange, legacy_seconds_to_us

FIXTURE = Path(__file__).resolve().parent / "golden" / "cfs03_49_59"
WINDOW = TimeRange(legacy_seconds_to_us("2960"), legacy_seconds_to_us("3560"))


def _load(name: str, kind: str) -> dict:
    path = FIXTURE / kind / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("role") != kind[:-1].upper() and payload.get("role") not in {"INPUT", "EXPECTED"}:
        raise AssertionError(f"{path} has no role")
    return payload


class GoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.words_doc = json.loads((FIXTURE / "inputs" / "words.json").read_text(encoding="utf-8"))
        cls.segments_doc = json.loads((FIXTURE / "inputs" / "diarization_segments.json").read_text(encoding="utf-8"))
        cls.map_doc = json.loads((FIXTURE / "inputs" / "cluster_map.json").read_text(encoding="utf-8"))
        cls.layout_doc = json.loads((FIXTURE / "inputs" / "layout.json").read_text(encoding="utf-8"))
        cls.expected_assign = json.loads((FIXTURE / "expected" / "assignments.json").read_text(encoding="utf-8"))
        cls.expected_turns = json.loads((FIXTURE / "expected" / "turns.json").read_text(encoding="utf-8"))
        cls.expected_overlaps = json.loads((FIXTURE / "expected" / "overlaps.json").read_text(encoding="utf-8"))
        cls.expected_shots = json.loads((FIXTURE / "expected" / "shots.json").read_text(encoding="utf-8"))
        for doc in (cls.words_doc, cls.segments_doc, cls.map_doc, cls.layout_doc):
            if doc["role"] != "INPUT":
                raise AssertionError("golden input is not marked INPUT")
        for doc in (cls.expected_assign, cls.expected_turns, cls.expected_overlaps, cls.expected_shots):
            if doc["role"] != "EXPECTED":
                raise AssertionError("golden expectation is not marked EXPECTED")

    def _words(self) -> list[Word]:
        words = []
        for row in self.words_doc["words"]:
            self.assertNotIn("speaker", row)
            self.assertNotIn("participant_id", row)
            words.append(Word(
                row["word_id"],
                legacy_seconds_to_us(row["start"]),
                legacy_seconds_to_us(row["end"]),
                row["text"],
            ))
        self.assertGreater(words[0].start_us, 2_900_000_000)
        self.assertLess(words[0].start_us, 3_000_000_000)
        return words

    def _segments(self) -> list[DiarizationSegment]:
        return [
            DiarizationSegment(
                legacy_seconds_to_us(row["start"]),
                legacy_seconds_to_us(row["end"]),
                row["cluster_id"],
            )
            for row in self.segments_doc["segments"]
        ]

    def _cluster_map(self) -> dict[str, ParticipantId]:
        return {key: ParticipantId(value) for key, value in self.map_doc["map"].items()}

    def _bindings(self) -> list[LayoutBinding]:
        return [
            LayoutBinding(
                ParticipantId(row["participant_id"]),
                row["x"], row["y"], row["w"], row["h"],
                WINDOW,
            )
            for row in self.layout_doc["bindings"]
        ]

    def test_assignments(self) -> None:
        words = self._words()
        got = assign_words(words, self._segments(), self._cluster_map())
        expected = self.expected_assign["assignments"]
        self.assertEqual(len(got), len(expected))
        for row, want in zip(got, expected):
            got_id = None if row.participant_id is None else row.participant_id.value
            self.assertEqual(row.word_id, want["word_id"])
            self.assertEqual(got_id, want["participant_id"])

    def test_turns(self) -> None:
        words = self._words()
        assignments = assign_words(words, self._segments(), self._cluster_map())
        turns = build_turns(words, assignments)
        expected = self.expected_turns["turns"]
        self.assertEqual(len(turns), len(expected))
        for turn, want in zip(turns, expected):
            got_id = None if turn.participant_id is None else turn.participant_id.value
            self.assertEqual(turn.turn_id, want["turn_id"])
            self.assertEqual(got_id, want["participant_id"])
            self.assertEqual(turn.start_us, want["start_us"])
            self.assertEqual(turn.end_us, want["end_us"])
            self.assertEqual(turn.word_count, want["word_count"])

    def test_overlap_regions(self) -> None:
        payload = json.loads((FIXTURE / "inputs" / "lip_activity.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["role"], "INPUT")
        self.assertNotIn("regions", payload)
        regions = self._activity_regions()
        expected = self.expected_overlaps["regions"]
        self.assertEqual(len(regions), len(expected))
        for region, want in zip(regions, expected):
            self.assertEqual(region.start_us, want["start_us"])
            self.assertEqual(region.end_us, want["end_us"])
            self.assertEqual([item.value for item in region.participant_ids], want["participant_ids"])
            self.assertEqual(region.confidence, want["confidence"])

    def _activity_regions(self) -> list[OverlapRegion]:
        path = FIXTURE / "inputs" / "lip_activity.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        people = tuple(ParticipantId(value) for value in payload["column_order"])
        series = LipActivitySeries(
            legacy_seconds_to_us(payload["origin_seconds"]),
            1_000_000 // payload["sample_fps"],
            people,
            tuple(tuple(frame) for frame in payload["scores"]),
            tuple(payload["audio_rms"]),
        )
        return overlap_regions(series, WINDOW)

    def test_automatic_shot_plan(self) -> None:
        words = self._words()
        assignments = assign_words(words, self._segments(), self._cluster_map())
        turns = build_turns(words, assignments)
        overlaps = self._activity_regions()
        plan = plan_shots(WINDOW, turns, words, overlaps, self._bindings(), [])
        expected = self.expected_shots["shots"]
        self.assertEqual(len(plan.shots), len(expected), _shot_diff(plan.shots, expected))
        for shot, want in zip(plan.shots, expected):
            got = {
                "start_us": shot.start_us,
                "end_us": shot.end_us,
                "presentation": shot.presentation.value,
                "participant_id": None if shot.participant_id is None else shot.participant_id.value,
                "floor_participant_id": None if shot.floor_participant_id is None else shot.floor_participant_id.value,
                "reason": shot.reason,
            }
            self.assertEqual(got, want)
        self.assertEqual(plan.shots[0].start_us, WINDOW.start_us)
        self.assertEqual(plan.shots[-1].end_us, WINDOW.end_us)
        for prev, nxt in zip(plan.shots, plan.shots[1:]):
            self.assertEqual(prev.end_us, nxt.start_us)

    def test_product_modules_do_not_name_legacy_tiles(self) -> None:
        root = Path(__file__).resolve().parents[1] / "amix_engine"
        banned = ("speaker_a", "speaker_b", "speaker_c", "FULL_A", "FULL_B", "FULL_C")
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in banned:
                self.assertNotIn(token, text, f"{token} in {path}")


def _shot_diff(shots, expected) -> str:
    if not shots or not expected:
        return f"got {len(shots)} expected {len(expected)}"
    for index, (shot, want) in enumerate(zip(shots, expected)):
        if shot.start_us != want["start_us"] or shot.reason != want["reason"]:
            return f"first difference at {index}: {shot.start_us} {shot.reason} vs {want}"
    return f"got {len(shots)} expected {len(expected)}"


if __name__ == "__main__":
    unittest.main()
