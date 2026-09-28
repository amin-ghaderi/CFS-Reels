from __future__ import annotations

from pathlib import Path
import subprocess

from .utils import read_json, require_binary, srt_ts, ts, write_json


def _extract_wav(source: Path, start: float, end: float, dest: Path) -> None:
    ffmpeg = require_binary("ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-ss", f"{start:.3f}",
            "-to", f"{end:.3f}",
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(dest),
        ],
        check=True,
    )


def flatten_words(transcript: dict) -> list[dict]:
    """One row per spoken token with segment_id and timing."""
    rows: list[dict] = []
    for seg in transcript.get("segments") or []:
        sid = int(seg.get("id", seg.get("segment_id", 0)))
        for word in seg.get("words") or []:
            text = str(word.get("text") or word.get("word") or "").strip()
            if not text:
                continue
            try:
                start = float(word.get("start", word.get("source_start")))
                end = float(word.get("end", word.get("source_end")))
            except (TypeError, ValueError):
                continue
            rows.append({
                "text": text,
                "start": round(start, 3),
                "end": round(end, 3),
                "probability": float(word.get("probability") or 0.0),
                "segment_id": sid,
            })
    return rows


def write_word_transcript(
    transcript: dict,
    out_json: Path,
    *,
    source_video: str | None = None,
) -> dict:
    words = flatten_words(transcript)
    payload = {
        "source_video": source_video or transcript.get("source_video"),
        "language": transcript.get("language"),
        "duration": transcript.get("duration"),
        "word_count": len(words),
        "segment_count": len(transcript.get("segments") or []),
        "words": words,
    }
    write_json(out_json, payload)
    return payload


def write_srt(segments: list[dict], out_srt: Path) -> None:
    out_srt.parent.mkdir(parents=True, exist_ok=True)
    with out_srt.open("w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, 1):
            f.write(f"{idx}\n{srt_ts(seg['start'])} --> {srt_ts(seg['end'])}\n{seg['text']}\n\n")


def _segment_from_whisper(seg, *, offset: float = 0.0, seg_id: int = 0) -> dict:
    words = []
    for w in (seg.words or []):
        words.append({
            "start": round(float(w.start) + offset, 3),
            "end": round(float(w.end) + offset, 3),
            "word": w.word,
            "text": str(w.word or "").strip(),
            "probability": float(w.probability),
        })
    return {
        "id": seg_id,
        "start": round(float(seg.start) + offset, 3),
        "end": round(float(seg.end) + offset, 3),
        "text": str(seg.text or "").strip(),
        "words": words,
    }


def transcribe(video: Path, out_json: Path, out_srt: Path, cfg: dict) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install -r requirements.txt"
        ) from exc

    tcfg = cfg["transcription"]
    model = WhisperModel(
        tcfg["model"],
        device=tcfg.get("device", "auto"),
        compute_type=tcfg.get("compute_type", "int8"),
    )
    segments_iter, info = model.transcribe(
        str(video),
        language=tcfg.get("language"),
        vad_filter=bool(tcfg.get("vad_filter", True)),
        beam_size=int(tcfg.get("beam_size", 5)),
        word_timestamps=True,
    )

    segments = []
    for i, seg in enumerate(segments_iter):
        segments.append(_segment_from_whisper(seg, offset=0.0, seg_id=i))
        if i and i % 40 == 0:
            print(f"[transcribe] {i} segments  t={ts(segments[-1]['end'])}", flush=True)

    payload = {
        "source_video": str(video.resolve()),
        "language": getattr(info, "language", None),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "duration": float(getattr(info, "duration", 0.0) or (segments[-1]["end"] if segments else 0.0)),
        "segments": segments,
    }
    write_json(out_json, payload)
    write_srt(segments, out_srt)
    words_path = out_json.with_name(f"{Path(out_json).stem.replace('.transcript', '')}.words.json")
    if out_json.name.endswith(".transcript.json"):
        words_path = out_json.with_name(out_json.name.replace(".transcript.json", ".words.json"))
    write_word_transcript(payload, words_path)
    return payload


def _load_whisper_model(cfg: dict):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install -r requirements.txt"
        ) from exc
    tcfg = cfg["transcription"]
    print(
        f"[transcribe] loading model={tcfg['model']} device={tcfg.get('device', 'cpu')} "
        f"compute={tcfg.get('compute_type', 'int8')}",
        flush=True,
    )
    return WhisperModel(
        tcfg["model"],
        device=tcfg.get("device", "cpu"),
        compute_type=tcfg.get("compute_type", "int8"),
    )


