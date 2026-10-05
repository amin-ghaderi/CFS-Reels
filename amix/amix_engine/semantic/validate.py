"""Turn-anchor validation. Timestamps from a model are ignored."""
from __future__ import annotations

from pydantic import ValidationError

from amix.amix_engine.semantic.input import SemanticTurn
from amix.amix_engine.semantic.tasks import MapDraft


def threads_from_assignments(units: list[dict], payload: object, *, group_limit: int = 4) -> tuple[list[dict] | None, str | None]:
    """Expand a fixed-length assignment array into ordered, non-overlapping threads.

    A one-item run is absorbed into its neighbor. Extra runs beyond ``group_limit``
    are absorbed too, so a per-turn labeling cannot publish dozens of tiny threads
    or an unbounded merge request.
    """
    if not isinstance(payload, dict):
        return None, "The model response was not a JSON object."
    assignments = payload.get("assignments")
    if not isinstance(assignments, list) or len(assignments) != len(units) or not units:
        return None, "The map does not cover the whole conversation."
    keys: list[int] = []
    for item in assignments:
        if isinstance(item, bool) or not isinstance(item, int):
            return None, "The model response did not match the conversation schema."
        keys.append(item)
    described: dict[int, dict] = {}
    threads = payload.get("threads")
    if threads is None:
        threads = []
    if not isinstance(threads, list):
        return None, "The model response did not match the conversation schema."
    for thread in threads:
        if not isinstance(thread, dict) or isinstance(thread.get("key"), bool) or not isinstance(thread.get("key"), int):
            continue
        described[thread["key"]] = thread
    runs: list[dict] = []
    start = 0
    for index in range(1, len(keys) + 1):
        if index != len(keys) and keys[index] == keys[start]:
            continue
        runs.append({"start": start, "end": index, "key": keys[start]})
        start = index
    _absorb_short_runs(runs, group_limit)
    grouped: list[dict] = []
    for run in runs:
        meta = described.get(run["key"]) or {}
        title = str(meta.get("title") or "").strip() or "Untitled"
        summary = str(meta.get("summary") or "").strip()
        grouped.append({
            "start_turn_id": units[run["start"]]["start_turn_id"],
            "end_turn_id": units[run["end"] - 1]["end_turn_id"],
            "title": title,
            "summary": summary,
        })
    return grouped, None


def _absorb_short_runs(runs: list[dict], group_limit: int) -> None:
    while len(runs) > 1 and any(run["end"] - run["start"] == 1 for run in runs):
        index = next(pos for pos, run in enumerate(runs) if run["end"] - run["start"] == 1)
        _absorb(runs, index)
    while len(runs) > max(1, group_limit):
        lengths = [run["end"] - run["start"] for run in runs]
        _absorb(runs, lengths.index(min(lengths)))


def _absorb(runs: list[dict], index: int) -> None:
    if index <= 0:
        runs[1]["start"] = runs[0]["start"]
        del runs[0]
        return
    if index >= len(runs) - 1:
        runs[index - 1]["end"] = runs[index]["end"]
        del runs[index]
        return
    previous = runs[index - 1]["end"] - runs[index - 1]["start"]
    following = runs[index + 1]["end"] - runs[index + 1]["start"]
    if following > previous:
        runs[index + 1]["start"] = runs[index]["start"]
        del runs[index]
        return
    runs[index - 1]["end"] = runs[index]["end"]
    del runs[index]


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
