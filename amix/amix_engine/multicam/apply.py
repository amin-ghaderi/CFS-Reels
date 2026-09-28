"""Multicam readiness and the automatic plan. The planner itself is unchanged."""
from __future__ import annotations

import hashlib
import json

from amix.amix_engine.adapters.vision.resolver import vision_model_status
from amix.amix_engine.domain.types import Word
from amix.amix_engine.layout import layout_fingerprint, protected_fingerprint
from amix.amix_engine.multicam.planner import PlannerConfig, plan_shots
from amix.amix_engine.storage.kinds import DIARIZATION, OVERLAP, PARTICIPANT_ASSIGNMENT, SHOT_PLAN, TURNS
from amix.amix_engine.storage.project import ProjectStore
from amix.amix_engine.time.clock import TimeRange

PLAN_PROFILE = "amix.multicam.plan.v1"


class PlanRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def multicam_readiness(store: ProjectStore, asset_id: str) -> dict:
    store.get_media(asset_id)
    transcript = store.active_transcript(asset_id)
    assignment_id = store.get_active_run_id(asset_id, PARTICIPANT_ASSIGNMENT)
    turn_id = store.get_active_run_id(asset_id, TURNS)
    overlap_id = store.get_active_run_id(asset_id, OVERLAP)
    plan_id = store.get_active_run_id(asset_id, SHOT_PLAN)
    turns_ready = False
    if transcript is not None and assignment_id is not None and turn_id is not None:
        assignment_deps = store.run_dependencies(assignment_id)
        turn_deps = store.run_dependencies(turn_id)
        turns_ready = transcript.analysis_run_id in assignment_deps and assignment_id in turn_deps
    layout_rows = store.list_layout_records(asset_id)
    layout_id = layout_fingerprint(layout_rows)
    protected = store.load_protected_regions(asset_id)
    protected_id = protected_fingerprint([(region.span.start_us, region.span.end_us) for region in protected])
    layout_ready = len({row["participant_id"] for row in layout_rows}) >= 2
    overlap_ready = overlap_id is not None
    overlap_stale = False
    if overlap_id is not None:
        recorded = store.analysis_record(overlap_id)["config"].get("layout_fingerprint")
        overlap_stale = recorded != layout_id
    usable_overlap = overlap_id if overlap_ready and not overlap_stale else None
    plan_window = _covered_plan_range(store, turn_id if turns_ready else None, usable_overlap)
    inputs_ready = plan_window is not None and layout_ready
    plan_stale = False
    if plan_id is not None:
        plan_stale = _plan_is_stale(store, plan_id, turn_id, overlap_id, layout_id, protected_id)
    blocking = _blocking(
        turns_ready=turns_ready,
        overlap_ready=overlap_ready,
        overlap_stale=overlap_stale,
        layout_ready=layout_ready,
        inputs_ready=inputs_ready,
        has_transcript=transcript is not None,
    )
    return {
        "turns_ready": turns_ready,
        "overlap_ready": overlap_ready and not overlap_stale,
        "overlap_stale": overlap_stale,
        "layout_ready": layout_ready,
        "plan_ready": inputs_ready,
        "plan_present": plan_id is not None,
        "plan_stale": plan_stale,
        "blocking_reason": blocking,
        "turn_run_id": turn_id,
        "overlap_run_id": overlap_id,
        "shot_plan_run_id": plan_id,
        "layout_fingerprint": layout_id,
        "protected_fingerprint": protected_id,
        "plan_start_us": None if plan_window is None else plan_window.start_us,
        "plan_end_us": None if plan_window is None else plan_window.end_us,
        "diarization_run_id": store.get_active_run_id(asset_id, DIARIZATION),
        "transcript_run_id": None if transcript is None else transcript.analysis_run_id,
        "vision_state": vision_model_status().state,
    }


