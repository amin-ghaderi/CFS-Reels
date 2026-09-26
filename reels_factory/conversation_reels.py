from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .cursor_ai import extract_json_payload, invoke_cursor_agent, resolve_model_id
from .plan_validate import estimated_duration, validate_semantic_plan
from .refine import resolve_video_path
from .transcribe import flatten_words
from .utils import parse_timestamp, read_json, ts, write_json
from .word_align import snap_range_to_words

ALLOWED_ROLES = {"hook", "setup", "response", "counterpoint", "development", "payoff"}
FORBIDDEN_ROLES = {"question_core", "answer_core", "central_answer"}
TARGET_MIN = 30.0
TARGET_MAX = 120.0
PREFERRED_MIN = 45.0
PREFERRED_MAX = 90.0
CEILING = 150.0
SIGNAL_WEIGHT = {
    "strong_hook": 3,
    "disagreement": 3,
    "surprising_statement": 3,
    "memorable_punchline": 3,
    "funny_exchange": 2,
    "emotional_honesty": 2,
    "counterintuitive_point": 2,
    "culturally_relevant": 2,
    "topical": 2,
    "strong_personal_opinion": 2,
    "clean_argument": 2,
    "relatable_situation": 1,
}


def thread_opportunity_score(thread: dict) -> float:
    score = 0.0
    for signal in thread.get("reel_signals") or []:
        score += SIGNAL_WEIGHT.get(str(signal), 1)
    if thread.get("hook_candidates"):
        score += 1.5 * min(3, len(thread["hook_candidates"]))
    if thread.get("disagreement_or_tension"):
        score += 2
    if thread.get("humor_or_punchline"):
        score += 2
    if thread.get("surprising_statement"):
        score += 2
    span = parse_timestamp(thread.get("end") or 0) - parse_timestamp(thread.get("start") or 0)
    if 40 <= span <= 400:
        score += 1
    return score


def _words_from_normalized(normalized: dict) -> list[dict]:
    words = []
    for seg in normalized.get("segments") or []:
        for word in seg.get("words") or []:
            words.append({
                "text": word.get("text") or word.get("normalized_text") or "",
                "start": float(word["start"]),
                "end": float(word["end"]),
                "probability": float(word.get("probability") or 0.0),
                "segment_id": int(word.get("segment_id", seg.get("segment_id", 0))),
            })
    if words:
        return words
    return flatten_words({"segments": [
        {
            "id": seg.get("segment_id"),
            "start": seg["start"],
            "end": seg["end"],
            "words": [{"start": seg["start"], "end": seg["end"], "word": seg.get("clean_text") or ""}],
        }
        for seg in normalized.get("segments") or []
    ]})


def repair_boundaries(plan: dict, words: list[dict]) -> dict:
    segs = []
    notes = list(plan.get("integrity_notes") or [])
    for seg in plan.get("segments") or []:
        start = parse_timestamp(seg["start"])
        end = parse_timestamp(seg["end"])
        snapped_s, snapped_e = snap_range_to_words(start, end, words)
        if abs(snapped_s - start) > 0.02 or abs(snapped_e - end) > 0.02:
            notes.append(
                f"snapped {seg.get('role')} {ts(start)}-{ts(end)} -> {ts(snapped_s)}-{ts(snapped_e)}"
            )
        row = dict(seg)
        row["start"] = ts(snapped_s)
        row["end"] = ts(snapped_e)
        segs.append(row)
    plan = dict(plan)
    plan["segments"] = segs
    plan["integrity_notes"] = notes
    return plan


def evaluate_conversation_integrity(plan: dict) -> dict:
    segs = plan.get("segments") or []
    roles = [str(s.get("role") or "").strip().lower() for s in segs]
    duration = estimated_duration(plan) if segs else 0.0
    pb = plan.get("playback_check") if isinstance(plan.get("playback_check"), dict) else {}
    qa_roles = [r for r in roles if r in FORBIDDEN_ROLES]
    unknown_roles = [r for r in roles if r and r not in ALLOWED_ROLES]
    flags = {
        "opening_understandable": bool(pb.get("opening_understandable", "hook" in roles or "setup" in roles)),
        "responses_have_triggers": bool(pb.get("responses_have_triggers", True)),
        "references_resolved": bool(pb.get("references_resolved", True)),
        "sentence_boundaries_clean": bool(pb.get("sentence_boundaries_clean", True)),
        "speaker_changes_make_sense": bool(pb.get("speaker_changes_make_sense", True)),
        "payoff_preserved": bool(pb.get("payoff_preserved", "payoff" in roles or duration < 40)),
        "meaning_unchanged": bool(pb.get("meaning_unchanged", True)),
        "duration_le_150": duration <= CEILING + 0.05,
        "no_qa_roles": not qa_roles,
        "roles_allowed": not unknown_roles,
        "has_segments": bool(segs),
    }
    failed = [k for k, ok in flags.items() if not ok]
    status = "PASS" if not failed else "FAIL"
    return {
        "duration_s": round(duration, 3),
        "integrity_status": status,
        "failed": failed,
        **flags,
    }


def _slice_blocks(blocks: list[dict], start: float, end: float) -> list[dict]:
    rows = []
    for block in blocks:
        if float(block["end"]) < start - 1.0 or float(block["start"]) > end + 1.0:
            continue
        rows.append({
            "block_id": block.get("block_id"),
            "speaker": block.get("speaker"),
            "start": ts(block["start"]),
            "end": ts(block["end"]),
            "text": block.get("text"),
            "confidence": block.get("confidence"),
        })
    return rows


