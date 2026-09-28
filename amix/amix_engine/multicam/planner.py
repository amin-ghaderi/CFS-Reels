"""Automatic 16:9 shot plan.

Behavior migrated from:
legacy/data/tmp_cfs03_preview/build_offline_49_59_diarized_turns_v1_plan.py
    ::build_floors, floors_to_shots
legacy/data/tmp_cfs03_preview/build_offline_49_59_diarized_overlap_v1_plan.py
    ::prepare_overlaps, overlay

Hand-authored reaction inserts in those scripts are not part of this planner.
Protected master spans are applied last and override every automatic shot.
A full shot is emitted only where that participant has a layout binding.
"""
from __future__ import annotations

from dataclasses import dataclass

from amix.amix_engine.domain.types import (
    LayoutBinding,
    OverlapRegion,
    Presentation,
    ProtectedRegion,
    Shot,
    ShotPlan,
    Turn,
    Word,
)
from amix.amix_engine.time.clock import TimeRange


@dataclass(frozen=True)
class PlannerConfig:
    min_floor_us: int = 2_000_000
    min_floor_words: int = 4
    long_wordless_us: int = 12_000_000
    close_sliver_us: int = 20_000
    snap_us: int = 400_000
    overlap_min_us: int = 1_000_000
    overlap_merge_gap_us: int = 750_000
    cut_sliver_us: int = 30_000
    merge_gap_us: int = 50_000


@dataclass(frozen=True)
class _Floor:
    start_us: int
    end_us: int
    participant_id: object
    kind: str
    turn_ids: tuple[str, ...]


def plan_shots(
    window: TimeRange,
    turns: list[Turn],
    words: list[Word],
    overlaps: list[OverlapRegion],
    bindings: list[LayoutBinding],
    protected: list[ProtectedRegion],
    config: PlannerConfig | None = None,
) -> ShotPlan:
    cfg = config or PlannerConfig()
    floors = _build_floors(window, turns, words, cfg)
    shots = _floors_to_shots(floors, bindings)
    prepared = _prepare_overlaps(overlaps, words, window, cfg)
    shots = _overlay(shots, prepared, window, cfg)
    shots = _merge(shots, cfg)
    shots = _apply_protected(shots, protected, window)
    return ShotPlan(span=window, shots=tuple(shots))


def _meaningful(turn: Turn, config: PlannerConfig) -> bool:
    if turn.participant_id is None:
        return False
    return (
        turn.end_us - turn.start_us >= config.min_floor_us
        and turn.word_count >= config.min_floor_words
    )


def _wordless_gaps(
    start_us: int,
    end_us: int,
    words: list[Word],
    long_us: int,
) -> list[tuple[int, int]]:
    cursor = start_us
    gaps: list[tuple[int, int]] = []
    for word in words:
        if word.end_us <= start_us or word.start_us >= end_us:
            continue
        if word.start_us - cursor >= long_us:
            gaps.append((cursor, word.start_us))
        cursor = max(cursor, word.end_us)
    if end_us - cursor >= long_us:
        gaps.append((cursor, end_us))
    return gaps


