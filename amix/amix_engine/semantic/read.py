"""Conversation workspace read model. It does not call a provider."""
from __future__ import annotations

from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.input import build_semantic_input
from amix.amix_engine.semantic.mapping import map_is_stale
from amix.amix_engine.semantic.registry import provider_status
from amix.amix_engine.storage.kinds import CONVERSATION_MAP
from amix.amix_engine.storage.project import ProjectStore


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
            semantic = build_semantic_input(store, asset_id)
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
