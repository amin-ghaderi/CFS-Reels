"""Manual editorial sequence. Source analyses are not edited here."""
from __future__ import annotations

import hashlib
import json
from amix.amix_engine.multicam.effective import describe_shots
from amix.amix_engine.storage.project import ProjectStore


class SequenceRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sequence_duration_us(clips: list[tuple[int, int]]) -> int:
    total = 0
    for start_us, end_us in clips:
        total += end_us - start_us
    return total


def source_to_sequence_us(clips: list[tuple[int, int]], source_us: int) -> int | None:
    """Sequence time of a kept source instant. Removed instants have no sequence time."""
    cursor = 0
    for start_us, end_us in clips:
        if start_us <= source_us < end_us:
            return cursor + (source_us - start_us)
        cursor += end_us - start_us
    return None


def sequence_to_source_us(clips: list[tuple[int, int]], sequence_us: int) -> int | None:
    """Source time of a sequence instant. The sequence end is outside every half-open clip."""
    if sequence_us < 0:
        return None
    cursor = 0
    for start_us, end_us in clips:
        duration = end_us - start_us
        if cursor <= sequence_us < cursor + duration:
            return start_us + (sequence_us - cursor)
        cursor += duration
    return None


def removed_ranges(
    source_start_us: int, source_end_us: int, clips: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    gaps: list[tuple[int, int]] = []
    cursor = source_start_us
    for start_us, end_us in clips:
        if start_us > cursor:
            gaps.append((cursor, start_us))
        cursor = end_us
    if cursor < source_end_us:
        gaps.append((cursor, source_end_us))
    return gaps


def sequence_fingerprint(
    source_start_us: int, source_end_us: int, clips: list[tuple[int, int]],
) -> str:
    payload = {
        "source_start_us": source_start_us,
        "source_end_us": source_end_us,
        "clips": [{"start_us": start, "end_us": end} for start, end in clips],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_clips(
    clips: list[tuple[int, int]], source_start_us: int, source_end_us: int,
) -> None:
    if source_end_us <= source_start_us:
        raise SequenceRejected("invalid_sequence", "The sequence source range is empty.")
    previous = source_start_us
    for start_us, end_us in clips:
        if start_us >= end_us:
            raise SequenceRejected("invalid_clip", "A clip range is empty.")
        if start_us < source_start_us or end_us > source_end_us:
            raise SequenceRejected("clip_out_of_range", "A clip is outside the sequence source range.")
        if start_us < previous:
            raise SequenceRejected("clip_overlap", "Clips must stay in source order without overlap.")
        previous = end_us


def create_sequence(store: ProjectStore, asset_id: str) -> dict:
    existing = store.load_editorial_sequence(asset_id)
    if existing is not None:
        return existing
    ready_start, ready_end = _plan_range(store, asset_id)
    validate_clips([(ready_start, ready_end)], ready_start, ready_end)
    store.insert_editorial_sequence(
        asset_id=asset_id,
        display_name="Edit",
        source_start_us=ready_start,
        source_end_us=ready_end,
        clips=[(ready_start, ready_end)],
    )
    loaded = store.load_editorial_sequence(asset_id)
    if loaded is None:
        raise SequenceRejected("invalid_sequence", "The sequence was not stored.")
    return loaded


def split_clip(store: ProjectStore, sequence_id: str, clip_id: str, source_time_us: int) -> dict:
    current = _owned(store, sequence_id)
    clips = _pairs(current)
    found = next((clip for clip in current["clips"] if clip["clip_id"] == clip_id), None)
    if found is None:
        raise SequenceRejected("unknown_clip", "That clip is not in this sequence.")
    if not (found["source_start_us"] < source_time_us < found["source_end_us"]):
        raise SequenceRejected("split_out_of_range", "Split inside the selected clip.")
    updated: list[tuple[int, int]] = []
    for start_us, end_us in clips:
        if start_us == found["source_start_us"] and end_us == found["source_end_us"]:
            updated.append((start_us, source_time_us))
            updated.append((source_time_us, end_us))
        else:
            updated.append((start_us, end_us))
    validate_clips(updated, current["source_start_us"], current["source_end_us"])
    store.replace_sequence_clips(sequence_id, updated)
    return store.load_editorial_sequence_by_id(sequence_id)


def remove_clip(store: ProjectStore, sequence_id: str, clip_id: str) -> dict:
    current = _owned(store, sequence_id)
    found = next((clip for clip in current["clips"] if clip["clip_id"] == clip_id), None)
    if found is None:
        raise SequenceRejected("unknown_clip", "That clip is not in this sequence.")
    updated = [
        (clip["source_start_us"], clip["source_end_us"])
        for clip in current["clips"]
        if clip["clip_id"] != clip_id
    ]
    validate_clips(updated, current["source_start_us"], current["source_end_us"])
    store.replace_sequence_clips(sequence_id, updated)
    return store.load_editorial_sequence_by_id(sequence_id)


def reset_sequence(store: ProjectStore, sequence_id: str) -> dict:
    current = _owned(store, sequence_id)
    span = (current["source_start_us"], current["source_end_us"])
    validate_clips([span], span[0], span[1])
    store.replace_sequence_clips(sequence_id, [span])
    return store.load_editorial_sequence_by_id(sequence_id)


def create_reel_draft(store: ProjectStore, asset_id: str, candidate_id: str) -> dict:
    """A new reel sequence. The primary edit and the shot plan are left alone."""
    candidate = store.load_reel_candidate(candidate_id)
    if candidate is None or candidate["media_asset_id"] != asset_id:
        raise SequenceRejected("unknown_candidate", "That reel candidate is not in this project.")
    start_us = int(candidate["start_us"])
    end_us = int(candidate["end_us"])
    name = str(candidate["title"]).strip() or "Reel"
    sequence_id = store.insert_editorial_sequence(
        asset_id=asset_id,
        display_name=name[:120],
        source_start_us=start_us,
        source_end_us=end_us,
        clips=[(start_us, end_us)],
        purpose="reel",
        origin_candidate_id=candidate_id,
    )
    return store.load_editorial_sequence_by_id(sequence_id)


def sequence_as_timeline(sequence: dict) -> dict:
    pairs = _pairs(sequence)
    return {
        "sequence_id": sequence["sequence_id"],
        "revision": sequence["revision"],
        "fingerprint": sequence_fingerprint(sequence["source_start_us"], sequence["source_end_us"], pairs),
        "source_start_us": sequence["source_start_us"],
        "source_end_us": sequence["source_end_us"],
        "duration_us": sequence_duration_us(pairs),
        "clips": [
            {**clip, "sequence_start_us": source_to_sequence_us(pairs, clip["source_start_us"])}
            for clip in sequence["clips"]
        ],
        "removed": [
            {"source_start_us": start, "source_end_us": end}
            for start, end in removed_ranges(sequence["source_start_us"], sequence["source_end_us"], pairs)
        ],
        "camera": [],
        "protected": [],
    }


def timeline_snapshot(store: ProjectStore, asset_id: str) -> dict:
    sequence = store.load_editorial_sequence(asset_id)
    described = describe_shots(store, asset_id)
    protected = [
        {"source_start_us": region.span.start_us, "source_end_us": region.span.end_us}
        for region in store.load_protected_regions(asset_id)
    ]
    if sequence is None:
        return {
            "sequence_id": None,
            "revision": None,
            "fingerprint": None,
            "source_start_us": described.get("start_us"),
            "source_end_us": described.get("end_us"),
            "duration_us": None,
            "clips": [],
            "removed": [],
            "camera": [],
            "protected": protected,
        }
    pairs = _pairs(sequence)
    return {
        "sequence_id": sequence["sequence_id"],
        "revision": sequence["revision"],
        "fingerprint": sequence_fingerprint(sequence["source_start_us"], sequence["source_end_us"], pairs),
        "source_start_us": sequence["source_start_us"],
        "source_end_us": sequence["source_end_us"],
        "duration_us": sequence_duration_us(pairs),
        "clips": [
            {
                **clip,
                "sequence_start_us": source_to_sequence_us(pairs, clip["source_start_us"]),
            }
            for clip in sequence["clips"]
        ],
        "removed": [
            {"source_start_us": start, "source_end_us": end}
            for start, end in removed_ranges(sequence["source_start_us"], sequence["source_end_us"], pairs)
        ],
        "camera": _camera_fragments(described.get("shots") or [], pairs),
        "protected": protected,
    }


def _camera_fragments(shots: list[dict], clips: list[tuple[int, int]]) -> list[dict]:
    fragments = []
    for shot in shots:
        for start_us, end_us in clips:
            left = max(int(shot["start_us"]), start_us)
            right = min(int(shot["end_us"]), end_us)
            if right <= left:
                continue
            fragments.append({
                "shot_id": shot["shot_id"],
                "source_start_us": left,
                "source_end_us": right,
                "presentation": shot["presentation"],
                "participant_name": shot.get("participant_name"),
                "locked": bool(shot.get("locked")),
            })
    return fragments


def _plan_range(store: ProjectStore, asset_id: str) -> tuple[int, int]:
    from amix.amix_engine.multicam.apply import multicam_readiness

    ready = multicam_readiness(store, asset_id)
    if not ready["shot_plan_run_id"] or ready["plan_stale"]:
        raise SequenceRejected("plan_required", "Build a current shot plan before creating an edit.")
    plan = store.load_shot_plan(ready["shot_plan_run_id"])
    return plan.span.start_us, plan.span.end_us


def _owned(store: ProjectStore, sequence_id: str) -> dict:
    try:
        return store.load_editorial_sequence_by_id(sequence_id)
    except Exception as exc:
        raise SequenceRejected("unknown_sequence", "That sequence is not in this project.") from exc


def _pairs(sequence: dict) -> list[tuple[int, int]]:
    return [(clip["source_start_us"], clip["source_end_us"]) for clip in sequence["clips"]]