def transcribe_window_audio(
    model,
    audio: Path,
    *,
    language: str | None,
    vad_filter: bool,
    beam_size: int,
    offset: float = 0.0,
) -> tuple[list[dict], dict]:
    segments_iter, info = model.transcribe(
        str(audio),
        language=language,
        vad_filter=vad_filter,
        beam_size=beam_size,
        word_timestamps=True,
    )
    segments = []
    for i, seg in enumerate(segments_iter):
        segments.append(_segment_from_whisper(seg, offset=offset, seg_id=i))
    meta = {
        "language": getattr(info, "language", language),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "duration": float(getattr(info, "duration", 0.0) or 0.0),
    }
    return segments, meta


def transcribe_longform(
    video: Path,
    out_json: Path,
    out_srt: Path,
    cfg: dict,
    *,
    audio_wav: Path | None = None,
    words_json: Path | None = None,
    language: str | None = None,
    chunk_s: float = 600.0,
    overlap_s: float = 1.5,
    model=None,
) -> dict:
    """Resumable word-level transcription for long files. Reuses one Whisper model."""
    from .refine import probe_duration

    tcfg = cfg["transcription"]
    lang = language if language is not None else tcfg.get("language")
    duration = probe_duration(Path(audio_wav) if audio_wav else video)
    chunks_dir = out_json.parent / f"{out_json.stem}.chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    source = Path(audio_wav) if audio_wav else video

    if model is None:
        model = _load_whisper_model(cfg)

    starts: list[float] = []
    t = 0.0
    while t < duration - 0.05:
        starts.append(t)
        t += chunk_s

    merged: list[dict] = []
    lang_name = lang
    lang_prob = 0.0
    for idx, start in enumerate(starts):
        end = min(duration, start + chunk_s + (overlap_s if idx < len(starts) - 1 else 0.0))
        chunk_path = chunks_dir / f"chunk_{idx:04d}_{int(start):05d}.json"
        if chunk_path.is_file():
            chunk = read_json(chunk_path)
            print(f"[transcribe] reuse {chunk_path.name} ({len(chunk.get('segments') or [])} segs)", flush=True)
        else:
            wav = chunks_dir / f"chunk_{idx:04d}.wav"
            print(f"[transcribe] chunk {idx+1}/{len(starts)} {ts(start)} -> {ts(end)}", flush=True)
            _extract_wav(source, start, end, wav)
            segs, meta = transcribe_window_audio(
                model,
                wav,
                language=lang,
                vad_filter=bool(tcfg.get("vad_filter", True)),
                beam_size=int(tcfg.get("beam_size", 5)),
                offset=start,
            )
            chunk = {"start": start, "end": end, "segments": segs, **meta}
            write_json(chunk_path, chunk)
            wav.unlink(missing_ok=True)
            print(f"[transcribe]   wrote {len(segs)} segments", flush=True)
        if chunk.get("language"):
            lang_name = chunk.get("language")
            lang_prob = float(chunk.get("language_probability") or lang_prob)
        cutoff = start + 0.12 if idx else -1.0
        for seg in chunk.get("segments") or []:
            if float(seg["start"]) < cutoff:
                continue
            merged.append(seg)

    for i, seg in enumerate(merged):
        seg["id"] = i
        for word in seg.get("words") or []:
            word.setdefault("text", str(word.get("word") or "").strip())

    payload = {
        "source_video": str(video.resolve()),
        "language": lang_name,
        "language_probability": lang_prob,
        "duration": duration,
        "segments": merged,
        "method": "faster_whisper_chunked",
        "word_timestamps": True,
    }
    write_json(out_json, payload)
    write_srt(merged, out_srt)
    words_path = words_json or out_json.with_name(
        out_json.name.replace(".transcript.json", ".words.json")
    )
    if words_path == out_json:
        words_path = out_json.with_name(out_json.stem + ".words.json")
    write_word_transcript(payload, words_path)
    print(f"[transcribe] {len(merged)} segments, {payload_word_count(payload)} words -> {out_json}", flush=True)
    return payload


def payload_word_count(transcript: dict) -> int:
    return len(flatten_words(transcript))
