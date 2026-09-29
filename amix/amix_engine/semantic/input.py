"""Deterministic semantic view. The model sees ids and effective text, not rows."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.tasks import CHUNK_PROFILE, CHUNK_TEXT_BUDGET, CONTEXT_TURN_COUNT, PROFILE_ID
from amix.amix_engine.storage.kinds import PARTICIPANT_ASSIGNMENT, TURNS
from amix.amix_engine.storage.project import ProjectStore


@dataclass(frozen=True)
class SemanticTurn:
    turn_id: str
    participant_id: str | None
    participant_name: str | None
    word_ids: tuple[str, ...]
    text: str
    start_us: int
    end_us: int

    @property
    def first_word_id(self) -> str:
        return self.word_ids[0]

    @property
    def last_word_id(self) -> str:
        return self.word_ids[-1]


@dataclass(frozen=True)
class SemanticInput:
    transcript_run_id: str
    turns_run_id: str
    text_fingerprint: str
    turns: tuple[SemanticTurn, ...]


@dataclass(frozen=True)
class SemanticChunk:
    chunk_id: str
    primary: tuple[SemanticTurn, ...]
    context: tuple[SemanticTurn, ...]
    fingerprint: str


def text_fingerprint(turns: list[SemanticTurn] | tuple[SemanticTurn, ...]) -> str:
    payload = [
        {"turn_id": turn.turn_id, "word_ids": list(turn.word_ids), "text": turn.text}
        for turn in turns
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_semantic_input(store: ProjectStore, asset_id: str) -> SemanticInput:
    transcript = store.active_transcript(asset_id)
    if transcript is None:
        raise SemanticError("transcript_required", "Transcribe this media before mapping the conversation.")
    turns_run_id = store.get_active_run_id(asset_id, TURNS)
    assignment_id = store.get_active_run_id(asset_id, PARTICIPANT_ASSIGNMENT)
    if turns_run_id is None or assignment_id is None:
        raise SemanticError("turns_required", "Finish speaker analysis before mapping the conversation.")
    assignment_deps = store.run_dependencies(assignment_id)
    turn_deps = store.run_dependencies(turns_run_id)
    if transcript.analysis_run_id not in assignment_deps or assignment_id not in turn_deps:
        raise SemanticError("turns_required", "Speaker turns do not match the current transcript.")
    names = {participant_id: name for participant_id, name, _order in store.list_participants()}
    words = {word.word_id: word for word in store.load_words(transcript.analysis_run_id)}
    semantic: list[SemanticTurn] = []
    for turn in store.load_turns(turns_run_id):
        if not turn.word_ids or any(word_id not in words for word_id in turn.word_ids):
            raise SemanticError("turns_required", "Speaker turns do not match the current transcript.")
        pieces = [words[word_id].effective_text for word_id in turn.word_ids]
        participant = None if turn.participant_id is None else turn.participant_id.value
        semantic.append(SemanticTurn(
            turn_id=turn.turn_id,
            participant_id=participant,
            participant_name=None if participant is None else names.get(participant),
            word_ids=tuple(turn.word_ids),
            text=" ".join(pieces),
            start_us=turn.start_us,
            end_us=turn.end_us,
        ))
    if not semantic:
        raise SemanticError("turns_required", "Speaker turns do not match the current transcript.")
    semantic.sort(key=lambda turn: (turn.start_us, turn.end_us, turn.turn_id))
    return SemanticInput(
        transcript.analysis_run_id,
        turns_run_id,
        text_fingerprint(semantic),
        tuple(semantic),
    )


def chunk_turns(
    turns: tuple[SemanticTurn, ...] | list[SemanticTurn],
    *,
    budget: int = CHUNK_TEXT_BUDGET,
) -> list[SemanticChunk]:
    """Split on turn boundaries only. A turn longer than the budget stays whole."""
    ordered = list(turns)
    chunks: list[SemanticChunk] = []
    index = 0
    while index < len(ordered):
        primary: list[SemanticTurn] = []
        size = 0
        while index < len(ordered):
            turn = ordered[index]
            if primary and size + len(turn.text) > budget:
                break
            primary.append(turn)
            size += len(turn.text)
            index += 1
        context: tuple[SemanticTurn, ...] = ()
        if chunks and CONTEXT_TURN_COUNT:
            context = chunks[-1].primary[-CONTEXT_TURN_COUNT:]
        chunk_id = f"c{len(chunks):04d}"
        chunks.append(SemanticChunk(
            chunk_id=chunk_id,
            primary=tuple(primary),
            context=context,
            fingerprint=chunk_fingerprint(chunk_id, primary),
        ))
    return chunks


def chunk_fingerprint(chunk_id: str, primary: list[SemanticTurn]) -> str:
    payload = {
        "profile": CHUNK_PROFILE,
        "task": PROFILE_ID,
        "chunk_id": chunk_id,
        "turns": [{"turn_id": turn.turn_id, "text": turn.text} for turn in primary],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def turn_payload(turn: SemanticTurn, role: str) -> dict:
    return {
        "turn_id": turn.turn_id,
        "participant_id": turn.participant_id,
        "participant_name": turn.participant_name,
        "word_ids": list(turn.word_ids),
        "text": turn.text,
        "role": role,
    }
