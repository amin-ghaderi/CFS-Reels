# Render CFS03 editorial drafts. Frozen framing. No packaging.
from __future__ import annotations

import json
import sys
from pathlib import Path

from reels_factory.config import load_config
from reels_factory.render import render_reel, resolve_transcript_for_plan
from reels_factory.stack_order import resolve_reel_stack_order
from reels_factory.utils import parse_timestamp, read_json, ts, write_json

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ("CFS03.R01", "CFS03.R02", "CFS03.R03")
BREATH = 0.10
MAX_BREATH = 0.14


def load_words() -> list[dict]:
    raw = read_json(ROOT / "data" / "transcripts" / "CFS03.words.json")
    if isinstance(raw, dict):
        return raw.get("words") or []
    return list(raw)


def interior_words(start: float, end: float, words: list[dict]) -> list[dict]:
    """Words that begin before the cut ends and finish after it starts. No pad-into-neighbor."""
    return [
        w for w in words
        if float(w["start"]) < end - 0.005 and float(w["end"]) > start + 0.005
    ]


def breath_snap(start: float, end: float, words: list[dict]) -> tuple[float, float]:
    inside = interior_words(start, end, words)
    if not inside:
        return start, end
    snapped_s = float(inside[0]["start"])
    snapped_e = float(inside[-1]["end"])
    earlier = [w for w in words if float(w["end"]) <= snapped_s + 0.001]
    later = [w for w in words if float(w["start"]) >= snapped_e - 0.001]
    if earlier:
        prev_end = max(float(w["end"]) for w in earlier)
        gap = snapped_s - prev_end
        if gap >= 0.06:
            snapped_s -= min(BREATH, gap * 0.45, max(0.0, gap - 0.03))
    if later:
        next_start = min(float(w["start"]) for w in later)
        gap = next_start - snapped_e
        if gap >= 0.08:
            snapped_e += min(MAX_BREATH, 0.08, max(0.0, gap - 0.03))
    return snapped_s, snapped_e


def first_last_words(start: float, end: float, words: list[dict]) -> tuple[dict | None, dict | None]:
    inside = interior_words(start, end, words)
    if not inside:
        return None, None
    return inside[0], inside[-1]


def prepare_plan(stem: str, words: list[dict], work: Path) -> tuple[Path, dict]:
    src = ROOT / "data" / "conversation_plans" / f"{stem}.json"
    plan = read_json(src)
    notes = list(plan.get("integrity_notes") or [])
    new_segs = []
    for seg in plan["segments"]:
        start = parse_timestamp(seg["start"])
        end = parse_timestamp(seg["end"])
        snapped_s, snapped_e = breath_snap(start, end, words)
        first, last = first_last_words(snapped_s, snapped_e, words)
        row = dict(seg)
        row["start"] = ts(snapped_s)
        row["end"] = ts(snapped_e)
        row["first_word"] = None if not first else first.get("text")
        row["last_word"] = None if not last else last.get("text")
        if abs(snapped_s - start) > 0.015 or abs(snapped_e - end) > 0.015:
            notes.append(
                f"word/breath snap {seg.get('role')} {ts(start)}-{ts(end)} -> {ts(snapped_s)}-{ts(snapped_e)}"
            )
        new_segs.append(row)
    plan["segments"] = new_segs
    plan["integrity_notes"] = notes
    plan["draft"] = True
    plan["packaging"] = False
    out = work / f"{stem}.draft_plan.json"
    write_json(out, plan)
    return out, plan


def draft_duration_s(path: Path, plan: dict) -> float:
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        n = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        cap.release()
        if n > 0 and fps > 0:
            return round(n / fps, 3)
    except Exception:
        pass
    return round(
        sum(
            parse_timestamp(seg["end"]) - parse_timestamp(seg["start"])
            for seg in plan.get("segments") or []
        ),
        3,
    )


def candidates() -> tuple[str, ...]:
    if len(sys.argv) > 1:
        return tuple(sys.argv[1:])
    return DEFAULT_CANDIDATES


def batch_name(stems: tuple[str, ...]) -> str:
    ids = [stem.split(".")[-1] for stem in stems]
    if len(ids) == 1:
        return f"batch_{ids[0]}.json"
    return f"batch_{ids[0]}_{ids[-1]}.json"


def main() -> None:
    cfg = load_config(ROOT)
    words = load_words()
    stems = candidates()
    drafts_dir = ROOT / "data" / "output" / "CFS03_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    work = drafts_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    summary = []
    batch_path = drafts_dir / batch_name(stems)
    for stem in stems:
        plan_path, plan = prepare_plan(stem, words, work)
        out_path = drafts_dir / f"{stem.replace('.', '_')}_draft.mp4"
        transcript = resolve_transcript_for_plan(plan_path, plan, cfg)
        source = ROOT / (plan.get("source_video") or "data/inbox/CFS03.mp4")
        decision = resolve_reel_stack_order(source, cfg, plan, [])
        print(f"[draft] {stem} -> {out_path} transcript={transcript}", flush=True)
        print(
            f"  stack {decision['decision']} "
            f"A={decision['speaker_a_seconds']:.3f} "
            f"B={decision['speaker_b_seconds']:.3f} "
            f"C={decision['speaker_c_seconds']:.3f} "
            f"unknown={decision['unknown_seconds']:.3f} "
            f"share={decision['unknown_share']:.1%} "
            f"order={decision['final_stack_order']}",
            flush=True,
        )
        for seg in plan["segments"]:
            print(
                f"  cut {seg['role']} {seg['start']}-{seg['end']} "
                f"first={seg.get('first_word')!r} last={seg.get('last_word')!r}",
                flush=True,
            )
        rendered = render_reel(plan_path, transcript, cfg, output_path=out_path)
        duration = draft_duration_s(rendered, plan)
        summary.append({
            "reel_id": plan.get("reel_id") or stem.replace(".", "_"),
            "candidate_id": stem,
            "speaker_a_seconds": decision["speaker_a_seconds"],
            "speaker_b_seconds": decision["speaker_b_seconds"],
            "speaker_c_seconds": decision["speaker_c_seconds"],
            "unknown_seconds": decision["unknown_seconds"],
            "unknown_share": decision["unknown_share"],
            "decision": decision["decision"],
            "final_stack_order": decision["final_stack_order"],
            "reason": decision["reason"],
            "duration": duration,
            "path": str(rendered.as_posix()),
            "cuts": len(plan["segments"]),
        })
        batch_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[draft] wrote {rendered} duration={duration:.3f}s", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
