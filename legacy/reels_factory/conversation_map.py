from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .cursor_ai import extract_json_payload, invoke_cursor_agent, resolve_model_id
from .refine import resolve_video_path
from .utils import parse_timestamp, read_json, ts, write_json

WINDOW_S = 720.0
OVERLAP_S = 45.0
FORBIDDEN_QA = (
    "question_core",
    "answer_core",
    "host/guest",
    "qa_unit",
    "Q&A",
)


def compact_blocks_for_mapper(speaker_payload: dict, normalized: dict) -> list[dict]:
    clean_by_seg = {}
    for seg in normalized.get("segments") or []:
        clean_by_seg[int(seg["segment_id"])] = str(seg.get("clean_text") or seg.get("raw_text") or "")
    rows = []
    for block in speaker_payload.get("blocks") or []:
        texts = []
        for word in block.get("words") or []:
            sid = int(word.get("segment_id", -1))
            if sid in clean_by_seg and not texts:
                texts.append(clean_by_seg[sid])
        text = (block.get("text") or "").strip()
        if texts:
            text = " ".join(texts) if len(text) < 8 else text
        rows.append({
            "block_id": block.get("block_id"),
            "speaker": block.get("speaker") or "unknown",
            "start": ts(block["start"]),
            "end": ts(block["end"]),
            "confidence": block.get("confidence"),
            "text": text,
        })
    return rows


def _windows(rows: list[dict]) -> list[list[dict]]:
    if not rows:
        return []
    start0 = parse_timestamp(rows[0]["start"])
    end_last = parse_timestamp(rows[-1]["end"])
    windows = []
    t = start0
    while t < end_last:
        lo, hi = t, t + WINDOW_S
        chunk = [
            row for row in rows
            if parse_timestamp(row["end"]) >= lo and parse_timestamp(row["start"]) <= hi
        ]
        if chunk:
            windows.append(chunk)
        t += WINDOW_S - OVERLAP_S
    return windows or [rows]


def _merge_threads(chunks: list[list[dict]]) -> list[dict]:
    merged: list[dict] = []
    for group in chunks:
        for thread in group:
            if not isinstance(thread, dict):
                continue
            start = parse_timestamp(thread.get("start") or 0)
            end = parse_timestamp(thread.get("end") or 0)
            topic = str(thread.get("topic") or "").strip().lower()
            overlap = None
            for existing in merged:
                es = parse_timestamp(existing.get("start") or 0)
                ee = parse_timestamp(existing.get("end") or 0)
                et = str(existing.get("topic") or "").strip().lower()
                if min(end, ee) - max(start, es) > 20 and (topic == et or topic in et or et in topic):
                    overlap = existing
                    break
            if overlap is None:
                merged.append(dict(thread))
                continue
            if start < parse_timestamp(overlap["start"]):
                overlap["start"] = thread["start"]
            if end > parse_timestamp(overlap["end"]):
                overlap["end"] = thread["end"]
    for i, thread in enumerate(merged, 1):
        thread["thread_id"] = f"T{i:02d}"
    return merged


def render_conversation_map_markdown(payload: dict) -> str:
    lines = [
        f"# Conversation map — {payload.get('source_video', '')}",
        "",
        "This is a discussion-thread map. It is not a Q&A program map.",
        "",
        f"- duration: {ts(payload.get('duration') or 0)}",
        f"- threads: {len(payload.get('threads') or [])}",
        f"- model: {payload.get('mapper_model')}",
        "",
    ]
    for thread in payload.get("threads") or []:
        lines.append(f"## {thread.get('thread_id')} — {thread.get('topic', '')}")
        lines.append(f"- span: {thread.get('start')} → {thread.get('end')}")
        lines.append(f"- speakers: {', '.join(thread.get('participating_speakers') or [])}")
        if thread.get("short_summary"):
            lines.append(f"- summary: {thread.get('short_summary')}")
        if thread.get("main_claim"):
            lines.append(f"- main claim: {thread.get('main_claim')}")
        if thread.get("disagreement_or_tension"):
            lines.append(f"- tension: {thread.get('disagreement_or_tension')}")
        if thread.get("hook_candidates"):
            lines.append(f"- hooks: {len(thread.get('hook_candidates') or [])}")
        lines.append("")
    return "\n".join(lines)


def map_conversation(
    video: Path,
    cfg: dict,
    *,
    root: Path,
    force: bool = False,
    invoke=None,
) -> dict:
    video = resolve_video_path(video, root)
    stem = video.stem
    speakers_path = Path(cfg["paths"].get("speakers") or (root / "data" / "speakers")) / f"{stem}.speakers.json"
    normalized_path = Path(cfg["paths"]["normalized_transcripts"]) / f"{stem}.normalized.json"
    if not speakers_path.is_file():
        raise FileNotFoundError(f"Speaker attribution not found: {speakers_path}")
    if not normalized_path.is_file():
        raise FileNotFoundError(f"Normalized transcript not found: {normalized_path}")
    out_dir = Path(cfg["paths"].get("conversation_maps") or (root / "data" / "conversation_maps"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{stem}.conversation_map.json"
    out_md = out_dir / f"{stem}.conversation_map.md"
    if out_json.is_file() and not force:
        print(f"[conversation-map] cache hit {out_json}")
        return read_json(out_json)

    speakers = read_json(speakers_path)
    normalized = read_json(normalized_path)
    rows = compact_blocks_for_mapper(speakers, normalized)
    prompt_prefix = (root / "prompts" / "conversation_mapper.md").read_text(encoding="utf-8")
    aicfg = (cfg.get("ai_editor") or {}).get("program_mapper") or {}
    model = resolve_model_id(str(aicfg.get("model") or "grok-4.6"), kind="semantic")
    caller = invoke or invoke_cursor_agent
    chunk_threads: list[list[dict]] = []
    windows = _windows(rows)
    print(f"[conversation-map] {len(rows)} blocks in {len(windows)} windows", flush=True)
    for idx, window in enumerate(windows):
        payload = {
            "source_video": str(video.name),
            "window": idx + 1,
            "window_count": len(windows),
            "blocks": window,
        }
        prompt = prompt_prefix + "\n\n## Attributed transcript\n\n" + json.dumps(payload, ensure_ascii=False)
        try:
            with tempfile.TemporaryDirectory(prefix="reels_conv_map_") as td:
                output = caller(prompt, model=model, mode="ask", workspace=Path(td), timeout=700)
            data = extract_json_payload(output)
            threads = data.get("threads") if isinstance(data, dict) else data
            chunk_threads.append(list(threads or []))
            print(f"[conversation-map] window {idx+1}/{len(windows)} threads={len(threads or [])}", flush=True)
        except Exception as exc:
            print(f"[conversation-map] window {idx+1} failed ({exc})", flush=True)
            chunk_threads.append([])

    threads = _merge_threads(chunk_threads)
    result = {
        "source_video": str(video.as_posix()),
        "kind": "discussion_threads",
        "not_qa": True,
        "duration": normalized.get("duration"),
        "mapper_model": model,
        "thread_count": len(threads),
        "threads": threads,
    }
    write_json(out_json, result)
    out_md.write_text(render_conversation_map_markdown(result), encoding="utf-8")
    print(f"[conversation-map] wrote {out_json} ({len(threads)} threads)", flush=True)
    return result