def mine_and_synthesize_reels(
    video: Path,
    cfg: dict,
    *,
    root: Path,
    force: bool = False,
    invoke=None,
) -> dict:
    video = resolve_video_path(video, root)
    stem = video.stem
    map_path = Path(cfg["paths"].get("conversation_maps") or (root / "data" / "conversation_maps")) / f"{stem}.conversation_map.json"
    speakers_path = Path(cfg["paths"].get("speakers") or (root / "data" / "speakers")) / f"{stem}.speakers.json"
    normalized_path = Path(cfg["paths"]["normalized_transcripts"]) / f"{stem}.normalized.json"
    out_dir = Path(cfg["paths"].get("conversation_plans") or (root / "data" / "conversation_plans"))
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / f"{stem}.reel_candidates.json"
    if index_path.is_file() and not force:
        print(f"[conversation-reels] cache hit {index_path}")
        return read_json(index_path)

    conversation = read_json(map_path)
    speakers = read_json(speakers_path)
    normalized = read_json(normalized_path)
    words = _words_from_normalized(normalized)
    prompt_prefix = (root / "prompts" / "conversation_reel_editor.md").read_text(encoding="utf-8")
    aicfg = (cfg.get("ai_editor") or {}).get("qa_reel_editor") or {}
    model = resolve_model_id(str(aicfg.get("model") or "grok-4.6"), kind="semantic")
    caller = invoke or invoke_cursor_agent

    ranked_threads = sorted(
        conversation.get("threads") or [],
        key=thread_opportunity_score,
        reverse=True,
    )
    candidates = []
    skipped = []
    for idx, thread in enumerate(ranked_threads, 1):
        cid = f"{stem}.R{idx:02d}"
        start = parse_timestamp(thread.get("start") or 0)
        end = parse_timestamp(thread.get("end") or 0)
        payload = {
            "candidate_id": cid,
            "thread": thread,
            "blocks": _slice_blocks(speakers.get("blocks") or [], start, end),
            "words": [
                {"start": ts(w["start"]), "end": ts(w["end"]), "text": w["text"]}
                for w in words
                if w["end"] >= start - 2 and w["start"] <= end + 2
            ][:2500],
            "duration_rules": {
                "normal": [TARGET_MIN, TARGET_MAX],
                "preferred": [PREFERRED_MIN, PREFERRED_MAX],
                "ceiling": CEILING,
            },
        }
        prompt = prompt_prefix + "\n\n## Thread packet\n\n" + json.dumps(payload, ensure_ascii=False)
        try:
            with tempfile.TemporaryDirectory(prefix="reels_conv_edit_") as td:
                output = caller(prompt, model=model, mode="ask", workspace=Path(td), timeout=700)
            data = extract_json_payload(output)
        except Exception as exc:
            skipped.append({"candidate_id": cid, "thread_id": thread.get("thread_id"), "reason": str(exc)})
            continue
        if isinstance(data, dict) and data.get("skip"):
            skipped.append({"candidate_id": cid, "thread_id": thread.get("thread_id"), "reason": data.get("reason")})
            continue
        plan = dict(data)
        plan["candidate_id"] = cid
        plan["reel_id"] = cid.replace(".", "_")
        plan["source_video"] = str(Path("data/inbox") / video.name).replace("\\", "/")
        plan["thread_id"] = thread.get("thread_id")
        plan["topic"] = plan.get("topic") or thread.get("topic")
        plan = repair_boundaries(plan, words)
        try:
            validate_semantic_plan(plan, source_duration=float(normalized.get("duration") or 0) or None)
        except Exception as exc:
            plan.setdefault("integrity_notes", []).append(f"plan validation: {exc}")
        gate = evaluate_conversation_integrity(plan)
        plan["integrity_status"] = gate["integrity_status"]
        plan["integrity"] = gate
        plan["source_duration_s"] = round(end - start, 3)
        plan["synthesized_duration_s"] = gate["duration_s"]
        plan["opportunity_score"] = thread_opportunity_score(thread)
        plan["avoid_hook_repeat"] = True
        write_json(out_dir / f"{cid}.json", plan)
        candidates.append({
            "candidate_id": cid,
            "discussion_thread": thread.get("thread_id"),
            "topic": plan.get("topic"),
            "hook": plan.get("hook"),
            "speakers_involved": plan.get("speakers_involved") or thread.get("participating_speakers"),
            "source_duration_s": plan["source_duration_s"],
            "synthesized_duration_s": plan["synthesized_duration_s"],
            "selected_blocks": plan.get("segments") or [],
            "why_it_works": plan.get("why_it_works"),
            "what_was_removed": plan.get("removed") or [],
            "integrity_status": plan["integrity_status"],
            "rank": None,
            "plan": str((out_dir / f"{cid}.json").as_posix()),
        })

    score_by_id = {
        f"{stem}.R{i:02d}": thread_opportunity_score(th)
        for i, th in enumerate(ranked_threads, 1)
    }
    candidates.sort(
        key=lambda c: (
            0 if c["integrity_status"] == "PASS" else 1,
            -score_by_id.get(c["candidate_id"], 0.0),
            c["candidate_id"],
        )
    )
    for i, row in enumerate(candidates, 1):
        row["rank"] = i

    index = {
        "source_video": str(video.as_posix()),
        "kind": "conversation_reel_candidates",
        "rendered": False,
        "candidate_count": len(candidates),
        "skipped": skipped,
        "candidates": candidates,
    }
    write_json(index_path, index)
    print(f"[conversation-reels] wrote {index_path} ({len(candidates)} candidates, not rendered)", flush=True)
    return index
