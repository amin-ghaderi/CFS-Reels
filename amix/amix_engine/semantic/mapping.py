"""Conversation map pipeline. A partial map is never published."""
from __future__ import annotations

import json

from amix.amix_engine.semantic.budget import (
    SEMANTIC_DATA_TOKEN_BUDGET,
    estimate_tokens,
    repair_payload,
    request_diagnostics,
    within_request_budget,
)
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.input import (
    SemanticChunk,
    SemanticInput,
    build_semantic_input,
    chunk_turns,
    turn_payload,
    turn_request_tokens,
)
from amix.amix_engine.semantic.provider import (
    GENERATE_STRUCTURED,
    STRICT_JSON_SCHEMA,
    StructuredRequest,
    runtime_provenance as _runtime_provenance,
)
from amix.amix_engine.semantic.tasks import (
    CHUNK_PROFILE,
    MAX_TURN_CHARS,
    PROFILE_ID,
    PROFILE_VERSION,
    SYSTEM_PROMPT,
    TASK_ID,
    VALIDATION_VERSION,
    assignment_schema,
    output_token_limit,
)
from amix.amix_engine.semantic.validate import coverage_error, parse_draft, resolve_threads, threads_from_assignments
from amix.amix_engine.storage.project import ProjectStore
from amix.amix_engine.time.clock import TimeRange


def map_is_stale(store: ProjectStore, asset_id: str) -> bool:
    from amix.amix_engine.storage.kinds import CONVERSATION_MAP

    run_id = store.get_active_run_id(asset_id, CONVERSATION_MAP)
    if run_id is None:
        return False
    recorded = store.analysis_record(run_id)["config"]
    try:
        current = build_semantic_input(store, asset_id)
    except SemanticError:
        return True
    return (
        recorded.get("transcript_run_id") != current.transcript_run_id
        or recorded.get("turns_run_id") != current.turns_run_id
        or recorded.get("text_fingerprint") != current.text_fingerprint
    )


def map_conversation(store: ProjectStore, asset_id: str, provider, cancellation, progress) -> dict:
    if GENERATE_STRUCTURED not in provider.descriptor.capabilities:
        raise SemanticError("semantic_capability_missing", "This provider cannot produce structured output.")
    progress(500)
    semantic = build_semantic_input(store, asset_id)
    for turn in semantic.turns:
        if len(turn.text) > MAX_TURN_CHARS or turn_request_tokens(turn) > SEMANTIC_DATA_TOKEN_BUDGET:
            raise SemanticError("semantic_context_too_large", "A turn is too large for this semantic profile.")
    chunks = chunk_turns(semantic.turns, fits=_chunk_fits)
    progress(1500)
    requests = 0
    repairs = 0
    ordinal = _Ordinal()
    candidates = []
    for index, chunk in enumerate(chunks):
        cancellation.raise_if_cancelled()
        draft, used_requests, used_repairs = _chunk_draft(provider, chunk, cancellation, ordinal)
        requests += used_requests
        repairs += used_repairs
        candidates.append({
            "chunk_id": chunk.chunk_id,
            "start_turn_id": draft[0]["start_turn_id"],
            "end_turn_id": draft[-1]["end_turn_id"],
            "title": draft[0]["title"] if len(draft) == 1 else " / ".join(item["title"] for item in draft),
            "summary": draft[0]["summary"] if len(draft) == 1 else " ".join(item["summary"] for item in draft if item["summary"]),
            "threads": draft,
        })
        progress(1500 + int(6000 * (index + 1) / len(chunks)))
    cancellation.raise_if_cancelled()
    if len(chunks) == 1:
        final_draft = candidates[0]["threads"]
    else:
        final_draft, merge_requests, merge_repairs = _merge_draft(provider, semantic, candidates, cancellation, ordinal)
        requests += merge_requests
        repairs += merge_repairs
    error = coverage_error([turn.turn_id for turn in semantic.turns], final_draft)
    if error:
        raise SemanticError("semantic_invalid_output", error)
    threads = resolve_threads(semantic.turns, final_draft)
    progress(9000)
    cancellation.raise_if_cancelled()
    run_id = _publish(store, asset_id, semantic, chunks, threads, provider, requests, repairs)
    return {
        "activated": True,
        "conversation_map_run_id": run_id,
        "thread_count": len(threads),
        "request_count": requests,
        "repair_count": repairs,
    }


