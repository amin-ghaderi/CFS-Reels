"""Focused tests for assignment, turns, overlap, and the planner."""
from __future__ import annotations

import unittest

from amix.amix_engine.analysis.assign import assign_words
from amix.amix_engine.analysis.overlap import overlap_regions
from amix.amix_engine.domain.types import SpeakerAssignment
from amix.amix_engine.analysis.turns import build_turns
from amix.amix_engine.domain.types import (
    DiarizationSegment,
    LayoutBinding,
    LipActivitySeries,
    OverlapRegion,
    ParticipantId,
    Presentation,
    ProtectedRegion,
    Turn,
    Word,
)
from amix.amix_engine.multicam.planner import plan_shots
from amix.amix_engine.time.clock import TimeRange, legacy_seconds_to_us


def _us(text: str) -> int:
    return legacy_seconds_to_us(text)


A = ParticipantId("person-a")
B = ParticipantId("person-b")


def _word(index: int, start: str, end: str, text: str = "w") -> Word:
    return Word(f"W{index}", _us(start), _us(end), text)


class AssignTests(unittest.TestCase):
    def test_majority_and_tie_and_miss(self) -> None:
        words = [
            _word(1, "0.000", "1.000"),
            _word(2, "1.000", "2.000"),
            _word(3, "10.000", "10.200"),
        ]
        segments = [
            DiarizationSegment(_us("0.000"), _us("1.000"), "c1"),
            DiarizationSegment(_us("1.000"), _us("1.600"), "c1"),
            DiarizationSegment(_us("1.400"), _us("2.000"), "c2"),
        ]
        cluster_map = {"c1": A, "c2": B}
        rows = assign_words(words, segments, cluster_map)
        self.assertEqual(rows[0].participant_id, A)
        self.assertIsNone(rows[1].participant_id)
        self.assertIsNone(rows[2].participant_id)


class TurnTests(unittest.TestCase):
    def test_change_splits_and_gap_holds(self) -> None:
        words = [
            _word(1, "0.000", "0.500"),
            _word(2, "1.000", "1.200"),
            _word(3, "3.000", "3.200"),
        ]
        assigned = [
            SpeakerAssignment("W1", A),
            SpeakerAssignment("W2", A),
            SpeakerAssignment("W3", B),
        ]
        turns = build_turns(words, assigned)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].participant_id, A)
        self.assertEqual(turns[0].end_us, _us("1.200"))
        self.assertEqual(turns[1].participant_id, B)

    def test_unknown_stays_unknown(self) -> None:
        words = [_word(1, "0.000", "0.400")]
        turns = build_turns(words, [SpeakerAssignment("W1", None)])
        self.assertIsNone(turns[0].participant_id)
        self.assertEqual(turns[0].turn_id, "T0001")


class OverlapTests(unittest.TestCase):
    def test_window_must_match_series(self) -> None:
        series = LipActivitySeries(0, 125_000, (A, B), ((0.0, 0.0),), (0.0,))
        with self.assertRaises(ValueError):
            overlap_regions(series, TimeRange(0, 1_000_000))


class PlannerTests(unittest.TestCase):
    def _bindings(self, *people: ParticipantId) -> list[LayoutBinding]:
        span = TimeRange(0, 60_000_000)
        return [
            LayoutBinding(person, 0, 0, 896, 504, span)
            for person in people
        ]

    def test_protected_overrides_full_and_overlap(self) -> None:
        words = [_word(i, f"{i}.000", f"{i}.400") for i in range(8)]
        turns = [Turn("T0001", A, _us("0"), _us("8"), tuple(word.word_id for word in words))]
        overlaps = [OverlapRegion(_us("2.000"), _us("5.000"), (A, B), 0.9)]
        plan = plan_shots(
            TimeRange(0, _us("8")),
            turns,
            words,
            overlaps,
            self._bindings(A, B),
            [ProtectedRegion(TimeRange(_us("3.000"), _us("4.000")))],
        )
        protected = [shot for shot in plan.shots if shot.reason == "protected"]
        self.assertEqual(len(protected), 1)
        self.assertEqual(protected[0].presentation, Presentation.PROTECTED_MASTER)
        self.assertEqual(protected[0].start_us, _us("3.000"))
        self.assertEqual(protected[0].end_us, _us("4.000"))
        self.assertTrue(any(shot.reason == "overlap" for shot in plan.shots))
        self.assertTrue(any(shot.presentation is Presentation.FULL for shot in plan.shots))

    def test_unbound_participant_is_wide(self) -> None:
        words = [_word(i, f"{i}.000", f"{i}.400") for i in range(6)]
        turns = [Turn("T0001", A, 0, _us("6"), tuple(word.word_id for word in words))]
        plan = plan_shots(
            TimeRange(0, _us("6")),
            turns,
            words,
            [],
            [],
            [],
        )
        self.assertEqual(len(plan.shots), 1)
        self.assertEqual(plan.shots[0].presentation, Presentation.UNTOUCHED_WIDE)
        self.assertEqual(plan.shots[0].reason, "unbound")
        self.assertIsNone(plan.shots[0].participant_id)
        self.assertEqual(plan.shots[0].floor_participant_id, A)

    def test_bound_participant_is_full(self) -> None:
        words = [_word(i, f"{i}.000", f"{i}.400") for i in range(6)]
        turns = [Turn("T0001", A, 0, _us("6"), tuple(word.word_id for word in words))]
        plan = plan_shots(
            TimeRange(0, _us("6")),
            turns,
            words,
            [],
            self._bindings(A),
            [],
        )
        self.assertEqual(plan.shots[0].presentation, Presentation.FULL)
        self.assertEqual(plan.shots[0].participant_id, A)


if __name__ == "__main__":
    unittest.main()
