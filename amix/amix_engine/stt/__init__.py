"""Turn speech evidence into one activated transcript. No model library imports."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from amix.amix_engine.adapters.stt.evidence import SttEvidence
from amix.amix_engine.adapters.stt.profile import ANALYSIS_WINDOW, TranscriptionProfile
from amix.amix_engine.adapters.stt.timing import CANONICAL_ORIGIN_RULE, canonical_source_us
from amix.amix_engine.domain.types import Word
from amix.amix_engine.stt.resolver import SpeechModelDescriptor
from amix.amix_engine.storage.project import ProjectStore, StoredMedia
from amix.amix_engine.time.clock import TimeRange


def activate_transcription(
    store: ProjectStore,
    asset: StoredMedia,
    source: Path,
    evidence: SttEvidence,
    model: SpeechModelDescriptor,
    profile: TranscriptionProfile,
    *,
    requested_language: str | None,
) -> str:
    """Persist a new run, transcript, and words, then switch the active pointer.

    Word ids are new UUIDs. Text is not part of the id. Corrections on an older
    transcript are not copied.
    """
    origin = 0 if asset.container_start_us is None else asset.container_start_us
    words: list[Word] = []
    confidences: dict[str, float | None] = {}
    segments: dict[str, str | None] = {}
    for item in evidence.words:
        start = canonical_source_us(item.start_us, origin)
        end = canonical_source_us(item.end_us, origin)
        word_id = str(uuid.uuid4())
        words.append(Word(word_id, start, end, item.text))
        confidences[word_id] = item.confidence
        segments[word_id] = str(item.segment)
    if asset.duration_us is None:
        end_us = origin if not words else max(word.end_us for word in words)
    else:
        end_us = origin + asset.duration_us
    if end_us < origin:
        end_us = origin
    window = TimeRange(origin, end_us)
    stat = source.stat()
    fingerprint = hashlib.sha256(
        f"{stat.st_size}:{stat.st_mtime_ns}:{model.identity}:{profile.profile_id}".encode("ascii")
    ).hexdigest()
    language = evidence.language or requested_language
    config = {
        "profile_id": profile.profile_id,
        "analysis_window": ANALYSIS_WINDOW,
        "model_id": model.model_id,
        "model_runtime": model.runtime,
        "model_identity": model.identity,
        "model_version": model.version,
        "faster_whisper_version": evidence.faster_whisper_version,
        "ctranslate2_version": evidence.ctranslate2_version,
        "device": model.device,
        "compute_type": model.compute_type,
        "requested_language": requested_language,
        "detected_language": evidence.language,
        "detected_language_probability": evidence.language_probability,
        "canonical_origin_rule": CANONICAL_ORIGIN_RULE,
        "source_container_start_us": origin,
        "beam_size": profile.beam_size,
        "vad_filter": profile.vad_filter,
        "word_timestamps": profile.word_timestamps,
        "task": profile.task,
        "temperature": list(profile.temperature),
    }
    return store.publish_activated_transcript(
        asset_id=asset.asset_id,
        words=words,
        algorithm_id=profile.profile_id,
        algorithm_version="1",
        fingerprint=fingerprint,
        window=window,
        config=config,
        language=language,
        confidences=confidences,
        segments=segments,
    )
