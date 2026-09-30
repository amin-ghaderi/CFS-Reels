"""Caption tracks for one editorial sequence. No model and no network."""
from __future__ import annotations

import uuid
from pathlib import Path

from amix.amix_engine.adapters.media.publish import publish_text
from amix.amix_engine.captions.persist import load_current_track, load_export, record_export, replace_track, set_manual_text
from amix.amix_engine.captions.segment import (
    PROFILE_ID,
    CaptionRejected,
    CaptionWord,
    build_cues,
    normalize_caption_text,
    stale_reasons,
)
from amix.amix_engine.captions.serialize import render_srt, render_vtt
from amix.amix_engine.editorial.sequence import sequence_fingerprint
from amix.amix_engine.storage.errors import NoActiveTranscript, ProjectDatabaseInvalid


def caption_state(store, sequence_id: str) -> dict:
    sequence = _sequence(store, sequence_id)
    track = load_current_track(store, sequence_id)
    if track is None:
        return _absent(sequence)
    active = store.active_transcript(sequence["media_asset_id"])
    run_id = None if active is None else active.analysis_run_id
    fingerprint = None
    if active is not None:
        fingerprint = _fingerprint(store, active.analysis_run_id)
    reasons = stale_reasons(
        sequence_revision=int(sequence["revision"]),
        sequence_revision_at_generation=int(track["sequence_revision_at_generation"]),
        transcript_run_id=run_id,
        transcript_analysis_run_id=track["transcript_analysis_run_id"],
        effective_fingerprint=fingerprint,
        stored_fingerprint=track["effective_text_fingerprint"],
    )
    return _present(sequence, track, "stale" if reasons else "ready", reasons)


def generate_captions(store, sequence_id: str) -> dict:
    sequence = _sequence(store, sequence_id)
    active = store.active_transcript(sequence["media_asset_id"])
    if active is None:
        raise NoActiveTranscript(sequence["media_asset_id"])
    words = _words(store, active.analysis_run_id)
    clips = [(int(clip["source_start_us"]), int(clip["source_end_us"])) for clip in sequence["clips"]]
    cues = build_cues(clips, words)
    replace_track(
        store,
        sequence=sequence,
        transcript_run_id=active.analysis_run_id,
        fingerprint=_fingerprint(store, active.analysis_run_id),
        profile=PROFILE_ID,
        cues=cues,
    )
    return caption_state(store, sequence_id)


def edit_cue_text(store, sequence_id: str, cue_id: str, text: str) -> dict:
    cleaned = normalize_caption_text(text)
    _sequence(store, sequence_id)
    updated = set_manual_text(store, sequence_id, cue_id, cleaned)
    if updated is None:
        raise CaptionRejected("unknown_caption_cue", "That caption is not on the current track.")
    return caption_state(store, sequence_id)


def reset_cue_text(store, sequence_id: str, cue_id: str) -> dict:
    _sequence(store, sequence_id)
    updated = set_manual_text(store, sequence_id, cue_id, None)
    if updated is None:
        raise CaptionRejected("unknown_caption_cue", "That caption is not on the current track.")
    return caption_state(store, sequence_id)


def export_captions(store, sequence_id: str, subtitle_format: str) -> dict:
    if subtitle_format not in {"srt", "vtt"}:
        raise CaptionRejected("invalid_caption_format", "Choose SRT or WebVTT.")
    state = caption_state(store, sequence_id)
    if state["status"] == "absent":
        raise CaptionRejected("captions_missing", "Generate captions before exporting.")
    if state["status"] == "stale":
        raise CaptionRejected(
            "captions_stale",
            "Regenerate captions before exporting. Manual edits on the old track may not carry over.",
        )
    sequence = _sequence(store, sequence_id)
    track = load_current_track(store, sequence_id)
    if track is None:
        raise CaptionRejected("captions_missing", "Generate captions before exporting.")
    body = render_srt(track["cues"]) if subtitle_format == "srt" else render_vtt(track["cues"])
    export_token = str(uuid.uuid4())
    relative = f"exports/captions/{export_token}.{subtitle_format}"
    destination = _project_path(store.root, relative)
    publish_text(destination, body)
    asset_id = store.add_media_asset(
        display_name=f"captions-{export_token[:8]}.{subtitle_format}",
        role="sidecar",
        location_kind="project",
        relative_path=relative,
        byte_size=destination.stat().st_size,
        container=subtitle_format,
    )
    clips = [(int(clip["source_start_us"]), int(clip["source_end_us"])) for clip in sequence["clips"]]
    fingerprint = sequence_fingerprint(int(sequence["source_start_us"]), int(sequence["source_end_us"]), clips)
    export_id = record_export(
        store,
        asset_id=asset_id,
        source_media_asset_id=sequence["media_asset_id"],
        sequence=sequence,
        fingerprint=fingerprint,
        track=track,
        subtitle_format=subtitle_format,
    )
    stored = load_export(store, export_id)
    if stored is None:
        raise CaptionRejected("invalid_caption_export", "The subtitle export was not stored.")
    return stored


def _sequence(store, sequence_id: str) -> dict:
    try:
        return store.load_editorial_sequence_by_id(sequence_id)
    except ProjectDatabaseInvalid as exc:
        raise CaptionRejected("unknown_sequence", "That sequence is not in this project.") from exc


def _words(store, run_id: str) -> list[CaptionWord]:
    return [
        CaptionWord(
            word_id=word.word_id,
            sequence=word.sequence,
            effective_text=word.effective_text,
            start_us=word.start_us,
            end_us=word.end_us,
        )
        for word in store.load_words(run_id)
    ]


def _fingerprint(store, run_id: str) -> str:
    from amix.amix_engine.captions.segment import effective_text_fingerprint

    return effective_text_fingerprint(_words(store, run_id))


def _project_path(root: Path, relative: str) -> Path:
    destination = (root / relative).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise CaptionRejected("invalid_caption_export", "The subtitle file must stay inside the project.")
    return destination


def _absent(sequence: dict) -> dict:
    return {
        "sequence_id": sequence["sequence_id"],
        "media_asset_id": sequence["media_asset_id"],
        "purpose": sequence["purpose"],
        "status": "absent",
        "track_id": None,
        "revision": None,
        "profile": None,
        "transcript_analysis_run_id": None,
        "effective_text_fingerprint": None,
        "sequence_revision_at_generation": None,
        "stale_reasons": [],
        "cues": [],
    }


def _present(sequence: dict, track: dict, status: str, reasons: list[str]) -> dict:
    return {
        "sequence_id": sequence["sequence_id"],
        "media_asset_id": sequence["media_asset_id"],
        "purpose": sequence["purpose"],
        "status": status,
        "track_id": track["track_id"],
        "revision": track["revision"],
        "profile": track["generation_profile"],
        "transcript_analysis_run_id": track["transcript_analysis_run_id"],
        "effective_text_fingerprint": track["effective_text_fingerprint"],
        "sequence_revision_at_generation": track["sequence_revision_at_generation"],
        "stale_reasons": reasons,
        "cues": track["cues"],
    }