def _publish(store, asset_id, semantic: SemanticInput, chunks, threads, provider, requests: int, repairs: int) -> str:
    descriptor = provider.descriptor
    execution = "local" if descriptor.execution == "local" else "remote"
    config = {
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "transcript_run_id": semantic.transcript_run_id,
        "turns_run_id": semantic.turns_run_id,
        "text_fingerprint": semantic.text_fingerprint,
        "provider_id": descriptor.provider_id,
        "adapter_kind": descriptor.adapter_kind,
        "model_id": descriptor.model_id,
        "execution": execution,
        **_runtime_provenance(descriptor),
        "capabilities": sorted(descriptor.capabilities),
        "chunk_profile": CHUNK_PROFILE,
        "chunk_fingerprints": [chunk.fingerprint for chunk in chunks],
        "request_count": requests,
        "repair_count": repairs,
        "validation_version": VALIDATION_VERSION,
    }
    window = TimeRange(semantic.turns[0].start_us, semantic.turns[-1].end_us)
    return store.publish_conversation_map(
        asset_id=asset_id,
        threads=threads,
        transcript_run_id=semantic.transcript_run_id,
        turns_run_id=semantic.turns_run_id,
        fingerprint=semantic.text_fingerprint,
        window=window,
        config=config,
        origin="local" if execution == "local" else "cloud",
    )


def _chunk_fits(primary, context) -> bool:
    payload = {
        "stage": "chunk",
        "chunk_id": "fit",
        "turns": [turn_payload(turn, "context") for turn in context] + [turn_payload(turn, "primary") for turn in primary],
    }
    diagnostics = request_diagnostics(
        profile_id=PROFILE_ID,
        ordinal=0,
        chunk_id="fit",
        turns=len(primary),
        words=0,
        context_turns=len(context),
        system_prompt=SYSTEM_PROMPT,
        schema=assignment_schema(len(primary)),
        payload=payload,
    )
    return within_request_budget(diagnostics)


def _chunk_draft(provider, chunk: SemanticChunk, cancellation, ordinal) -> tuple[list[dict], int, int]:
    context = list(chunk.context)
    primary = list(chunk.primary)
    visible = [turn_payload(turn, "context") for turn in context] + [turn_payload(turn, "primary") for turn in primary]
    if context and estimate_tokens(json.dumps(visible, sort_keys=True)) > SEMANTIC_DATA_TOKEN_BUDGET:
        context = []
    payload = {
        "stage": "chunk",
        "chunk_id": chunk.chunk_id,
        "turns": [turn_payload(turn, "context") for turn in context] + [turn_payload(turn, "primary") for turn in primary],
    }
    primary_ids = [turn.turn_id for turn in chunk.primary]
    words = sum(len(turn.word_ids) for turn in chunk.primary)
    units = [{"start_turn_id": turn_id, "end_turn_id": turn_id} for turn_id in primary_ids]
    return _generate(
        provider, "chunk", payload, primary_ids, units, cancellation, ordinal,
        chunk_id=chunk.chunk_id, turns=len(chunk.primary), words=words, context_turns=len(context),
    )


def _merge_draft(provider, semantic: SemanticInput, candidates: list[dict], cancellation, ordinal) -> tuple[list[dict], int, int]:
    units = [thread for item in candidates for thread in item["threads"]]
    payload = {
        "stage": "merge",
        "candidates": [
            {
                "index": index,
                "start_turn_id": thread["start_turn_id"],
                "end_turn_id": thread["end_turn_id"],
                "title": thread["title"],
                "summary": thread["summary"],
            }
            for index, thread in enumerate(units)
        ],
    }
    repair_ids = [thread["start_turn_id"] for thread in units]
    repair_ids.append(units[-1]["end_turn_id"])
    words = sum(len(turn.word_ids) for turn in semantic.turns)
    return _generate(
        provider, "merge", payload, [turn.turn_id for turn in semantic.turns], units, cancellation, ordinal,
        chunk_id=None, turns=len(semantic.turns), words=words, context_turns=0, repair_ids=repair_ids,
    )