def _build_floors(
    window: TimeRange,
    turns: list[Turn],
    words: list[Word],
    config: PlannerConfig,
) -> list[_Floor]:
    kept = [turn for turn in turns if _meaningful(turn, config)]
    if not kept:
        return [_Floor(window.start_us, window.end_us, None, "long_unknown", ())]
    floors: list[_Floor] = []
    cursor = window.start_us
    speaker = kept[0].participant_id
    ids: list[str] = [kept[0].turn_id]

    def close(at: int) -> None:
        nonlocal cursor, ids
        if at - cursor >= config.close_sliver_us:
            floors.append(_Floor(cursor, at, speaker, "floor", tuple(ids)))
        cursor = at
        ids = []

    for prev, turn in zip(kept, kept[1:]):
        gaps = _wordless_gaps(prev.end_us, turn.start_us, words, config.long_wordless_us)
        if turn.participant_id == speaker and not gaps:
            ids.append(turn.turn_id)
            continue
        if gaps:
            gap_start, gap_end = gaps[0]
            if prev.turn_id not in ids:
                ids.append(prev.turn_id)
            close(gap_start)
            floors.append(_Floor(gap_start, gap_end, None, "long_unknown", ()))
            cursor = gap_end
            if turn.participant_id != speaker:
                if turn.start_us - cursor >= config.close_sliver_us:
                    floors.append(_Floor(cursor, turn.start_us, speaker, "floor", ()))
                cursor = turn.start_us
                speaker = turn.participant_id
                ids = [turn.turn_id]
            else:
                speaker = turn.participant_id
                ids = [turn.turn_id]
            continue
        close(turn.start_us)
        speaker = turn.participant_id
        ids = [turn.turn_id]
    close(window.end_us)
    return floors


def _binding_covers(
    bindings: list[LayoutBinding],
    participant,
    start_us: int,
    end_us: int,
) -> bool:
    return any(
        binding.participant_id == participant and binding.covers(start_us, end_us)
        for binding in bindings
    )


def _shot(
    start_us: int,
    end_us: int,
    presentation: Presentation,
    participant,
    floor,
    reason: str,
) -> Shot:
    return Shot(
        start_us=start_us,
        end_us=end_us,
        presentation=presentation,
        participant_id=participant if presentation is Presentation.FULL else None,
        floor_participant_id=floor,
        reason=reason,
    )


def _floors_to_shots(floors: list[_Floor], bindings: list[LayoutBinding]) -> list[Shot]:
    shots: list[Shot] = []
    for floor in floors:
        if floor.kind == "long_unknown" or floor.participant_id is None:
            shots.append(_shot(
                floor.start_us, floor.end_us,
                Presentation.UNTOUCHED_WIDE, None, None, "unknown_hold",
            ))
            continue
        if _binding_covers(bindings, floor.participant_id, floor.start_us, floor.end_us):
            shots.append(_shot(
                floor.start_us, floor.end_us,
                Presentation.FULL, floor.participant_id, floor.participant_id, "active_speaker",
            ))
        else:
            shots.append(_shot(
                floor.start_us, floor.end_us,
                Presentation.UNTOUCHED_WIDE, None, floor.participant_id, "unbound",
            ))
    return shots


def _snap_edge(t_us: int, words: list[Word], *, toward: str, snap_us: int) -> int:
    for word in words:
        if word.start_us <= t_us <= word.end_us:
            if toward == "start" and 0 <= t_us - word.start_us <= snap_us:
                return word.start_us
            if toward == "end" and 0 <= word.end_us - t_us <= snap_us:
                return word.end_us
            return t_us
    return t_us


def _prepare_overlaps(
    overlaps: list[OverlapRegion],
    words: list[Word],
    window: TimeRange,
    config: PlannerConfig,
) -> list[tuple[int, int, tuple]]:
    prepared = []
    for region in overlaps:
        start = max(window.start_us, _snap_edge(region.start_us, words, toward="start", snap_us=config.snap_us))
        end = min(window.end_us, _snap_edge(region.end_us, words, toward="end", snap_us=config.snap_us))
        if end - start < config.overlap_min_us:
            continue
        prepared.append((start, end, region.participant_ids))
    prepared.sort(key=lambda row: row[0])
    merged: list[tuple[int, int, tuple]] = []
    for start, end, names in prepared:
        if merged and start - merged[-1][1] <= config.overlap_merge_gap_us:
            prev_start, prev_end, prev_names = merged[-1]
            combined = list(prev_names)
            for name in names:
                if name not in combined:
                    combined.append(name)
            merged[-1] = (prev_start, max(prev_end, end), tuple(combined))
            continue
        merged.append((start, end, names))
    return merged


