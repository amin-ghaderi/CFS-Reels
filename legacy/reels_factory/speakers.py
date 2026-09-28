from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .utils import read_json, ts, write_json

SPEAKERS = ("speaker_a", "speaker_b", "speaker_c")
UNKNOWN = "unknown"
GAP_S = 0.65
MIN_BLOCK_S = 0.35
RATIO_LOCK = 1.45
RATIO_WEAK = 1.22
LIVE_STD = 22.0


def load_speaker_boxes(profile: dict) -> dict[str, tuple[int, int, int, int]]:
    boxes = {}
    for key in SPEAKERS:
        raw = profile[key]
        boxes[key] = (
            int(round(raw["x"])),
            int(round(raw["y"])),
            int(round(raw["w"])),
            int(round(raw["h"])),
        )
    return boxes


def _crop(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    h_img, w_img = frame.shape[:2]
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(w_img, x0 + max(1, w))
    y1 = min(h_img, y0 + max(1, h))
    return frame[y0:y1, x0:x1]


def _mouth_roi(tile: np.ndarray) -> np.ndarray:
    if tile.size == 0:
        return tile
    h, w = tile.shape[:2]
    x0 = int(w * 0.18)
    x1 = int(w * 0.82)
    y0 = int(h * 0.48)
    y1 = int(h * 0.92)
    roi = tile[y0:y1, x0:x1]
    if roi.size == 0:
        return tile
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    return cv2.GaussianBlur(gray, (5, 5), 0)


def _tile_live(tile: np.ndarray) -> bool:
    if tile.size == 0:
        return False
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY) if tile.ndim == 3 else tile
    return float(gray.std()) >= LIVE_STD


def _green_graphic(tile: np.ndarray) -> bool:
    if tile.size == 0:
        return True
    hsv = cv2.cvtColor(tile, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    return float(v.mean()) < 70 and float(s.mean()) > 25 and (35 < float(h.mean()) < 95)


def classify_layout(frame: np.ndarray, boxes: dict[str, tuple[int, int, int, int]]) -> str:
    crops = {key: _crop(frame, box) for key, box in boxes.items()}
    live = {key: _tile_live(im) for key, im in crops.items()}
    if live.get("speaker_c") and not _green_graphic(crops["speaker_c"]):
        return "three"
    if live.get("speaker_a") or live.get("speaker_b"):
        return "two"
    return "unknown"


def _label_for_box(box_key: str, layout: str) -> str:
    if layout == "two" and box_key == "speaker_b":
        return "speaker_c"
    return box_key


def group_speech_blocks(words: list[dict], *, gap_s: float = GAP_S) -> list[dict]:
    ordered = sorted(words, key=lambda w: float(w["start"]))
    blocks: list[dict] = []
    current: list[dict] = []
    for word in ordered:
        if current and float(word["start"]) - float(current[-1]["end"]) > gap_s:
            blocks.append(_finish_block(current, len(blocks)))
            current = []
        current.append(word)
    if current:
        blocks.append(_finish_block(current, len(blocks)))
    return [b for b in blocks if b["end"] - b["start"] >= MIN_BLOCK_S]


def _finish_block(words: list[dict], index: int) -> dict:
    text = " ".join(str(w.get("text") or w.get("word") or "").strip() for w in words).strip()
    return {
        "block_id": f"B{index+1:04d}",
        "start": float(words[0]["start"]),
        "end": float(words[-1]["end"]),
        "text": text,
        "words": words,
        "speaker": UNKNOWN,
        "confidence": 0.0,
    }


def _lookup(blocks: list[dict], t: float) -> int | None:
    for i, block in enumerate(blocks):
        if block["start"] - 0.08 <= t <= block["end"] + 0.08:
            return i
    return None


def _assign(scores: dict[str, float], layout: str) -> tuple[str, float]:
    usable = {k: v for k, v in scores.items() if v > 0.4}
    if layout == "two":
        usable.pop("speaker_b", None)
    if not usable:
        return UNKNOWN, 0.0
    ranked = sorted(usable.items(), key=lambda kv: kv[1], reverse=True)
    best_name, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if second <= 1e-6:
        ratio = 9.0
    else:
        ratio = best / max(second, 1e-6)
    if ratio >= RATIO_LOCK:
        return best_name, min(0.97, 0.55 + 0.12 * ratio)
    if ratio >= RATIO_WEAK:
        return best_name, min(0.72, 0.40 + 0.08 * ratio)
    return UNKNOWN, round(min(0.45, ratio * 0.2), 3)


def attribute_speakers(
    video: Path,
    words: list[dict],
    profile: dict,
    *,
    out_json: Path | None = None,
    frame_step: int = 8,
) -> dict:
    """Visual active-speaker labels mapped onto frozen CFS03 tiles. Read-only profile."""
    boxes = load_speaker_boxes(profile)
    blocks = group_speech_blocks(words)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for speaker attribution: {video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    accum = [{key: [] for key in SPEAKERS} for _ in blocks]
    layouts: list[str] = ["unknown" for _ in blocks]
    prev = {key: None for key in SPEAKERS}
    index = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if index % frame_step != 0:
                index += 1
                continue
            t = index / fps
            bi = _lookup(blocks, t)
            index += 1
            if bi is None:
                prev = {key: None for key in SPEAKERS}
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                continue
            layout = classify_layout(frame, boxes)
            if layout != "unknown":
                layouts[bi] = layout
            for key, box in boxes.items():
                if layout == "two" and key == "speaker_c":
                    continue
                roi = _mouth_roi(_crop(frame, box))
                if roi.size == 0:
                    continue
                last = prev[key]
                if last is not None and last.shape == roi.shape:
                    score = float(np.mean(cv2.absdiff(last, roi)))
                    label = _label_for_box(key, layout if layout != "unknown" else layouts[bi])
                    accum[bi][label].append(score)
                prev[key] = roi
            if n and index % max(1, int(fps * 60)) < frame_step:
                print(f"[speakers] t={ts(t)} blocks={bi+1}/{len(blocks)}", flush=True)
    finally:
        cap.release()

    attributed = []
    counts = {key: 0 for key in (*SPEAKERS, UNKNOWN)}
    for i, block in enumerate(blocks):
        means = {key: float(np.mean(vals)) if vals else 0.0 for key, vals in accum[i].items()}
        layout = layouts[i]
        speaker, conf = _assign(means, layout)
        item = dict(block)
        item["speaker"] = speaker
        item["confidence"] = round(float(conf), 3)
        item["layout"] = layout
        item["motion"] = {k: round(v, 3) for k, v in means.items()}
        attributed.append(item)
        counts[speaker] = counts.get(speaker, 0) + 1

    payload = {
        "source_video": str(Path(video).as_posix()),
        "profile": str(profile.get("source_stem") or "CFS03"),
        "method": "visual_mouth_motion_on_frozen_tiles",
        "speakers": list(SPEAKERS),
        "unknown_policy": "do_not_force_guess",
        "block_count": len(attributed),
        "counts": counts,
        "blocks": attributed,
    }
    if out_json:
        write_json(out_json, payload)
        print(f"[speakers] wrote {out_json} counts={counts}", flush=True)
    return payload
