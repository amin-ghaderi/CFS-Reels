from __future__ import annotations

from pathlib import Path

from .ai_normalizer import normalize_transcript
from .conversation_map import map_conversation
from .conversation_reels import mine_and_synthesize_reels
from .refine import resolve_video_path
from .speakers import attribute_speakers
from .transcribe import transcribe_longform
from .utils import read_json


def analyze_conversation(
    video: Path,
    cfg: dict,
    *,
    root: Path,
    force: bool = False,
    language: str | None = "fa",
    audio_wav: Path | None = None,
    invoke=None,
) -> dict:
    """Transcribe → normalize (word links) → speakers → discussion map → Reel plans.

    Does not render video. Does not modify framing profiles.
    """
    video = resolve_video_path(video, root)
    stem = video.stem
    transcripts = Path(cfg["paths"]["transcripts"])
    transcripts.mkdir(parents=True, exist_ok=True)
    out_json = transcripts / f"{stem}.transcript.json"
    out_srt = transcripts / f"{stem}.srt"
    words_json = transcripts / f"{stem}.words.json"

    if out_json.is_file() and words_json.is_file() and not force:
        print(f"[analyze] transcript cache hit {out_json}")
        transcript = read_json(out_json)
    else:
        tcfg = dict(cfg.get("transcription") or {})
        if language:
            tcfg["language"] = language
        cfg = dict(cfg)
        cfg["transcription"] = tcfg
        transcript = transcribe_longform(
            video,
            out_json,
            out_srt,
            cfg,
            audio_wav=audio_wav,
            words_json=words_json,
            language=language,
        )

    normalized = normalize_transcript(video, cfg, root=root, force=force, invoke=invoke)

    speakers_dir = Path(cfg["paths"].get("speakers") or (root / "data" / "speakers"))
    speakers_dir.mkdir(parents=True, exist_ok=True)
    speakers_json = speakers_dir / f"{stem}.speakers.json"
    profile_path = Path(cfg["paths"]["framing_profiles"]) / f"{stem}.json"
    if speakers_json.is_file() and not force:
        speakers = read_json(speakers_json)
        print(f"[analyze] speakers cache hit {speakers_json}")
    else:
        profile = read_json(profile_path)
        words = read_json(words_json).get("words") if words_json.is_file() else []
        if not words:
            from .transcribe import flatten_words
            words = flatten_words(transcript)
        speakers = attribute_speakers(video, words, profile, out_json=speakers_json)

    conversation = map_conversation(video, cfg, root=root, force=force, invoke=invoke)
    candidates = mine_and_synthesize_reels(video, cfg, root=root, force=force, invoke=invoke)
    return {
        "transcript": str(out_json),
        "words": str(words_json),
        "normalized": str(Path(cfg["paths"]["normalized_transcripts"]) / f"{stem}.normalized.json"),
        "speakers": str(speakers_json),
        "conversation_map": str(
            Path(cfg["paths"].get("conversation_maps") or (root / "data" / "conversation_maps"))
            / f"{stem}.conversation_map.json"
        ),
        "reel_candidates": str(
            Path(cfg["paths"].get("conversation_plans") or (root / "data" / "conversation_plans"))
            / f"{stem}.reel_candidates.json"
        ),
        "thread_count": conversation.get("thread_count"),
        "candidate_count": candidates.get("candidate_count"),
        "rendered": False,
        "framing_profile_untouched": str(profile_path),
        "speaker_counts": speakers.get("counts"),
        "normalized_corrections": normalized.get("correction_count"),
    }
