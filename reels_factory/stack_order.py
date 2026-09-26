"""Once-per-Reel static 9:16 stack order. Not active-speaker switching."""
from __future__ import annotations

from pathlib import Path

from .composition import STACK_ORDER_916
from .utils import parse_timestamp, read_json

SPEAKERS = ("speaker_a", "speaker_b", "speaker_c")
UNKNOWN = "unknown"
# Frozen show layout: TOP B, MIDDLE C, BOTTOM A
DEFAULT_STACK = tuple(STACK_ORDER_916)
UNKNOWN_SHARE_MAX = 0.15
FIRST_SHARE_MIN = 0.55
LEAD_MIN_S = 8.0
SILENT_MAX_S = 1.0
TIE_GAP_S = 2.0


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _ranges_from_plan(plan: dict | None, clips: list[dict] | None) -> list[tuple[float, float]]:
    segments = (plan or {}).get("segments") or []
    if segments:
        return [(parse_timestamp(row["start"]), parse_timestamp(row["end"])) for row in segments]
    rows = []
    for clip in clips or []:
        start = float(clip["start"])
        end = float(clip["end"])
        if end > start:
            rows.append((start, end))
    return rows


def speaking_durations(
    blocks: list[dict],
    ranges: list[tuple[float, float]],
) -> dict[str, float]:
    """Actual overlapped speaking time. Not block counts."""
    dur = {key: 0.0 for key in (*SPEAKERS, UNKNOWN)}
    if not ranges:
        return dur
    for block in blocks or []:
        start = float(block["start"])
        end = float(block["end"])
        overlapped = 0.0
        for lo, hi in ranges:
            overlapped += _overlap(start, end, lo, hi)
        if overlapped <= 0.0:
            continue
        label = str(block.get("speaker") or UNKNOWN)
        if label not in dur:
            label = UNKNOWN
        dur[label] += overlapped
    return {key: round(dur[key], 3) for key in dur}


def _remaining_default_order(middle: str) -> tuple[str, str]:
    leftover = [name for name in DEFAULT_STACK if name != middle]
    return leftover[0], leftover[1]


def choose_static_stack_order(durations: dict[str, float]) -> dict:
    a = float(durations.get("speaker_a") or 0.0)
    b = float(durations.get("speaker_b") or 0.0)
    c = float(durations.get("speaker_c") or 0.0)
    unknown = float(durations.get(UNKNOWN) or 0.0)
    attributed = a + b + c
    speech = attributed + unknown
    unknown_share = (unknown / speech) if speech > 0 else 0.0
    ranked = sorted(
        (("speaker_a", a), ("speaker_b", b), ("speaker_c", c)),
        key=lambda item: (-item[1], DEFAULT_STACK.index(item[0])),
    )
    first_name, first_s = ranked[0]
    second_name, second_s = ranked[1]
    third_name, third_s = ranked[2]
    gap_1_2 = first_s - second_s
    first_share = (first_s / attributed) if attributed > 0 else 0.0
    payload = {
        "speaker_a_seconds": round(a, 3),
        "speaker_b_seconds": round(b, 3),
        "speaker_c_seconds": round(c, 3),
        "unknown_seconds": round(unknown, 3),
        "unknown_share": round(unknown_share, 4),
        "decision": "fallback",
        "final_stack_order": list(DEFAULT_STACK),
        "reason": "",
    }

    def _finish(decision: str, order: tuple[str, str, str], reason: str) -> dict:
        payload["decision"] = decision
        payload["final_stack_order"] = list(order)
        payload["reason"] = reason
        return payload

    if attributed <= 0:
        return _finish("fallback", DEFAULT_STACK, "no attributed speech; frozen B/C/A")

    dominant_ok = (
        unknown_share < UNKNOWN_SHARE_MAX
        and unknown < gap_1_2
        and (first_share >= FIRST_SHARE_MIN or gap_1_2 >= LEAD_MIN_S)
    )
    if not dominant_ok:
        reasons = []
        if unknown_share >= UNKNOWN_SHARE_MAX:
            reasons.append(f"unknown_share {unknown_share:.1%} >= 15%")
        if unknown >= gap_1_2:
            reasons.append(f"unknown {unknown:.2f}s >= first/second gap {gap_1_2:.2f}s")
        if first_share < FIRST_SHARE_MIN and gap_1_2 < LEAD_MIN_S:
            reasons.append(
                f"first share {first_share:.1%} < 55% and lead {gap_1_2:.2f}s < 8s"
            )
        return _finish("fallback", DEFAULT_STACK, "; ".join(reasons) + "; frozen B/C/A")

    remaining_silent = second_s < SILENT_MAX_S and third_s < SILENT_MAX_S
    remaining_tied = abs(second_s - third_s) < TIE_GAP_S
    if remaining_silent or remaining_tied:
        top, bottom = _remaining_default_order(first_name)
        why = "second/third effectively silent" if remaining_silent else "second/third tied"
        return _finish(
            "partial_dynamic",
            (top, first_name, bottom),
            f"{first_name} dominant; {why}; remaining keep default relative order",
        )

    return _finish(
        "dynamic",
        (second_name, first_name, third_name),
        f"{first_name} most, {second_name} second, {third_name} least",
    )


def resolve_reel_stack_order(
    source: Path,
    cfg: dict,
    plan: dict | None,
    clips: list[dict] | None,
) -> dict:
    speakers_dir = Path(cfg.get("paths", {}).get("speakers") or "")
    path = speakers_dir / f"{Path(source).stem}.speakers.json" if speakers_dir else Path()
    if not path.is_file():
        result = choose_static_stack_order({})
        result["reason"] = f"no speaker file ({path.name}); frozen B/C/A"
        result["decision"] = "fallback"
        result["final_stack_order"] = list(DEFAULT_STACK)
        return result
    payload = read_json(path)
    ranges = _ranges_from_plan(plan, clips)
    durations = speaking_durations(payload.get("blocks") or [], ranges)
    return choose_static_stack_order(durations)


def log_stack_decision(decision: dict) -> None:
    print(
        "[stack] "
        f"A={decision['speaker_a_seconds']:.3f}s "
        f"B={decision['speaker_b_seconds']:.3f}s "
        f"C={decision['speaker_c_seconds']:.3f}s "
        f"unknown={decision['unknown_seconds']:.3f}s "
        f"unknown_share={decision['unknown_share']:.1%} "
        f"decision={decision['decision']} "
        f"final_stack_order={decision['final_stack_order']} "
        f"reason={decision['reason']}",
        flush=True,
    )
