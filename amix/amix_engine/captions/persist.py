"""Caption track persistence. Transcript rows are not rewritten here."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from amix.amix_engine.storage.models import (
    CaptionCueRow,
    CaptionExportRow,
    CaptionTrackRow,
    MediaAssetRow,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_current_track(store, sequence_id: str) -> dict | None:
    with store._session() as session:
        track = session.scalar(
            select(CaptionTrackRow).where(
                CaptionTrackRow.sequence_id == sequence_id,
                CaptionTrackRow.project_id == store.project_id,
                CaptionTrackRow.superseded_at.is_(None),
            )
        )
        if track is None:
            return None
        cues = session.scalars(
            select(CaptionCueRow)
            .where(CaptionCueRow.track_id == track.id)
            .order_by(CaptionCueRow.order_index, CaptionCueRow.id)
        ).all()
        return _track_view(track, cues)


def replace_track(
    store,
    *,
    sequence: dict,
    transcript_run_id: str,
    fingerprint: str,
    profile: str,
    cues: list,
) -> str:
    store._require_write()
    track_id = str(uuid.uuid4())
    now = _now()
    with store._session() as session:
        current = session.scalar(
            select(CaptionTrackRow).where(
                CaptionTrackRow.sequence_id == sequence["sequence_id"],
                CaptionTrackRow.project_id == store.project_id,
                CaptionTrackRow.superseded_at.is_(None),
            )
        )
        if current is not None:
            current.superseded_at = now
            current.updated_at = now
            session.flush()
        session.add(CaptionTrackRow(
            id=track_id,
            project_id=store.project_id,
            media_asset_id=sequence["media_asset_id"],
            sequence_id=sequence["sequence_id"],
            sequence_revision_at_generation=int(sequence["revision"]),
            transcript_analysis_run_id=transcript_run_id,
            effective_text_fingerprint=fingerprint,
            generation_profile=profile,
            revision=1,
            superseded_at=None,
            created_at=now,
            updated_at=now,
        ))
        session.flush()
        for cue in cues:
            session.add(CaptionCueRow(
                id=str(uuid.uuid4()),
                track_id=track_id,
                order_index=cue.order_index,
                first_word_id=cue.first_word_id,
                last_word_id=cue.last_word_id,
                source_start_us=cue.source_start_us,
                source_end_us=cue.source_end_us,
                sequence_start_us=cue.sequence_start_us,
                sequence_end_us=cue.sequence_end_us,
                generated_text=cue.generated_text,
                manual_text=None,
            ))
        session.commit()
    return track_id


def set_manual_text(store, sequence_id: str, cue_id: str, text: str | None) -> None:
    """Set or clear one cue overlay. The track revision moves only when the value changes."""
    store._require_write()
    with store._session() as session:
        track = session.scalar(
            select(CaptionTrackRow).where(
                CaptionTrackRow.sequence_id == sequence_id,
                CaptionTrackRow.project_id == store.project_id,
                CaptionTrackRow.superseded_at.is_(None),
            )
        )
        if track is None:
            return None
        cue = session.get(CaptionCueRow, cue_id)
        if cue is None or cue.track_id != track.id:
            return None
        if cue.manual_text == text:
            session.rollback()
            return track.id
        cue.manual_text = text
        track.revision = int(track.revision) + 1
        track.updated_at = _now()
        session.commit()
        return track.id


def record_export(
    store,
    *,
    asset_id: str,
    source_media_asset_id: str,
    sequence: dict,
    fingerprint: str,
    track: dict,
    subtitle_format: str,
) -> str:
    store._require_write()
    export_id = str(uuid.uuid4())
    now = _now()
    with store._session() as session:
        asset = session.get(MediaAssetRow, asset_id)
        if asset is None or asset.project_id != store.project_id:
            raise ValueError("subtitle asset was not stored")
        asset.source_media_asset_id = source_media_asset_id
        session.add(CaptionExportRow(
            id=export_id,
            project_id=store.project_id,
            media_asset_id=asset_id,
            source_media_asset_id=source_media_asset_id,
            sequence_id=sequence["sequence_id"],
            sequence_purpose=sequence["purpose"],
            sequence_revision=int(sequence["revision"]),
            sequence_fingerprint=fingerprint,
            caption_track_id=track["track_id"],
            caption_track_revision=int(track["revision"]),
            transcript_analysis_run_id=track["transcript_analysis_run_id"],
            effective_text_fingerprint=track["effective_text_fingerprint"],
            generation_profile=track["generation_profile"],
            format=subtitle_format,
            created_at=now,
        ))
        session.commit()
    return export_id


def load_export(store, export_id: str) -> dict | None:
    with store._session() as session:
        row = session.get(CaptionExportRow, export_id)
        if row is None or row.project_id != store.project_id:
            return None
        asset = session.get(MediaAssetRow, row.media_asset_id)
        return {
            "export_id": row.id,
            "asset_id": row.media_asset_id,
            "relative_path": None if asset is None else asset.relative_path,
            "role": None if asset is None else asset.role,
            "source_media_asset_id": row.source_media_asset_id,
            "sequence_id": row.sequence_id,
            "sequence_purpose": row.sequence_purpose,
            "sequence_revision": int(row.sequence_revision),
            "sequence_fingerprint": row.sequence_fingerprint,
            "caption_track_id": row.caption_track_id,
            "caption_track_revision": int(row.caption_track_revision),
            "transcript_analysis_run_id": row.transcript_analysis_run_id,
            "effective_text_fingerprint": row.effective_text_fingerprint,
            "generation_profile": row.generation_profile,
            "format": row.format,
            "created_at": row.created_at,
        }


def list_exports(store, sequence_id: str) -> list[dict]:
    with store._session() as session:
        rows = session.scalars(
            select(CaptionExportRow)
            .where(
                CaptionExportRow.sequence_id == sequence_id,
                CaptionExportRow.project_id == store.project_id,
            )
            .order_by(CaptionExportRow.created_at, CaptionExportRow.id)
        ).all()
        found = []
        for row in rows:
            asset = session.get(MediaAssetRow, row.media_asset_id)
            found.append({
                "export_id": row.id,
                "asset_id": row.media_asset_id,
                "relative_path": None if asset is None else asset.relative_path,
                "role": None if asset is None else asset.role,
                "source_media_asset_id": row.source_media_asset_id,
                "sequence_id": row.sequence_id,
                "sequence_purpose": row.sequence_purpose,
                "sequence_revision": int(row.sequence_revision),
                "sequence_fingerprint": row.sequence_fingerprint,
                "caption_track_id": row.caption_track_id,
                "caption_track_revision": int(row.caption_track_revision),
                "transcript_analysis_run_id": row.transcript_analysis_run_id,
                "effective_text_fingerprint": row.effective_text_fingerprint,
                "generation_profile": row.generation_profile,
                "format": row.format,
                "created_at": row.created_at,
            })
        return found


def _track_view(track: CaptionTrackRow, cues: list[CaptionCueRow]) -> dict:
    return {
        "track_id": track.id,
        "media_asset_id": track.media_asset_id,
        "sequence_id": track.sequence_id,
        "sequence_revision_at_generation": int(track.sequence_revision_at_generation),
        "transcript_analysis_run_id": track.transcript_analysis_run_id,
        "effective_text_fingerprint": track.effective_text_fingerprint,
        "generation_profile": track.generation_profile,
        "revision": int(track.revision),
        "created_at": track.created_at,
        "updated_at": track.updated_at,
        "cues": [_cue_view(cue) for cue in cues],
    }


def _cue_view(cue: CaptionCueRow) -> dict:
    manual = cue.manual_text
    return {
        "cue_id": cue.id,
        "order_index": int(cue.order_index),
        "first_word_id": cue.first_word_id,
        "last_word_id": cue.last_word_id,
        "source_start_us": int(cue.source_start_us),
        "source_end_us": int(cue.source_end_us),
        "sequence_start_us": int(cue.sequence_start_us),
        "sequence_end_us": int(cue.sequence_end_us),
        "generated_text": cue.generated_text,
        "manual_text": manual,
        "effective_text": manual if manual else cue.generated_text,
    }
