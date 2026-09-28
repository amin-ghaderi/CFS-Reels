"""Overlap regions from precomputed lip and audio activity.

Behavior migrated from:
legacy/reels_factory/cfs_overlap.py::overlaps_from_activity

No video decode. Thresholds are the ones that produced the accepted CFS03
10-minute regions, including the 5.5 weaker-mouth floor and the 2.5 s minimum.
The activity series is the analyzed span: its percentile gate is not reusable
for a different window.
"""
from __future__ import annotations

import math

from amix.amix_engine.domain.types import LipActivitySeries, OverlapRegion
from amix.amix_engine.time.clock import TimeRange, legacy_seconds_to_us

SAMPLE_FPS = 8
WINDOW_S = 1.25
STEP_S = 0.25
SIMULTANEOUS_S = 0.75
MIN_WINDOWS = 2
MERGE_GAP_S = 0.75
LIP_ON = 4.2
WEAKER_MIN = 5.5
MIN_REGION_S = 2.5


def _percentile_linear(values: list[float], q: float) -> float:
    """NumPy's default linear percentile, so the audio gate matches legacy."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (q / 100.0)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _round_seconds(seconds: float) -> float:
    return round(seconds, 3)


def overlap_regions(
    series: LipActivitySeries,
    window: TimeRange,
) -> list[OverlapRegion]:
    """Build regions for ``window``.

    ``window`` must be the span the series was measured on. Passing a different
    span is rejected rather than silently recomputing a gate on a slice.
    """
    if series.origin_us != window.start_us:
        raise ValueError("activity origin is not the analysis window start")
    if not series.scores:
        return []
    covered = series.origin_us + len(series.scores) * series.sample_period_us
    if covered != window.end_us:
        raise ValueError("activity length is not the analysis window")

    positive = [value for value in series.audio_rms if value > 0]
    audio_gate = _percentile_linear(positive, 25.0) if positive else 0.0
    hits = _window_hits(series, audio_gate)
    return _regions_from_hits(series, hits)


def _window_hits(series: LipActivitySeries, audio_gate: float) -> list[dict]:
    scores = series.scores
    audio = series.audio_rms
    count = len(scores)
    win = max(2, int(round(WINDOW_S * SAMPLE_FPS)))
    step = max(1, int(round(STEP_S * SAMPLE_FPS)))
    need = max(2, int(round(SIMULTANEOUS_S * SAMPLE_FPS)))
    hits: list[dict] = []
    for start in range(0, max(1, count - win + 1), step):
        part = scores[start:start + win]
        if len(part) < win // 2:
            break
        on = [[value >= LIP_ON for value in row] for row in part]
        simultaneous = [sum(frame) >= 2 for frame in on]
        if sum(simultaneous) < need:
            continue
        if _median(list(audio[start:start + len(part)])) < audio_gate:
            continue
        active: list[int] = []
        width = len(series.participant_ids)
        for column in range(width):
            both = sum(1 for frame_i, frame_on in enumerate(on) if frame_on[column] and simultaneous[frame_i])
            if both >= need:
                active.append(column)
        if len(active) < 2:
            continue
        hits.append({"i0": start, "i1": start + len(part), "columns": active})
    return hits


def _frame_seconds(series: LipActivitySeries, index: int) -> float:
    # Same grid as legacy ``origin + index / SAMPLE_FPS`` for an 8 Hz series
    # whose origin is a whole second. Period is exact in microseconds.
    return (series.origin_us + index * series.sample_period_us) / 1_000_000


def _regions_from_hits(series: LipActivitySeries, hits: list[dict]) -> list[OverlapRegion]:
    if not hits:
        return []
    groups: list[list[dict]] = [[hits[0]]]
    for hit in hits[1:]:
        previous = groups[-1][-1]
        gap_s = (hit["i0"] - previous["i0"]) / SAMPLE_FPS
        if gap_s <= STEP_S * 1.6:
            groups[-1].append(hit)
        else:
            groups.append([hit])
    regions: list[dict] = []
    columns = series.participant_ids
    for group in groups:
        if len(group) < MIN_WINDOWS:
            continue
        i0 = group[0]["i0"]
        i1 = group[-1]["i1"]
        start_s = _frame_seconds(series, i0)
        end_index = min(len(series.scores) - 1, i1 - 1)
        end_s = _frame_seconds(series, end_index) + 1.0 / SAMPLE_FPS
        counts = [0 for _ in columns]
        for hit in group:
            for column in hit["columns"]:
                counts[column] += 1
        active = [
            index for index, count in enumerate(counts)
            if count >= max(1, len(group) // 2)
        ]
        if len(active) < 2:
            continue
        span = series.scores[i0:i1]
        means = []
        for index in range(len(columns)):
            means.append(sum(row[index] for row in span) / len(span) if span else 0.0)
        weaker = min(means[index] for index in active)
        if weaker < WEAKER_MIN:
            continue
        confidence = round(float(min(0.93, max(0.42, 0.42 + 0.07 * weaker))), 3)
        regions.append({
            "start_s": _round_seconds(start_s),
            "end_s": _round_seconds(end_s),
            "participants": tuple(columns[index] for index in active),
            "confidence": confidence,
        })
    return _merge_regions(regions, columns)


def _merge_regions(regions: list[dict], columns: tuple) -> list[OverlapRegion]:
    if not regions:
        return []
    rank = {participant: index for index, participant in enumerate(columns)}
    merged = [dict(regions[0])]
    for region in regions[1:]:
        previous = merged[-1]
        if region["start_s"] - previous["end_s"] <= MERGE_GAP_S:
            previous["end_s"] = region["end_s"]
            names = set(previous["participants"]) | set(region["participants"])
            # Legacy keeps the detector's column order, not first-seen order.
            previous["participants"] = tuple(sorted(names, key=lambda item: rank[item]))
            previous["confidence"] = round(max(previous["confidence"], region["confidence"]), 3)
            continue
        merged.append(dict(region))
    kept = []
    for region in merged:
        duration = round(region["end_s"] - region["start_s"], 3)
        if duration < MIN_REGION_S:
            continue
        kept.append(OverlapRegion(
            start_us=legacy_seconds_to_us(f"{region['start_s']:.3f}"),
            end_us=legacy_seconds_to_us(f"{region['end_s']:.3f}"),
            participant_ids=region["participants"],
            confidence=region["confidence"],
        ))
    return kept
