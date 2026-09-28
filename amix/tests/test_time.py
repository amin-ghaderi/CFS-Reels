"""Canonical clock and legacy import."""
from __future__ import annotations

import json
import unittest

from amix.amix_engine.time.clock import TimeError, TimeRange, legacy_seconds_to_us


class LegacyImportTests(unittest.TestCase):
    def test_required_examples(self) -> None:
        self.assertEqual(legacy_seconds_to_us("0"), 0)
        self.assertEqual(legacy_seconds_to_us("0.001"), 1_000)
        self.assertEqual(legacy_seconds_to_us("1.234"), 1_234_000)
        self.assertEqual(legacy_seconds_to_us("2960.123"), 2_960_123_000)

    def test_fewer_decimal_digits(self) -> None:
        self.assertEqual(legacy_seconds_to_us("1.2"), 1_200_000)
        self.assertEqual(legacy_seconds_to_us("1.20"), 1_200_000)
        self.assertEqual(legacy_seconds_to_us("10"), 10_000_000)

    def test_json_numbers(self) -> None:
        self.assertEqual(legacy_seconds_to_us(json.loads("0")), 0)
        self.assertEqual(legacy_seconds_to_us(json.loads("0.001")), 1_000)
        self.assertEqual(legacy_seconds_to_us(json.loads("1.234")), 1_234_000)
        self.assertEqual(legacy_seconds_to_us(json.loads("2960.123")), 2_960_123_000)
        self.assertEqual(legacy_seconds_to_us(json.loads("2960")), 2_960_000_000)

    def test_half_up_on_text(self) -> None:
        self.assertEqual(legacy_seconds_to_us("1.2345"), 1_235_000)

    def test_rejects_empty(self) -> None:
        with self.assertRaises(TimeError):
            legacy_seconds_to_us("  ")


class TimeRangeTests(unittest.TestCase):
    def test_half_open(self) -> None:
        span = TimeRange(0, 1_000)
        self.assertTrue(span.contains(0))
        self.assertFalse(span.contains(1_000))
        self.assertEqual(span.duration_us, 1_000)

    def test_overlap(self) -> None:
        left = TimeRange(0, 1_500)
        right = TimeRange(1_000, 2_000)
        self.assertTrue(left.intersects(right))
        self.assertEqual(left.overlap_us(right), 500)
        self.assertEqual(left.intersection(right), TimeRange(1_000, 1_500))
        self.assertFalse(left.intersects(TimeRange(1_500, 2_000)))

    def test_window_is_not_rebased(self) -> None:
        start = legacy_seconds_to_us("2960")
        duration = legacy_seconds_to_us("600")
        window = TimeRange(start, start + duration)
        self.assertEqual(window.start_us, 2_960_000_000)
        self.assertEqual(window.end_us, 3_560_000_000)
        self.assertNotEqual(window.start_us, 0)


if __name__ == "__main__":
    unittest.main()