class _Ordinal:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def _generate(
    provider, stage: str, payload: dict, turn_ids: list[str], units: list[dict], cancellation, ordinal: _Ordinal, *,
    chunk_id: str | None, turns: int, words: int, context_turns: int, repair_ids: list[str] | None = None,
) -> tuple[list[dict], int, int]:
    request = _request(provider, stage, payload, ordinal, chunk_id, turns, words, context_turns, len(units))
    first, error, attempts = _once(provider, request, units)
    cancellation.raise_if_cancelled()
    previous = None
    if error is None and first is not None:
        covered = coverage_error(turn_ids, first)
        if covered is None:
            return first, attempts, 0
        error = covered
        previous = first
    repaired = repair_payload(payload, error or "The model response could not be used.", previous, repair_ids or turn_ids)
    second, second_error, second_attempts = _once(
        provider,
        _request(provider, stage, repaired, ordinal, chunk_id, turns, words, 0, len(units)),
        units,
    )
    cancellation.raise_if_cancelled()
    if second is None or second_error is not None:
        raise SemanticError("semantic_invalid_output", second_error or "The model response could not be used.")
    covered = coverage_error(turn_ids, second)
    if covered is not None:
        raise SemanticError("semantic_invalid_output", covered)
    return second, attempts + second_attempts, 1


def _once(provider, request: StructuredRequest, units: list[dict]) -> tuple[list[dict] | None, str | None, int]:
    raw, error, attempts = _call(provider, request)
    if error is not None:
        return None, error, attempts
    if isinstance(raw, dict) and "assignments" in raw:
        draft, problem = threads_from_assignments(units, raw)
        return draft, problem, attempts
    draft, problem = parse_draft(raw)
    return draft, problem, attempts


def _call(provider, request: StructuredRequest) -> tuple[dict | None, str | None, int]:
    """One provider call, plus one local retry when the server stalls past the deadline."""
    try:
        return provider.generate_structured(request), None, 1
    except SemanticError as exc:
        if exc.code == "semantic_invalid_output":
            return None, exc.message, 1
        if exc.code == "semantic_timeout" and getattr(provider.descriptor, "execution", "") == "local":
            try:
                return provider.generate_structured(request), None, 2
            except SemanticError as again:
                if again.code == "semantic_invalid_output":
                    return None, again.message, 2
                if again.code == "semantic_timeout":
                    raise _timeout(again, provider, request) from again
                raise
        if exc.code == "semantic_timeout":
            raise _timeout(exc, provider, request) from exc
        raise


def _timeout(exc: SemanticError, provider, request: StructuredRequest) -> SemanticError:
    diagnostics = request.diagnostics or {}
    chunk_id = diagnostics.get("chunk_id") or ""
    where = f"Chunk {chunk_id}." if chunk_id else "Merge."
    ordinal = diagnostics.get("ordinal")
    request_label = f"Request {ordinal}." if ordinal else ""
    descriptor = provider.descriptor
    detail = " ".join(
        part for part in (
            where,
            request_label,
            exc.detail,
            f"Provider {descriptor.provider_id}.",
            f"Model {descriptor.display_name}.",
        )
        if part
    )
    return SemanticError(exc.code, exc.message, detail=detail)


def _request(
    provider, stage: str, payload: dict, ordinal: _Ordinal,
    chunk_id: str | None, turns: int, words: int, context_turns: int, assignment_count: int,
) -> StructuredRequest:
    strict = getattr(provider.descriptor, "structured_transport", "") == STRICT_JSON_SCHEMA
    schema = assignment_schema(assignment_count) if strict else None
    limit = output_token_limit(assignment_count)
    diagnostics = request_diagnostics(
        profile_id=PROFILE_ID,
        ordinal=ordinal.next(),
        chunk_id=chunk_id,
        turns=turns,
        words=words,
        context_turns=context_turns,
        system_prompt=SYSTEM_PROMPT,
        schema=schema,
        payload=payload,
    )
    if not within_request_budget(diagnostics):
        raise SemanticError("semantic_context_too_large", "This semantic request is larger than the profile limit.")
    return StructuredRequest(
        task_id=TASK_ID,
        profile_id=PROFILE_ID,
        profile_version=PROFILE_VERSION,
        stage=stage,
        system_prompt=SYSTEM_PROMPT,
        payload=payload,
        output_schema=schema,
        diagnostics=diagnostics,
        output_token_limit=limit,
    )
