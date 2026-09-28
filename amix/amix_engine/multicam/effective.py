"""Effective shots. Automatic rows stay stored as they were generated."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from amix.amix_engine.domain.types import LayoutBinding, ParticipantId
from amix.amix_engine.multicam.framing import covering_segments
from amix.amix_engine.storage.project import ProjectStore

PROTECTED = "protected_master"


class OverrideRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class EffectiveShot:
    shot_id: str
    start_us: int
    end_us: int
    reason: str
    automatic_presentation: str
    automatic_participant_id: str | None
    override_decision: str
    override_participant_id: str | None
    effective_presentation: str
    effective_participant_id: str | None
    locked: bool


def resolve_effective(records: list[dict], overrides: list[dict]) -> list[EffectiveShot]:
    chosen = {row["shot_id"]: row for row in overrides}
    resolved: list[EffectiveShot] = []
    for record in records:
        locked = record["presentation"] == PROTECTED
        override = chosen.get(record["shot_id"])
        decision = "auto"
        override_participant = None
        presentation = record["presentation"]
        participant = record["participant_id"]
        if override is not None and not locked:
            decision = override["decision"]
            override_participant = override["participant_id"]
            if decision == "wide":
                presentation = "untouched_wide"
                participant = None
            elif decision == "full":
                presentation = "full"
                participant = override_participant
        resolved.append(EffectiveShot(
            shot_id=record["shot_id"],
            start_us=int(record["start_us"]),
            end_us=int(record["end_us"]),
            reason=record["reason"],
            automatic_presentation=record["presentation"],
            automatic_participant_id=record["participant_id"],
            override_decision=decision,
            override_participant_id=override_participant,
            effective_presentation=presentation,
            effective_participant_id=participant,
            locked=locked,
        ))
    return resolved


def override_fingerprint(overrides: list[dict]) -> str:
    payload = [
        {
            "shot_id": row["shot_id"],
            "decision": row["decision"],
            "participant_id": row["participant_id"],
        }
        for row in sorted(overrides, key=lambda item: item["shot_id"])
    ]
    return _digest(payload)


def effective_fingerprint(shots: list[EffectiveShot]) -> str:
    payload = [
        {
            "shot_id": shot.shot_id,
            "start_us": shot.start_us,
            "end_us": shot.end_us,
            "presentation": shot.effective_presentation,
            "participant_id": shot.effective_participant_id,
            "locked": shot.locked,
        }
        for shot in shots
    ]
    return _digest(payload)


def full_choices(bindings: list[LayoutBinding], start_us: int, end_us: int) -> list[ParticipantId]:
    people = []
    seen: set[str] = set()
    for binding in bindings:
        if binding.participant_id.value in seen:
            continue
        if covering_segments(bindings, binding.participant_id, start_us, end_us) is None:
            continue
        seen.add(binding.participant_id.value)
        people.append(binding.participant_id)
    return people


def set_shot_override(
    store: ProjectStore,
    asset_id: str,
    plan_run_id: str,
    shot_id: str,
    decision: str,
    participant_id: str | None,
) -> None:
    record = _plan_record(store, asset_id, plan_run_id)
    shots = {row["shot_id"]: row for row in store.list_shot_records(plan_run_id)}
    shot = shots.get(shot_id)
    if shot is None:
        raise OverrideRejected("unknown_shot", "That shot is not in this plan.")
    if decision == "auto":
        store.clear_shot_override(plan_run_id, shot_id)
        return
    if shot["presentation"] == PROTECTED:
        raise OverrideRejected("protected_locked", "A protected shot stays on the full program frame.")
    if decision == "wide":
        store.save_shot_override(
            asset_id=asset_id, plan_run_id=plan_run_id, shot_id=shot_id,
            decision="wide", participant_id=None,
        )
        return
    if decision != "full" or not participant_id:
        raise OverrideRejected("invalid_override", "Choose automatic, wide, or one participant.")
    known = {item[0] for item in store.list_participants()}
    if participant_id not in known:
        raise OverrideRejected("unknown_participant", "That participant is not in this project.")
    bindings = store.load_layout_bindings(asset_id)
    if covering_segments(bindings, ParticipantId(participant_id), shot["start_us"], shot["end_us"]) is None:
        raise OverrideRejected("layout_not_covering", "That participant does not cover this whole shot.")
    store.save_shot_override(
        asset_id=asset_id, plan_run_id=plan_run_id, shot_id=shot_id,
        decision="full", participant_id=participant_id,
    )
    _ = record


def describe_shots(store: ProjectStore, asset_id: str) -> dict:
    from amix.amix_engine.multicam.apply import multicam_readiness

    ready = multicam_readiness(store, asset_id)
    run_id = ready["shot_plan_run_id"]
    if run_id is None:
        return {"run_id": None, "stale": False, "start_us": None, "end_us": None, "shots": []}
    names = {participant_id: name for participant_id, name, _order in store.list_participants()}
    bindings = store.load_layout_bindings(asset_id)
    records = store.list_shot_records(run_id)
    overrides = store.list_shot_overrides(run_id)
    plan = store.load_shot_plan(run_id)
    shots = []
    for item in resolve_effective(records, overrides):
        choices = [] if item.locked else full_choices(bindings, item.start_us, item.end_us)
        shots.append({
            "shot_id": item.shot_id,
            "start_us": item.start_us,
            "end_us": item.end_us,
            "reason": item.reason,
            "presentation": item.effective_presentation,
            "participant_id": item.effective_participant_id,
            "participant_name": None if item.effective_participant_id is None else names.get(item.effective_participant_id),
            "automatic_presentation": item.automatic_presentation,
            "automatic_participant_id": item.automatic_participant_id,
            "automatic_participant_name": None if item.automatic_participant_id is None else names.get(item.automatic_participant_id),
            "override_decision": item.override_decision,
            "locked": item.locked,
            "overridden": item.override_decision != "auto",
            "full_choices": [
                {"participant_id": person.value, "display_name": names.get(person.value, person.value)}
                for person in choices
            ],
        })
    return {
        "run_id": run_id,
        "stale": ready["plan_stale"],
        "start_us": plan.span.start_us,
        "end_us": plan.span.end_us,
        "shots": shots,
    }


def _plan_record(store: ProjectStore, asset_id: str, plan_run_id: str) -> dict:
    try:
        record = store.analysis_record(plan_run_id)
    except Exception as exc:
        raise OverrideRejected("unknown_shot_plan", "That shot plan is not in this project.") from exc
    if record["kind"] != "shot_plan" or record.get("media_asset_id") != asset_id:
        raise OverrideRejected("unknown_shot_plan", "That shot plan is not in this project.")
    return record


def _digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
