"""Offline audio-visual speaker resolver for CFS03.

Reads the original attribution and writes a new timeline.
Does not modify CFS03.speakers.json, the Virtual Director, or Reels.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .faces import CachedYunet, ensure_yunet_model

SPEAKERS = ("speaker_a", "speaker_b", "speaker_c")
TILES = {
    "speaker_a": (52, 24, 896, 504),
    "speaker_b": (972, 24, 896, 504),
    "speaker_c": (512, 552, 896, 504),
}
BACKCHANNELS = {
    "آره", "اره", "بله", "دقیقا", "دقیقاً", "هوم", "خب", "آها", "اها",
}


def crop_tile(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    fh, fw = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x0 + w), min(fh, y0 + h)
    tile = frame[y0:y1, x0:x1]
    if tile.size == 0:
        return tile
    return cv2.resize(tile, (448, 252), interpolation=cv2.INTER_AREA)


def _clip(value: int, limit: int) -> int:
    return max(0, min(limit, value))


def _patches(tile: np.ndarray, detector: CachedYunet) -> tuple[np.ndarray, np.ndarray, str] | None:
    """Return (mouth gray, upper-face gray, method) or None."""
    if tile.size == 0:
        return None
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    faces = detector.detect(tile)
    face = max(faces, key=lambda f: f.w * f.h) if faces else None
    if face is not None and face.landmarks and len(face.landmarks) >= 5:
        mouth_r, mouth_l = face.landmarks[3], face.landmarks[4]
        nose = face.landmarks[2]
        cx = (mouth_r[0] + mouth_l[0]) / 2.0
        cy = (mouth_r[1] + mouth_l[1]) / 2.0
        mw = max(14.0, abs(mouth_r[0] - mouth_l[0]))
        x0, x1 = _clip(int(cx - mw * 0.95), w), _clip(int(cx + mw * 0.95), w)
        y0, y1 = _clip(int(cy - mw * 0.35), h), _clip(int(cy + mw * 0.50), h)
        ux0, ux1 = x0, x1
        uy1 = _clip(int(nose[1] + mw * 0.15), h)
        uy0 = _clip(int(nose[1] - mw * 0.55), h)
        method = "landmarks"
    elif face is not None and face.h > 20:
        x0 = _clip(int(face.x + face.w * 0.22), w)
        x1 = _clip(int(face.x + face.w * 0.78), w)
        y0 = _clip(int(face.y + face.h * 0.58), h)
        y1 = _clip(int(face.y + face.h * 0.92), h)
        ux0, ux1 = x0, x1
        uy0 = _clip(int(face.y + face.h * 0.28), h)
        uy1 = _clip(int(face.y + face.h * 0.55), h)
        method = "face_box"
    else:
        x0, x1 = int(w * 0.34), int(w * 0.66)
        y0, y1 = int(h * 0.42), int(h * 0.62)
        ux0, ux1 = x0, x1
        uy0, uy1 = int(h * 0.28), int(h * 0.42)
        method = "fixed_prior"
    mouth = gray[y0:y1, x0:x1]
    upper = gray[uy0:uy1, ux0:ux1]
    if mouth.size < 16 or upper.size < 16:
        return None
    return mouth, upper, method


def _fit(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    if image.size == 0:
        return image
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def _speech_delta(prev, cur) -> tuple[float, float] | None:
    """Return (mouth motion, upper-face motion). Head turns move both."""
    if prev is None or cur is None:
        return None
    mouth_a = _fit(prev[0], (48, 32))
    mouth_b = _fit(cur[0], (48, 32))
    upper_a = _fit(prev[1], (48, 24))
    upper_b = _fit(cur[1], (48, 24))
    if min(mouth_a.size, mouth_b.size, upper_a.size, upper_b.size) < 16:
        return None
    mouth = float(np.mean(cv2.absdiff(mouth_a, mouth_b)))
    upper = float(np.mean(cv2.absdiff(upper_a, upper_b)))
    return mouth, upper


def _audio_envelope(path: Path) -> np.ndarray:
    if not path.exists():
        return np.zeros(1, dtype=np.float32)
    env = np.abs(np.fromfile(path, dtype=np.float32))
    # Smooth syllable-scale energy. The source mix is quiet, so keep relative shape.
    kernel = np.ones(8, dtype=np.float32) / 8.0
    return np.convolve(env, kernel, mode="same")


def _rms_at(env: np.ndarray, t: float) -> float:
    i = int(t * 100)
    sl = env[max(0, i - 6): i + 6]
    if sl.size == 0:
        return 0.0
    return float(sl.mean())


def measure_blocks(
    video: Path,
    blocks: list[dict],
    out_path: Path,
    audio_path: Path,
    *,
    samples: int | dict = 6,
) -> dict:
    model = ensure_yunet_model()
    if model is None:
        raise RuntimeError("YuNet face model is required for mouth measurement")
    detector = CachedYunet(model, score_threshold=0.5)
    env = _audio_envelope(audio_path)
    done: dict[str, dict] = {}
    if out_path.exists():
        done = json.loads(out_path.read_text(encoding="utf-8")).get("blocks", {})
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cursor_msec = -1.0
    try:
        for n, block in enumerate(blocks, start=1):
            bid = block["block_id"]
            if bid in done:
                continue
            start, end = float(block["start"]), float(block["end"])
            span = max(0.2, end - start)
            n_samples = samples
            if isinstance(samples, dict):
                n_samples = int(samples.get(bid, 6))
            times = [start + span * (i + 1) / (n_samples + 1) for i in range(n_samples)]
            excess = {k: [] for k in SPEAKERS}
            audio_vals = []
            for t in times:
                target = t * 1000.0
                # One forward pass. Seek only when the next sample is behind
                # the decoder or more than a few seconds ahead.
                if cursor_msec < 0 or target + 40 < cursor_msec or target - cursor_msec > 2500:
                    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, target - 40.0))
                    cursor_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
                guard = 0
                while cursor_msec + 15 < target and guard < 90:
                    if not cap.grab():
                        break
                    guard += 1
                    cursor_msec = cap.get(cv2.CAP_PROP_POS_MSEC) or (cursor_msec + 1000.0 / fps)
                ok, frame_a = cap.read()
                if not ok or frame_a is None:
                    cursor_msec = -1.0
                    continue
                cursor_msec = cap.get(cv2.CAP_PROP_POS_MSEC) or (target + 1000.0 / fps)
                for _ in range(2):
                    if not cap.grab():
                        break
                    cursor_msec += 1000.0 / fps
                ok, frame_b = cap.retrieve()
                if not ok or frame_b is None:
                    cursor_msec = -1.0
                    continue
                audio_vals.append(_rms_at(env, t))
                for key, box in TILES.items():
                    delta = _speech_delta(
                        _patches(crop_tile(frame_a, box), detector),
                        _patches(crop_tile(frame_b, box), detector),
                    )
                    # Mouth motion above upper-face motion is speech-like.
                    # A head turn moves both and cancels out.
                    excess[key].append(0.0 if delta is None else float(delta[0] - delta[1]))
            medians = {
                key: round(float(np.median(vals)), 4) if vals else 0.0
                for key, vals in excess.items()
            }
            corrs = {}
            audio_arr = np.array(audio_vals, dtype=np.float32)
            for key, vals in excess.items():
                series = np.array(vals, dtype=np.float32)
                if series.size < 4 or series.std() < 1e-4 or audio_arr.std() < 1e-8:
                    corrs[key] = 0.0
                else:
                    count = min(series.size, audio_arr.size)
                    corrs[key] = round(float(np.corrcoef(series[:count], audio_arr[:count])[0, 1]), 4)
                    if np.isnan(corrs[key]):
                        corrs[key] = 0.0
            done[bid] = {
                "mouth_activity": medians,
                "audio_correlation": corrs,
                "audio_rms": round(float(audio_arr.mean()) if audio_arr.size else 0.0, 6),
                "samples": {key: len(vals) for key, vals in excess.items()},
            }
            if n % 10 == 0 or n == len(blocks) or n <= 3:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps({"blocks": done}, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(f"[resolver] measured {n}/{len(blocks)}", flush=True)
    finally:
        cap.release()
    out_path.write_text(json.dumps({"blocks": done}, ensure_ascii=False), encoding="utf-8")
    return done


def _tokens(text: str) -> list[str]:
    cleaned = text.replace("،", " ").replace(".", " ").replace("؟", " ").replace("!", " ")
    return [tok.strip("«»\"'") for tok in cleaned.split() if tok.strip("«»\"'")]


def _is_backchannel(text: str, duration: float) -> bool:
    if duration > 2.4:
        return False
    tokens = _tokens(text)
    if not tokens or len(tokens) > 4:
        return False
    return all(tok in BACKCHANNELS for tok in tokens)


def _mouth_rank(mouth: dict) -> tuple[str, str, float, float, float]:
    ranked = sorted(SPEAKERS, key=lambda key: float(mouth.get(key) or 0.0), reverse=True)
    best, second = ranked[0], ranked[1]
    best_v = float(mouth.get(best) or 0.0)
    second_v = float(mouth.get(second) or 0.0)
    ratio = best_v / second_v if second_v > 0.35 else (8.0 if best_v >= 1.5 else 1.0)
    return best, second, best_v, second_v, ratio


def _visual_call(measure: dict) -> tuple[str | None, float, str]:
    mouth = measure.get("mouth_activity") or {}
    corr = measure.get("audio_correlation") or {}
    if not mouth:
        return None, 0.0, "no mouth measurement"
    best, second, best_v, second_v, ratio = _mouth_rank(mouth)
    if best_v >= 2.0 and ratio >= 1.45:
        conf = min(0.93, 0.66 + 0.07 * (ratio - 1.45))
        return best, round(conf, 3), (
            f"Mouth activity leads on {best} ({best_v:.2f} vs {second} {second_v:.2f})."
        )
    corr_best = max(SPEAKERS, key=lambda key: float(corr.get(key) or 0.0))
    corr_v = float(corr.get(corr_best) or 0.0)
    if corr_v >= 0.28 and float(mouth.get(corr_best) or 0.0) >= 1.2 and ratio < 1.45:
        return corr_best, 0.6, (
            f"Mouth levels are close, but audio correlation favors {corr_best} ({corr_v:.2f})."
        )
    return None, 0.0, "mouth activity does not separate the three tiles"


def resolve_blocks(blocks: list[dict], measures: dict) -> list[dict]:
    """Two passes: mouth/audio first, then continuity where the mouth stayed silent."""
    rows = []
    for block in blocks:
        measure = measures.get(block["block_id"], {})
        visual, vconf, vreason = _visual_call(measure)
        original = block["speaker"]
        original_conf = float(block["confidence"])
        strong_contradiction = (
            visual is not None
            and visual != original
            and vconf >= 0.75
        )
        if original in SPEAKERS and original_conf >= 0.85 and not strong_contradiction:
            resolved = original
            confidence = original_conf
            reason = "High-confidence label kept. Mouth evidence does not strongly contradict it."
            if visual == original:
                confidence = max(original_conf, vconf)
                reason = "High-confidence label and mouth activity agree."
            source = "kept_high_confidence"
        elif visual is not None:
            resolved = visual
            confidence = vconf
            reason = vreason
            source = "mouth"
        else:
            resolved = None
            confidence = 0.0
            reason = vreason
            source = "unresolved"
        rows.append({
            "block": block,
            "measure": measure,
            "original": original,
            "original_confidence": original_conf,
            "resolved": resolved,
            "resolution_confidence": confidence,
            "reason": reason,
            "source": source,
        })

    def neighbor(index: int, step: int):
        j = index + step
        if j < 0 or j >= len(rows):
            return None
        other = rows[j]
        gap = (
            float(other["block"]["start"]) - float(rows[index]["block"]["end"])
            if step > 0
            else float(rows[index]["block"]["start"]) - float(other["block"]["end"])
        )
        if gap > 2.0:
            return None
        if other["resolved"] in SPEAKERS:
            return other["resolved"]
        return None

    growing = True
    while growing:
        growing = False
        for index, row in enumerate(rows):
            if row["resolved"] is not None:
                continue
            block = row["block"]
            duration = float(block["end"]) - float(block["start"])
            if _is_backchannel(block.get("text") or "", duration):
                continue
            left = neighbor(index, -1)
            right = neighbor(index, 1)
            if left and left == right:
                row["resolved"] = left
                row["resolution_confidence"] = 0.58
                row["reason"] = (
                    "Mouth activity does not pick a tile. The same speaker holds the floor "
                    "on both sides within two seconds, so this fragment stays in that turn."
                )
                row["source"] = "continuity"
                growing = True
    for row in rows:
        if row["resolved"] is not None:
            continue
        if row["original"] in SPEAKERS and row["original_confidence"] >= 0.7:
            row["resolved"] = row["original"]
            row["resolution_confidence"] = row["original_confidence"]
            row["reason"] = (
                "Mouth activity is inconclusive. The original label stays because nothing "
                "around it agrees on a different speaker."
            )
            row["source"] = "kept_moderate"
        else:
            row["resolved"] = "unknown"
            row["resolution_confidence"] = 0.34
            row["reason"] = (
                "Mouth activity, audio correlation, and the surrounding turns do not "
                "agree on one participant."
            )
            row["source"] = "unknown"
    for row in rows:
        row["backchannel"] = _is_backchannel(
            row["block"].get("text") or "",
            float(row["block"]["end"]) - float(row["block"]["start"]),
        )
        row["label_changed"] = row["resolved"] != row["original"]
    return rows


def build_turns(rows: list[dict]) -> list[dict]:
    turns = []
    current = None
    for row in rows:
        block = row["block"]
        start, end = float(block["start"]), float(block["end"])
        speaker = row["resolved"]
        gap = 0.0 if current is None else start - current["end"]
        same = (
            current is not None
            and speaker == current["resolved_speaker"]
            and gap <= 1.05
            and not row["backchannel"]
            and not current["backchannel"]
        )
        if same:
            current["end"] = end
            current["block_ids"].append(block["block_id"])
            current["original_speakers"].append(row["original"])
            current["text"] = (current["text"] + " " + (block.get("text") or "")).strip()
            current["label_changed"] = current["label_changed"] or row["label_changed"]
            current["resolution_confidence"] = round(
                min(current["resolution_confidence"], row["resolution_confidence"]), 3
            )
            continue
        if current is not None:
            turns.append(current)
        current = {
            "start": start,
            "end": end,
            "resolved_speaker": speaker,
            "original_speakers": [row["original"]],
            "block_ids": [block["block_id"]],
            "text": (block.get("text") or "").strip(),
            "resolution_confidence": row["resolution_confidence"],
            "label_changed": row["label_changed"],
            "backchannel": row["backchannel"],
            "reason": row["reason"],
        }
    if current is not None:
        turns.append(current)
    for i, turn in enumerate(turns, start=1):
        turn["turn_id"] = f"T{i:04d}"
        turn["start"] = round(turn["start"], 3)
        turn["end"] = round(turn["end"], 3)
        turn["duration_s"] = round(turn["end"] - turn["start"], 3)
        originals = [s for s in turn["original_speakers"] if s != turn["resolved_speaker"]]
        turn["original_speaker"] = (
            turn["original_speakers"][0] if len(set(turn["original_speakers"])) == 1
            else "mixed"
        )
        turn["label_changed"] = bool(originals) or turn["label_changed"]
    return turns


def _evidence(row: dict, rows: list[dict], index: int) -> dict:
    measure = row["measure"]
    left = rows[index - 1]["resolved"] if index else None
    right = rows[index + 1]["resolved"] if index + 1 < len(rows) else None
    return {
        "mouth_activity": measure.get("mouth_activity") or {},
        "audio_visual_correlation": {
            "audio_rms": measure.get("audio_rms"),
            "by_speaker": measure.get("audio_correlation") or {},
        },
        "transcript_continuity": row["source"],
        "neighboring_turns": {"before": left, "after": right},
        "conversation_structure": "backchannel" if row["backchannel"] else "floor",
    }


def public_block(row: dict, rows: list[dict], index: int) -> dict:
    block = row["block"]
    return {
        "block_id": block["block_id"],
        "start": round(float(block["start"]), 3),
        "end": round(float(block["end"]), 3),
        "text": block.get("text") or "",
        "original_speaker": row["original"],
        "resolved_speaker": row["resolved"],
        "original_confidence": round(row["original_confidence"], 3),
        "resolution_confidence": round(float(row["resolution_confidence"]), 3),
        "label_changed": row["label_changed"],
        "backchannel": row["backchannel"],
        "evidence": _evidence(row, rows, index),
        "reason": row["reason"],
    }


def _seconds(rows: list[dict], pred) -> float:
    total = 0.0
    for row in rows:
        if pred(row):
            total += float(row["block"]["end"]) - float(row["block"]["start"])
    return total


def _window_seconds(rows: list[dict], lo: float, hi: float, pred) -> float:
    total = 0.0
    for row in rows:
        if not pred(row):
            continue
        start = float(row["block"]["start"])
        end = float(row["block"]["end"])
        total += max(0.0, min(end, hi) - max(start, lo))
    return total


def write_resolution(rows: list[dict], turns: list[dict], out_json: Path, out_md: Path) -> str:
    public_blocks = [public_block(row, rows, i) for i, row in enumerate(rows)]
    payload = {
        "kind": "cfs_speaker_resolution_v2",
        "source_video": "data/inbox/03.mp4",
        "based_on": "data/speakers/CFS03.speakers.json",
        "original_not_modified": True,
        "method": "offline_mouth_activity_plus_audio_correlation_and_turn_continuity",
        "role": "roles/speaker_resolver.md",
        "tiles": {
            "speaker_a": {"x": 52, "y": 24, "w": 896, "h": 504},
            "speaker_b": {"x": 972, "y": 24, "w": 896, "h": 504},
            "speaker_c": {"x": 512, "y": 552, "w": 896, "h": 504},
        },
        "turn_count": len(turns),
        "block_count": len(public_blocks),
        "turns": turns,
        "blocks": public_blocks,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def count(orig, resolved):
        return sum(1 for row in rows if row["original"] == orig and row["resolved"] == resolved)

    names = {"speaker_a": "A", "speaker_b": "B", "speaker_c": "C", "unknown": "unknown"}
    lo, hi = 2360.0, 2960.0
    old_unk = _window_seconds(rows, lo, hi, lambda r: r["original"] == "unknown")
    new_unk = _window_seconds(rows, lo, hi, lambda r: r["resolved"] == "unknown")
    in_window = [
        row for row in rows
        if float(row["block"]["end"]) > lo and float(row["block"]["start"]) < hi and row["label_changed"]
    ]
    corrected = [
        row for row in in_window
        if row["original"] in SPEAKERS and row["resolved"] != row["original"]
    ]
    unknowns_assigned = [
        row for row in in_window
        if row["original"] == "unknown" and row["resolved"] in SPEAKERS
    ]
    focus = [
        row for row in rows
        if float(row["block"]["start"]) <= 2612 and float(row["block"]["end"]) >= 2596
    ]
    lines = [
        "# CFS03 speaker resolution v2",
        "",
        "Original file `data/speakers/CFS03.speakers.json` was not modified.",
        "Resolved timeline: `data/speakers/CFS03.speakers_resolved_v2.json`.",
        "",
        "Mouth activity is the lip region minus upper-face motion, so a head turn does not count as speech. Audio correlation breaks ties when mouth levels are close. A high-confidence label stays unless the mouth evidence strongly contradicts it.",
        "",
        "## Full episode",
        "",
        f"- Original blocks: {len(rows)}",
        f"- Original unknown blocks: {sum(1 for row in rows if row['original'] == 'unknown')}",
        f"- Resolved unknown to A: {count('unknown', 'speaker_a')}",
        f"- Resolved unknown to B: {count('unknown', 'speaker_b')}",
        f"- Resolved unknown to C: {count('unknown', 'speaker_c')}",
        f"- Remaining unknown blocks: {sum(1 for row in rows if row['resolved'] == 'unknown')}",
        f"- Original unknown speech: {_seconds(rows, lambda r: r['original'] == 'unknown'):.1f} s",
        f"- Remaining unknown speech: {_seconds(rows, lambda r: r['resolved'] == 'unknown'):.1f} s",
        "",
        "## Label corrections",
        "",
        f"- A to B: {count('speaker_a', 'speaker_b')}",
        f"- A to C: {count('speaker_a', 'speaker_c')}",
        f"- B to A: {count('speaker_b', 'speaker_a')}",
        f"- B to C: {count('speaker_b', 'speaker_c')}",
        f"- C to A: {count('speaker_c', 'speaker_a')}",
        f"- C to B: {count('speaker_c', 'speaker_b')}",
        "",
        "## 00:39:20–00:49:20",
        "",
        f"- Old unknown speech in the window: {old_unk:.1f} s",
        f"- New unknown speech in the window: {new_unk:.1f} s",
        f"- Old speaker labels corrected in the window: {len(corrected)}",
        f"- Unknown blocks in the window assigned a speaker: {len(unknowns_assigned)}",
        "",
        "### Around 00:43:21",
        "",
    ]
    for row in focus:
        block = row["block"]
        mouth = (row["measure"].get("mouth_activity") or {})
        lines.append(
            f"- `{block['block_id']}` {block['start']:.2f}–{block['end']:.2f} "
            f"original {names.get(row['original'], row['original'])} ({row['original_confidence']:.2f}) "
            f"→ {names.get(row['resolved'], row['resolved'])} ({row['resolution_confidence']:.2f}). "
            f"Mouth A={mouth.get('speaker_a', 0):.2f} B={mouth.get('speaker_b', 0):.2f} "
            f"C={mouth.get('speaker_c', 0):.2f}. {row['reason']}"
        )
    lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)
