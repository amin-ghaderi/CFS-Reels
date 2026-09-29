"""Turn-anchor validation. Timestamps from a model are ignored."""
from __future__ import annotations

from pydantic import ValidationError

from amix.amix_engine.semantic.input import SemanticTurn
from amix.amix_engine.semantic.tasks import MapDraft


def parse_draft(payload: object) -> tuple[list[dict] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "The model response was not a JSON object."
    try:
        draft = MapDraft.model_validate(payload)
    except ValidationError:
        return None, "The model response did not match the conversation schema."
    return [item.model_dump() for item in draft.threads], None


def coverage_error(turn_ids: list[str], threads: list[dict]) -> str | None:
    """Require every turn exactly once, in order. A gap or overlap is invalid."""
    if not turn_ids:
        return "There are no turns to map."
    index = {turn_id: position for position, turn_id in enumerate(turn_ids)}
    cursor = 0
    for thread in threads:
        start = thread["start_turn_id"]
        end = thread["end_turn_id"]
        if start not in index or end not in index:
            return "A thread uses a turn id that is not in this conversation."
        if index[end] < index[start]:
            return "A thread reverses source order."
        if index[start] != cursor:
            if index[start] < cursor:
                return "Threads overlap or repeat a turn."
            return "The map leaves a gap between threads."
        cursor = index[end] + 1
    if cursor != len(turn_ids):
        return "The map does not cover the whole conversation."
    return None


def resolve_threads(turns: tuple[SemanticTurn, ...] | list[SemanticTurn], threads: list[dict]) -> list[dict]:
    """Expand anchors to source times. Model timestamp fields are not read."""
    by_id = {turn.turn_id: turn for turn in turns}
    order = {turn.turn_id: index for index, turn in enumerate(turns)}
    resolved = []
    for thread in threads:
        start = by_id[thread["start_turn_id"]]
        end = by_id[thread["end_turn_id"]]
        if order[end.turn_id] < order[start.turn_id]:
            raise ValueError("reversed thread")
        resolved.append({
            "first_turn_id": start.turn_id,
            "last_turn_id": end.turn_id,
            "first_word_id": start.first_word_id,
            "last_word_id": end.last_word_id,
            "title": thread["title"].strip(),
            "summary": thread["summary"].strip(),
            "topic": None if not thread.get("topic") else str(thread["topic"]).strip(),
            "start_us": start.start_us,
            "end_us": end.end_us,
        })
    return resolved
