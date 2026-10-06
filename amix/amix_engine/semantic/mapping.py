"""Conversation map pipeline. A partial map is never published."""
from __future__ import annotations

import json
import time

from amix.amix_engine.semantic.budget import (
    MERGE_TOKEN_BUDGET,
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
    turn_request_tokens,
)
from amix.amix_engine.semantic.provider import (
    GENERATE_STRUCTURED,
    StructuredRequest,
    requests_output_schema,
    runtime_provenance as _runtime_provenance,
    transport_delta,
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
    boundary_schema,
    chunk_group_limit,
    MERGE_CANDIDATE_LIMIT,
    compact_chunk_payload,
    compact_merge_payload,
    output_token_limit,
)
from amix.amix_engine.semantic.validate import (
    coverage_error,
    parse_draft,
    resolve_threads,
    threads_from_assignments,
    threads_from_boundaries,
)
from amix.amix_engine.storage.project import ProjectStore
from amix.amix_engine.time.clock import TimeRange


def map_is_stale(store: ProjectStore, asset_id: str) -> bool:
    from amix.amix_engine.storage.kinds import CONVERSATION_MAP

    run_id = store.get_active_run_id(asset_id, CONVERSATION_MAP)
    if run_id is None:
        return False
    recorded = store.analysis_record(run_id)["config"]
    try:
        from amix.amix_engine.semantic.read import cached_semantic_input

        current = cached_semantic_input(store, asset_id)
    except SemanticError:
        return True
    return (
        recorded.get("transcript_run_id") != current.transcript_run_id
        or recorded.get("turns_run_id") != current.turns_run_id
        or recorded.get("text_fingerprint") != current.text_fingerprint
    )


def map_conversation(store: ProjectStore, asset_id: str, provider, cancellation, progress) -> dict:
    started = time.monotonic()
    if GENERATE_STRUCTURED not in provider.descriptor.capabilities:
        raise SemanticError("semantic_capability_missing", "This provider cannot produce structured output.")
    progress(500)
    semantic = build_semantic_input(store, asset_id)
    from amix.amix_engine.semantic.read import remember_semantic

    remember_semantic(store, asset_id, semantic)
    for turn in semantic.turns:
        if len(turn.text) > MAX_TURN_CHARS or turn_request_tokens(turn) > SEMANTIC_DATA_TOKEN_BUDGET:
            raise SemanticError("semantic_context_too_large", "A turn is too large for this semantic profile.")
    chunks = chunk_turns(
        semantic.turns, fits=_chunk_fits, max_turns=provider.descriptor.preferred_max_turns,
    )
    progress(1500)
    requests = 0
    repairs = 0
    recovery = _Recovery()
    ordinal = _Ordinal()
    candidates = []
    for index, chunk in enumerate(chunks):
        cancellation.raise_if_cancelled()
        draft, used_requests, used_repairs = _chunk_draft(
            provider, chunk, cancellation, ordinal, recovery=recovery,
        )
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
    run_id = _publish(
        store, asset_id, semantic, chunks, threads, provider, requests, repairs,
        duration_ms=int((time.monotonic() - started) * 1000),
        loop_stops=recovery.loops, splits=recovery.splits,
    )
    return {
        "activated": True,
        "conversation_map_run_id": run_id,
        "thread_count": len(threads),
        "request_count": requests,
        "repair_count": repairs,
        "loop_stop_count": recovery.loops,
        "split_count": recovery.splits,
    }