def _host_at(shots: list[Shot], mid: int, window_end: int) -> Shot | None:
    for shot in shots:
        if shot.start_us <= mid < shot.end_us:
            return shot
        if abs(mid - window_end) <= 1_000 and shot.end_us == window_end:
            return shot
    return None


def _overlay(
    shots: list[Shot],
    overlaps: list[tuple[int, int, tuple]],
    window: TimeRange,
    config: PlannerConfig,
) -> list[Shot]:
    cuts = {window.start_us, window.end_us}
    for shot in shots:
        cuts.add(shot.start_us)
        cuts.add(shot.end_us)
    for start, end, _names in overlaps:
        cuts.add(start)
        cuts.add(end)
    bounds = sorted(cuts)
    out: list[Shot] = []
    for left, right in zip(bounds, bounds[1:]):
        if right - left < config.cut_sliver_us:
            continue
        mid = (left + right) // 2
        host = _host_at(shots, mid, window.end_us)
        if host is None:
            continue
        row = next((item for item in overlaps if item[0] <= mid < item[1]), None)
        if row is None:
            out.append(_shot(
                left, right, host.presentation, host.participant_id,
                host.floor_participant_id, host.reason,
            ))
            continue
        out.append(_shot(
            left, right, Presentation.UNTOUCHED_WIDE, None,
            host.floor_participant_id, "overlap",
        ))
    return out


def _merge(shots: list[Shot], config: PlannerConfig) -> list[Shot]:
    merged: list[Shot] = []
    for shot in shots:
        previous = merged[-1] if merged else None
        if previous is None:
            merged.append(shot)
            continue
        gap = shot.start_us - previous.end_us
        both_wide = (
            previous.presentation is Presentation.UNTOUCHED_WIDE
            and shot.presentation is Presentation.UNTOUCHED_WIDE
            and abs(gap) < config.merge_gap_us
        )
        same = (
            previous.presentation is shot.presentation
            and previous.reason == shot.reason
            and previous.participant_id == shot.participant_id
            and previous.floor_participant_id == shot.floor_participant_id
            and abs(gap) < config.merge_gap_us
        )
        if not same and not both_wide:
            merged.append(shot)
            continue
        merged[-1] = _shot(
            previous.start_us, shot.end_us,
            previous.presentation, previous.participant_id,
            previous.floor_participant_id, previous.reason,
        )
    return merged


def _apply_protected(
    shots: list[Shot],
    protected: list[ProtectedRegion],
    window: TimeRange,
) -> list[Shot]:
    if not protected:
        return shots
    spans = []
    for region in protected:
        clipped = region.span.intersection(window)
        if clipped is not None and clipped.duration_us > 0:
            spans.append(clipped)
    if not spans:
        return shots
    out: list[Shot] = []
    for shot in shots:
        pieces = [TimeRange(shot.start_us, shot.end_us)]
        for span in spans:
            nxt = []
            for piece in pieces:
                hit = piece.intersection(span)
                if hit is None:
                    nxt.append(piece)
                    continue
                if piece.start_us < hit.start_us:
                    nxt.append(TimeRange(piece.start_us, hit.start_us))
                nxt.append(TimeRange(hit.start_us, hit.end_us))
                if hit.end_us < piece.end_us:
                    nxt.append(TimeRange(hit.end_us, piece.end_us))
            pieces = nxt
        for piece in pieces:
            locked = any(span.start_us <= piece.start_us and piece.end_us <= span.end_us for span in spans)
            if locked:
                out.append(_shot(
                    piece.start_us, piece.end_us,
                    Presentation.PROTECTED_MASTER, None, shot.floor_participant_id, "protected",
                ))
            else:
                out.append(_shot(
                    piece.start_us, piece.end_us,
                    shot.presentation, shot.participant_id,
                    shot.floor_participant_id, shot.reason,
                ))
    return _merge(out, PlannerConfig())
