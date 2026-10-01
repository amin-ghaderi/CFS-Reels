"""Request-size diagnostics. Estimates are deterministic and do not call a vendor tokenizer.

Transcript text is counted, not copied into the diagnostic record.
"""
from __future__ import annotations

import json
import re

# A small CPU model should see a small request even when its context window is larger.
REQUEST_TOKEN_LIMIT = 4096
SEMANTIC_DATA_TOKEN_BUDGET = 3072

_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{8,}\b")
_STRING_KEYS = (
    "text",
    "turn_id",
    "start_turn_id",
    "end_turn_id",
    "first_turn_id",
    "last_turn_id",
    "participant_id",
    "participant_name",
    "role",
    "title",
    "summary",
    "topic",
    "hook",
    "chunk_id",
    "stage",
    "conversation_thread_id",
    "thread_title",
)


def estimate_tokens(text: str) -> int:
    """Prose is about four characters per token. UUID-like runs are about two."""
    if not text:
        return 0
    id_chars = sum(len(match) for match in _UUID.findall(text))
    other = max(0, len(text) - id_chars)
    return (other + 3) // 4 + (id_chars + 1) // 2


def section_chars(payload: object) -> dict[str, int]:
    """Character totals by field name. The returned record contains no field values."""
    totals = {key: 0 for key in _STRING_KEYS}
    totals["word_ids"] = 0
    _walk(payload, totals)
    return totals


def _walk(value: object, totals: dict[str, int]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "word_ids" and isinstance(item, list):
                totals["word_ids"] += sum(len(word) for word in item if isinstance(word, str))
            elif key in totals and isinstance(item, str):
                totals[key] += len(item)
            else:
                _walk(item, totals)
    elif isinstance(value, list):
        for item in value:
            _walk(item, totals)


def request_diagnostics(
    *,
    profile_id: str,
    ordinal: int,
    chunk_id: str | None,
    turns: int,
    words: int,
    context_turns: int,
    system_prompt: str,
    schema: dict | None,
    payload: dict,
) -> dict:
    payload_json = json.dumps(payload, sort_keys=True)
    schema_json = "" if schema is None else json.dumps(schema, sort_keys=True)
    sections = section_chars(payload)
    value_chars = sum(sections.values())
    return {
        "profile_id": profile_id,
        "ordinal": ordinal,
        "chunk_id": chunk_id or "",
        "turns": turns,
        "words": words,
        "context_turns": context_turns,
        "system_chars": len(system_prompt),
        "schema_chars": len(schema_json),
        "payload_chars": len(payload_json),
        "json_syntax_chars": max(0, len(payload_json) - value_chars),
        "text_chars": sections["text"],
        "turn_id_chars": (
            sections["turn_id"]
            + sections["start_turn_id"]
            + sections["end_turn_id"]
            + sections["first_turn_id"]
            + sections["last_turn_id"]
        ),
        "word_id_chars": sections["word_ids"],
        "participant_id_chars": sections["participant_id"],
        "participant_name_chars": sections["participant_name"],
        "instruction_tokens": estimate_tokens(system_prompt) + estimate_tokens(schema_json),
        "data_tokens": estimate_tokens(payload_json),
        "estimated_tokens": estimate_tokens(system_prompt) + estimate_tokens(schema_json) + estimate_tokens(payload_json),
    }


def within_request_budget(diagnostics: dict) -> bool:
    return int(diagnostics["estimated_tokens"]) <= REQUEST_TOKEN_LIMIT and int(diagnostics["data_tokens"]) <= SEMANTIC_DATA_TOKEN_BUDGET


def repair_payload(payload: dict, error: str, previous: list | None, anchor_ids: list[str]) -> dict:
    """A parsed draft is repaired from anchors and the error. Invalid JSON still needs the compact source."""
    if previous is None:
        return {**payload, "repair": {"error": error}}
    compact = {
        "stage": payload.get("stage"),
        "repair": {"error": error},
        "previous": previous,
        "turn_ids": list(anchor_ids),
    }
    for key in ("chunk_id", "conversation_thread_id"):
        if key in payload:
            compact[key] = payload[key]
    return compact