def _publish(
    store, asset_id, semantic: SemanticInput, chunks, threads, provider, requests: int, repairs: int,
    duration_ms: int = 0, loop_stops: int = 0, splits: int = 0,
) -> str:
    descriptor = provider.descriptor
    execution = "local" if descriptor.execution == "local" else "remote"
    config = {
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "task_id": TASK_ID,
        "duration_ms": int(duration_ms),
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
        "loop_stop_count": int(loop_stops),
        "split_count": int(splits),
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
    payload = compact_chunk_payload("fit", primary, context)
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


MAX_REPETITION_SPLIT_DEPTH = 2
MIN_REPETITION_LEAF_TURNS = 8


class _Recovery:
    def __init__(self) -> None:
        self.loops = 0
        self.splits = 0


def _chunk_draft(
    provider, chunk: SemanticChunk, cancellation, ordinal, *, recovery: _Recovery | None = None, depth: int = 0,
) -> tuple[list[dict], int, int]:
    recovery = recovery or _Recovery()
    context = list(chunk.context)
    primary = list(chunk.primary)
    rendered = json.dumps(
        compact_chunk_payload(chunk.chunk_id, primary, context),
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    if context and estimate_tokens(rendered) > SEMANTIC_DATA_TOKEN_BUDGET:
        context = []
    payload = compact_chunk_payload(chunk.chunk_id, primary, context)
    primary_ids = [turn.turn_id for turn in primary]
    words = sum(len(turn.word_ids) for turn in primary)
    units = [{"start_turn_id": turn_id, "end_turn_id": turn_id} for turn_id in primary_ids]
    before = int(getattr(provider, "transport_attempts", 0) or 0)
    try:
        return _generate(
            provider, "chunk", payload, primary_ids, units, cancellation, ordinal,
            chunk_id=chunk.chunk_id, turns=len(primary), words=words, context_turns=len(context),
        )
    except SemanticError as exc:
        if exc.code != "semantic_repetition_stop":
            raise
        spent = transport_delta(provider, before)
        if depth >= MAX_REPETITION_SPLIT_DEPTH or len(primary) < MIN_REPETITION_LEAF_TURNS * 2:
            raise
        recovery.loops += 1
        recovery.splits += 1
        midpoint = len(primary) // 2
        left = primary[:midpoint]
        right = primary[midpoint:]
        cancellation.raise_if_cancelled()
        left_draft, left_requests, left_repairs = _chunk_draft(
            provider,
            SemanticChunk(f"{chunk.chunk_id}a", tuple(left), tuple(context), chunk.fingerprint),
            cancellation, ordinal, recovery=recovery, depth=depth + 1,
        )
        cancellation.raise_if_cancelled()
        right_draft, right_requests, right_repairs = _chunk_draft(
            provider,
            SemanticChunk(f"{chunk.chunk_id}b", tuple(right), (left[-1],), chunk.fingerprint),
            cancellation, ordinal, recovery=recovery, depth=depth + 1,
        )
        return left_draft + right_draft, spent + left_requests + right_requests, left_repairs + right_repairs


def _merge_draft(provider, semantic: SemanticInput, candidates: list[dict], cancellation, ordinal) -> tuple[list[dict], int, int]:
    units = [thread for item in candidates for thread in item["threads"]]
    turn_ids = [turn.turn_id for turn in semantic.turns]
    words = sum(len(turn.word_ids) for turn in semantic.turns)
    return _merge_level(provider, units, turn_ids, words, cancellation, ordinal)


def _merge_level(provider, units, turn_ids, words, cancellation, ordinal) -> tuple[list[dict], int, int]:
    """Merge adjacent candidates. A payload that does not fit is merged in halves."""
    payload = compact_merge_payload(units)
    span = _span_ids(turn_ids, units)
    too_many = len(units) > MERGE_CANDIDATE_LIMIT
    if len(units) > 1 and (too_many or not _merge_fits(provider, payload, len(span), words, len(units))):
        mid = len(units) // 2
        left, left_requests, left_repairs = _merge_level(provider, units[:mid], turn_ids, words, cancellation, ordinal)
        right, right_requests, right_repairs = _merge_level(provider, units[mid:], turn_ids, words, cancellation, ordinal)
        combined = left + right
        requests = left_requests + right_requests
        repairs = left_repairs + right_repairs
        shrunk = compact_merge_payload(combined)
        if len(combined) >= len(units) or not _merge_fits(provider, shrunk, len(span), words, len(combined)):
            return combined, requests, repairs
        draft, used_requests, used_repairs = _merge_level(provider, combined, turn_ids, words, cancellation, ordinal)
        return draft, requests + used_requests, repairs + used_repairs
    repair_ids = [unit["start_turn_id"] for unit in units]
    repair_ids.append(units[-1]["end_turn_id"])
    return _generate(
        provider, "merge", payload, span, units, cancellation, ordinal,
        chunk_id=None, turns=len(span), words=words, context_turns=0, repair_ids=repair_ids,
        budget=MERGE_TOKEN_BUDGET,
    )


def _span_ids(turn_ids: list[str], units: list[dict]) -> list[str]:
    index = {turn_id: position for position, turn_id in enumerate(turn_ids)}
    start = index[units[0]["start_turn_id"]]
    end = index[units[-1]["end_turn_id"]]
    return turn_ids[start:end + 1]


def _merge_fits(provider, payload: dict, turns: int, words: int, count: int) -> bool:
    diagnostics = request_diagnostics(
        profile_id=PROFILE_ID,
        ordinal=0,
        chunk_id=None,
        turns=turns,
        words=words,
        context_turns=0,
        system_prompt=SYSTEM_PROMPT,
        schema=boundary_schema(count) if requests_output_schema(provider.descriptor) else None,
        payload=payload,
    )
    return within_request_budget(diagnostics, ceiling=MERGE_TOKEN_BUDGET)


class _Ordinal:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def _generate(
    provider, stage: str, payload: dict, turn_ids: list[str], units: list[dict], cancellation, ordinal: _Ordinal, *,
    chunk_id: str | None, turns: int, words: int, context_turns: int, repair_ids: list[str] | None = None,
    budget: int | None = None,
) -> tuple[list[dict], int, int]:
    request = _request(
        provider, stage, payload, ordinal, chunk_id, turns, words, context_turns, len(units), budget=budget,
    )
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
        _request(provider, stage, repaired, ordinal, chunk_id, turns, words, 0, len(units), budget=budget),
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
    if isinstance(raw, dict) and "boundaries" in raw:
        draft, problem = threads_from_boundaries(units, raw)
        return draft, problem, attempts
    if isinstance(raw, dict) and "assignments" in raw:
        draft, problem = threads_from_assignments(units, raw, group_limit=chunk_group_limit(len(units)))
        return draft, problem, attempts
    draft, problem = parse_draft(raw)
    return draft, problem, attempts


def _call(provider, request: StructuredRequest) -> tuple[dict | None, str | None, int]:
    """One provider call, plus one local retry when the server stalls past the deadline."""
    try:
        before = int(getattr(provider, "transport_attempts", 0) or 0)
        parsed = provider.generate_structured(request)
        return parsed, None, transport_delta(provider, before)
    except SemanticError as exc:
        if exc.code == "semantic_invalid_output":
            text = exc.message if not exc.detail else f"{exc.message} {exc.detail}"
            return None, text, 1
        if exc.code == "semantic_timeout" and getattr(provider.descriptor, "execution", "") == "local":
            try:
                return provider.generate_structured(request), None, 2
            except SemanticError as again:
                if again.code == "semantic_invalid_output":
                    text = again.message if not again.detail else f"{again.message} {again.detail}"
                    return None, text, 2
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
            f"Model id {descriptor.model_id}.",
        )
        if part
    )
    return SemanticError(exc.code, exc.message, detail=detail)


def _request(
    provider, stage: str, payload: dict, ordinal: _Ordinal,
    chunk_id: str | None, turns: int, words: int, context_turns: int, assignment_count: int,
    budget: int | None = None,
) -> StructuredRequest:
    attach_schema = requests_output_schema(provider.descriptor)
    groups = assignment_count if stage == "merge" else chunk_group_limit(assignment_count)
    if attach_schema and stage == "merge":
        schema = boundary_schema(assignment_count)
    elif attach_schema:
        schema = assignment_schema(assignment_count, groups)
    else:
        schema = None
    limit = output_token_limit(assignment_count, groups)
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
    if not within_request_budget(diagnostics, ceiling=budget):
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