def build_automatic_plan(store: ProjectStore, asset_id: str) -> str:
    ready = multicam_readiness(store, asset_id)
    if not ready["turns_ready"]:
        raise PlanRejected("turns_required", "Speaker turns are not ready for this media.")
    if ready["overlap_stale"]:
        raise PlanRejected("overlap_stale", "Overlap analysis is out of date for the current layout.")
    if not ready["overlap_ready"]:
        raise PlanRejected("overlap_required", "Overlap analysis is not ready for this media.")
    if not ready["layout_ready"]:
        raise PlanRejected("insufficient_layout", "At least two participant regions are required.")
    if ready["plan_start_us"] is None or ready["plan_end_us"] is None:
        raise PlanRejected("analysis_not_covering", "Turns and overlap do not cover a shared plan range.")
    window = TimeRange(ready["plan_start_us"], ready["plan_end_us"])
    turn_id = ready["turn_run_id"]
    overlap_id = ready["overlap_run_id"]
    turns = [
        turn for turn in store.load_turns(turn_id)
        if turn.end_us > window.start_us and turn.start_us < window.end_us
    ]
    words = [
        Word(word.word_id, word.start_us, word.end_us, word.machine_text)
        for word in store.load_words(ready["transcript_run_id"])
        if word.end_us > window.start_us and word.start_us < window.end_us
    ]
    overlaps = [
        region for region in store.load_overlaps(overlap_id)
        if region.end_us > window.start_us and region.start_us < window.end_us
    ]
    bindings = store.load_layout_bindings(asset_id)
    protected = store.load_protected_regions(asset_id)
    plan = plan_shots(window, turns, words, overlaps, bindings, protected, PlannerConfig())
    fingerprint = hashlib.sha256(
        json.dumps({
            "turns": turn_id,
            "overlap": overlap_id,
            "layout": ready["layout_fingerprint"],
            "protected": ready["protected_fingerprint"],
            "start_us": window.start_us,
            "end_us": window.end_us,
            "profile": PLAN_PROFILE,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    config = {
        "profile_id": PLAN_PROFILE,
        "turn_run_id": turn_id,
        "overlap_run_id": overlap_id,
        "transcript_run_id": ready["transcript_run_id"],
        "layout_fingerprint": ready["layout_fingerprint"],
        "protected_fingerprint": ready["protected_fingerprint"],
        "plan_start_us": window.start_us,
        "plan_end_us": window.end_us,
        "reaction_shots": False,
    }
    return store.publish_shot_plan(
        asset_id=asset_id,
        plan=plan,
        depends_on=[turn_id, overlap_id],
        algorithm_id=PLAN_PROFILE,
        algorithm_version="1",
        fingerprint=fingerprint,
        config=config,
    )


def _covered_plan_range(store: ProjectStore, turn_id: str | None, overlap_id: str | None) -> TimeRange | None:
    if turn_id is None or overlap_id is None:
        return None
    turn_start, turn_end = store.run_window(turn_id)
    overlap_start, overlap_end = store.run_window(overlap_id)
    if None in {turn_start, turn_end, overlap_start, overlap_end}:
        return None
    overlap = TimeRange(overlap_start, overlap_end)
    if turn_start <= overlap.start_us and turn_end >= overlap.end_us:
        return overlap
    return None


def _plan_is_stale(store, plan_id, turn_id, overlap_id, layout_id, protected_id) -> bool:
    record = store.analysis_record(plan_id)
    config = record["config"]
    deps = set(store.run_dependencies(plan_id))
    if turn_id not in deps or overlap_id not in deps:
        return True
    if config.get("layout_fingerprint") != layout_id:
        return True
    if config.get("protected_fingerprint") != protected_id:
        return True
    return False


def _blocking(*, turns_ready, overlap_ready, overlap_stale, layout_ready, inputs_ready, has_transcript) -> str | None:
    if not has_transcript:
        return "transcript_required"
    if not turns_ready:
        return "turns_required"
    if not layout_ready:
        return "insufficient_layout"
    if overlap_stale:
        return "overlap_stale"
    if not overlap_ready:
        return "overlap_required"
    if not inputs_ready:
        return "analysis_not_covering"
    return None
