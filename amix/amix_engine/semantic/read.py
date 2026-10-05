"""Conversation workspace read model. It does not call a provider."""
from __future__ import annotations

import threading

from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.input import SemanticInput, build_semantic_input
from amix.amix_engine.semantic.mapping import map_is_stale
from amix.amix_engine.semantic.registry import provider_status
from amix.amix_engine.storage.kinds import CONVERSATION_MAP, PARTICIPANT_ASSIGNMENT, TURNS
from amix.amix_engine.storage.project import ProjectStore

_CACHE: dict[tuple, SemanticInput] = {}
_CACHE_LOCK = threading.Lock()


def semantic_stamp(store: ProjectStore, asset_id: str) -> tuple:
    """Cheap identity of the semantic input. It does not load word rows."""
    transcript = store.active_transcript(asset_id)
    return (
        store.project_id,
        asset_id,
        None if transcript is None else transcript.analysis_run_id,
        store.get_active_run_id(asset_id, TURNS),
        store.get_active_run_id(asset_id, PARTICIPANT_ASSIGNMENT),
        store.word_text_revision(),
    )


def cached_semantic_input(store: ProjectStore, asset_id: str) -> SemanticInput:
    """Reuse a built input while the transcript, turns, and word text are unchanged."""
    stamp = semantic_stamp(store, asset_id)
    with _CACHE_LOCK:
        found = _CACHE.get(stamp)
    if found is not None:
        return found
    built = build_semantic_input(store, asset_id)
    remember_semantic(store, asset_id, built)
    return built


def remember_semantic(store: ProjectStore, asset_id: str, semantic: SemanticInput) -> None:
    stamp = semantic_stamp(store, asset_id)
    with _CACHE_LOCK:
        _CACHE[stamp] = semantic
        while len(_CACHE) > 4:
            _CACHE.pop(next(iter(_CACHE)))


def conversation_view(store: ProjectStore, asset_id: str) -> dict:
    store.get_media(asset_id)
    try:
        status = provider_status()
    except SemanticError:
        status = {
            "configured": False,
            "display_name": None,
            "model_id": None,
            "execution": None,
            "capability_ready": False,
            "offline_blocked": False,
            "network_mode": "offline",
        }
    transcript = store.active_transcript(asset_id)
    turns_ready = False
    blocking = None if transcript is not None else "transcript_required"
    names: dict[str, str | None] = {}
    ordered: list[str] = []
    if transcript is not None:
        try:
            semantic = cached_semantic_input(store, asset_id)
        except SemanticError as exc:
            blocking = exc.code
        else:
            turns_ready = True
            blocking = None
            names = {turn.turn_id: turn.participant_name for turn in semantic.turns}
            ordered = [turn.turn_id for turn in semantic.turns]
    run_id = store.get_active_run_id(asset_id, CONVERSATION_MAP)
    threads = [] if run_id is None else store.load_conversation_threads(run_id)
    stale = bool(run_id) and map_is_stale(store, asset_id)
    return {
        "transcript_present": transcript is not None,
        "turns_ready": turns_ready,
        "blocking_reason": blocking,
        "provider_configured": status["configured"],
        "provider_display_name": status["display_name"],
        "provider_model_id": status["model_id"],
        "provider_execution": status["execution"],
        "capability_ready": status["capability_ready"],
        "offline_blocked": status["offline_blocked"],
        "network_mode": status["network_mode"],
        "local_ai_state": status.get("local_ai_state"),
        "map_present": run_id is not None,
        "map_stale": stale,
        "conversation_map_run_id": run_id,
        "threads": [_thread_view(thread, names, ordered) for thread in threads],
    }


def _thread_view(thread: dict, names: dict[str, str | None], ordered: list[str]) -> dict:
    participants = []
    if ordered and thread["first_turn_id"] in ordered and thread["last_turn_id"] in ordered:
        start = ordered.index(thread["first_turn_id"])
        end = ordered.index(thread["last_turn_id"])
        for turn_id in ordered[start:end + 1]:
            name = names.get(turn_id)
            if name and name not in participants:
                participants.append(name)
    return {
        **thread,
        "participant_names": participants,
        "duration_us": thread["end_us"] - thread["start_us"],
    }
