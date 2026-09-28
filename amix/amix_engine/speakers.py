"""Cluster review and manual mapping. Assignment uses the Phase 2 functions."""
from __future__ import annotations

import hashlib
import json

from amix.amix_engine.analysis.assign import assign_words
from amix.amix_engine.analysis.turns import build_turns
from amix.amix_engine.domain.types import DiarizationSegment, ParticipantId, Word
from amix.amix_engine.storage.errors import MediaMissing
from amix.amix_engine.storage.kinds import DIARIZATION, PARTICIPANT_ASSIGNMENT, TURNS
from amix.amix_engine.storage.project import ProjectStore
from amix.amix_engine.time.clock import TimeRange

SAMPLE_LIMIT = 3
ASSIGN_ALGORITHM = "amix.assign"
TURN_ALGORITHM = "amix.turns"


class SpeakerMapRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def representative_ranges(ranges: list[tuple[int, int]], limit: int = SAMPLE_LIMIT) -> list[tuple[int, int]]:
    """Longer examples spread across the run. There is no confidence score."""
    if not ranges or limit < 1:
        return []
    ordered = sorted(ranges, key=lambda item: (item[0], item[1]))
    span_start = ordered[0][0]
    span_end = max(item[1] for item in ordered)
    span = max(1, span_end - span_start)
    chosen: list[tuple[int, int]] = []
    used: set[tuple[int, int]] = set()
    for band in range(limit):
        band_start = span_start + span * band // limit
        in_band = [
            item for item in ordered
            if item[0] >= band_start and (band == limit - 1 or item[0] < span_start + span * (band + 1) // limit)
        ]
        if not in_band:
            continue
        best = max(in_band, key=lambda item: (item[1] - item[0], -item[0]))
        if best in used:
            continue
        used.add(best)
        chosen.append(best)
    return chosen


def summarize_clusters(segments: list[DiarizationSegment]) -> list[dict]:
    grouped: dict[str, list[DiarizationSegment]] = {}
    for segment in segments:
        grouped.setdefault(segment.cluster_id, []).append(segment)
    summaries = []
    for key in sorted(grouped):
        rows = grouped[key]
        voiced = sum(row.end_us - row.start_us for row in rows)
        samples = representative_ranges([(row.start_us, row.end_us) for row in rows])
        summaries.append({
            "cluster_key": key,
            "segment_count": len(rows),
            "voiced_us": voiced,
            "samples": [{"start_us": start, "end_us": end} for start, end in samples],
        })
    return summaries


def apply_cluster_map(
    store: ProjectStore,
    asset_id: str,
    diarization_run_id: str,
    mapping: dict[str, str | None],
) -> tuple[str, str]:
    """Create assignment and turn runs, then switch both active pointers together."""
    transcript = store.active_transcript(asset_id)
    if transcript is None:
        raise SpeakerMapRejected("no_active_transcript", "No transcript is available for this media yet.")
    record = store.analysis_record(diarization_run_id)
    if record["kind"] != DIARIZATION:
        raise SpeakerMapRejected("unknown_diarization", "That speaker analysis is not available.")
    active = store.get_active_run_id(asset_id, DIARIZATION)
    if active != diarization_run_id:
        raise SpeakerMapRejected("unknown_diarization", "That speaker analysis is not available.")
    segments = store.load_diarization_segments(diarization_run_id)
    keys = sorted({segment.cluster_id for segment in segments})
    if sorted(mapping) != keys:
        raise SpeakerMapRejected("incomplete_cluster_map", "Map every cluster, including Unknown.")
    participants = {item[0] for item in store.list_participants()}
    cluster_map: dict[str, ParticipantId | None] = {}
    stored_map: dict[str, str | None] = {}
    for key in keys:
        participant_id = mapping[key]
        if participant_id is None:
            cluster_map[key] = None
            stored_map[key] = None
            continue
        if not isinstance(participant_id, str) or participant_id not in participants:
            raise SpeakerMapRejected("unknown_participant", "Choose a participant in this project.")
        cluster_map[key] = ParticipantId(participant_id)
        stored_map[key] = participant_id
    stored_words = store.load_words(transcript.analysis_run_id)
    words = [Word(word.word_id, word.start_us, word.end_us, word.machine_text) for word in stored_words]
    assignments = assign_words(words, segments, cluster_map)
    turns = build_turns(words, assignments)
    window_start, window_end = store.run_window(diarization_run_id)
    window = None if window_start is None or window_end is None else TimeRange(window_start, window_end)
    payload = json.dumps(stored_map, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(
        f"{transcript.analysis_run_id}:{diarization_run_id}:{payload}".encode("utf-8")
    ).hexdigest()
    config = {
        "cluster_map": stored_map,
        "transcript_run_id": transcript.analysis_run_id,
        "diarization_run_id": diarization_run_id,
        "unknown_allowed": True,
        "duplicate_participants_allowed": True,
    }
    return store.publish_assignment_and_turns(
        asset_id=asset_id,
        assignments=assignments,
        turns=turns,
        transcript_run_id=transcript.analysis_run_id,
        diarization_run_id=diarization_run_id,
        fingerprint=fingerprint,
        window=window,
        assignment_config=config,
        turn_config={"assignment_algorithm": ASSIGN_ALGORITHM},
        assignment_algorithm=ASSIGN_ALGORITHM,
        turn_algorithm=TURN_ALGORITHM,
    )


def speaker_status(store: ProjectStore, asset_id: str) -> dict:
    participants = store.list_participants()
    transcript = store.active_transcript(asset_id)
    diarization_id = store.get_active_run_id(asset_id, DIARIZATION)
    assignment_id = store.get_active_run_id(asset_id, PARTICIPANT_ASSIGNMENT)
    turn_id = store.get_active_run_id(asset_id, TURNS)
    compatible = False
    if transcript is not None and assignment_id is not None:
        compatible = transcript.analysis_run_id in store.run_dependencies(assignment_id)
    turns_match = False
    if compatible and turn_id is not None and assignment_id is not None:
        turns_match = assignment_id in store.run_dependencies(turn_id)
    source_present = True
    try:
        store.require_media(asset_id)
    except MediaMissing:
        source_present = False
    clusters = []
    if diarization_id is not None:
        clusters = summarize_clusters(store.load_diarization_segments(diarization_id))
    previous_map = None
    if assignment_id is not None:
        config = store.analysis_record(assignment_id)["config"]
        raw = config.get("cluster_map") if isinstance(config, dict) else None
        if isinstance(raw, dict):
            previous_map = raw
    state = _state(
        participant_count=len(participants),
        has_transcript=transcript is not None,
        source_present=source_present,
        has_diarization=diarization_id is not None,
        assignment_exists=assignment_id is not None,
        compatible=compatible,
        turns_match=turns_match,
    )
    return {
        "state": state,
        "participant_count": len(participants),
        "transcript_run_id": None if transcript is None else transcript.analysis_run_id,
        "diarization_run_id": diarization_id,
        "assignment_run_id": assignment_id,
        "assignment_compatible": compatible,
        "turns_run_id": turn_id,
        "turns_match_assignment": turns_match,
        "source_present": source_present,
        "clusters": clusters,
        "previous_map": previous_map,
        "profile_id": "amix.diarize.mfcc_kmeans.v1",
        "cluster_count": 3,
    }


def _state(
    *,
    participant_count: int,
    has_transcript: bool,
    source_present: bool,
    has_diarization: bool,
    assignment_exists: bool,
    compatible: bool,
    turns_match: bool,
) -> str:
    if participant_count < 1:
        return "no_participants"
    if not has_transcript:
        return "no_transcript"
    if compatible and turns_match:
        return "applied"
    if assignment_exists and not compatible:
        return "stale"
    if has_diarization:
        return "clusters_ready"
    if not source_present:
        return "source_missing"
    return "ready"
