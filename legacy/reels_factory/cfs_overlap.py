"""Secondary overlap layer for the offline 16:9 director.

The diarized turn timeline still owns the floor. This module only answers
whether two or more participants are articulating at the same time.

Motion is measured on a tight lip band between the mouth corners.
A hand on the chin and a head turn are rejected. One cluster per audio
window is unchanged, and turns are not rewritten.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .cfs_multicam_16x9 import TILES
from .faces import CachedYunet, ensure_yunet_model
from .speaker_resolver_v2 import SPEAKERS, crop_tile

SAMPLE_FPS = 8
WINDOW_S = 1.25
STEP_S = 0.25
# Simultaneous lip motion required inside one window before it can count.
SIMULTANEOUS_S = 0.75
# A single window is not an overlap. The next window must agree.
MIN_WINDOWS = 2
MERGE_GAP_S = 0.75
LIP_ON = 4.2
FRAME_W = 1920
FRAME_H = 1080


def _clip(value: int, limit: int) -> int:
    return max(0, min(limit, value))


def _band(gray: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> np.ndarray | None:
    h, w = gray.shape[:2]
    xa, xb = _clip(int(x0), w), _clip(int(x1), w)
    ya, yb = _clip(int(y0), h), _clip(int(y1), h)
    if xb - xa < 8 or yb - ya < 6:
        return None
    patch = gray[ya:yb, xa:xb]
    return cv2.resize(patch, (32, 16), interpolation=cv2.INTER_AREA)


def _lip_parts(gray: np.ndarray, face) -> tuple[np.ndarray, np.ndarray, np.ndarray, float] | None:
    """Tight lips, the band below them, and the upper face.

    The band below the lip line is where a hand on the chin lives.
    It is used only to reject that motion, not to score speech.
    """
    if face is None or not face.landmarks or len(face.landmarks) < 5:
        return None
    mouth_r, mouth_l = face.landmarks[3], face.landmarks[4]
    nose = face.landmarks[2]
    cx = (mouth_r[0] + mouth_l[0]) / 2.0
    cy = (mouth_r[1] + mouth_l[1]) / 2.0
    mw = max(12.0, abs(mouth_r[0] - mouth_l[0]))
    lip = _band(gray, cx - mw * 0.40, cy - mw * 0.16, cx + mw * 0.40, cy + mw * 0.20)
    chin = _band(gray, cx - mw * 0.40, cy + mw * 0.55, cx + mw * 0.40, cy + mw * 1.20)
    upper = _band(gray, cx - mw * 0.40, nose[1] - mw * 0.70, cx + mw * 0.40, nose[1] - mw * 0.08)
    if lip is None or upper is None:
        return None
    if chin is None:
        chin = np.zeros_like(lip)
    return lip, chin, upper, cy


def _motion(prev: np.ndarray | None, cur: np.ndarray | None) -> float:
    if prev is None or cur is None or prev.shape != cur.shape:
        return 0.0
    return float(np.mean(cv2.absdiff(prev, cur)))


def _speech_score(prev, cur, prev_cy: float | None, cy: float) -> float:
    if prev is None:
        return 0.0
    if prev_cy is not None and abs(cy - prev_cy) > 10.0:
        return 0.0
    lip = _motion(prev[0], cur[0])
    chin = _motion(prev[1], cur[1])
    upper = _motion(prev[2], cur[2])
    # A hand on the chin moves the band under the mouth at least as much as the lips.
    if chin > 2.0 and chin > lip * 1.15:
        return 0.0
    # A head turn moves the upper face with the mouth.
    if lip < upper + 1.4:
        return 0.0
    return max(0.0, lip - 0.45 * upper)


def collect_lip_activity(video: Path, origin: float, duration: float) -> dict:
    """One forward decode. Returns per-frame lip scores and mixed-audio energy."""
    from .cfs_audio_diarize_poc import SR, load_audio

    model = ensure_yunet_model()
    if model is None:
        raise RuntimeError("YuNet face model is required for overlap detection")
    detector = CachedYunet(model, score_threshold=0.5)
    audio = load_audio(video, origin, duration)
    frame_bytes = FRAME_W * FRAME_H * 3
    cmd = [
        "ffmpeg", "-v", "error",
        "-ss", f"{origin:.3f}", "-t", f"{duration:.3f}",
        "-i", str(video),
        "-vf", f"fps={SAMPLE_FPS}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    import subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    scores = []
    times = []
    audio_rms = []
    prev = {key: None for key in SPEAKERS}
    prev_cy = {key: None for key in SPEAKERS}
    index = 0
    assert proc.stdout is not None
    try:
        while True:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(FRAME_H, FRAME_W, 3)
            t = origin + index / SAMPLE_FPS
            row = []
            for key in SPEAKERS:
                tile = crop_tile(frame, TILES[key])
                gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (3, 3), 0)
                faces = detector.detect(tile)
                face = max(faces, key=lambda f: f.w * f.h) if faces else None
                parts = _lip_parts(gray, face)
                if parts is None:
                    row.append(0.0)
                    prev[key] = None
                    prev_cy[key] = None
                    continue
                lip, chin, upper, cy = parts
                row.append(_speech_score(prev[key], (lip, chin, upper), prev_cy[key], cy))
                prev[key] = (lip, chin, upper)
                prev_cy[key] = cy
            a0 = int((t - origin) * SR)
            a1 = min(len(audio), a0 + int(SR / SAMPLE_FPS))
            chunk = audio[a0:a1] if a1 > a0 else audio[0:0]
            rms = float(np.sqrt(np.mean(chunk * chunk))) if chunk.size else 0.0
            scores.append(row)
            times.append(t)
            audio_rms.append(rms)
            index += 1
            if index % 800 == 0:
                print(f"overlap frames {index}", flush=True)
    finally:
        proc.stdout.close()
        proc.wait()
    return {
        "origin": origin,
        "fps": SAMPLE_FPS,
        "times": np.asarray(times, dtype=np.float64),
        "scores": np.asarray(scores, dtype=np.float32),
        "audio_rms": np.asarray(audio_rms, dtype=np.float32),
    }


def _window_hits(scores: np.ndarray, audio: np.ndarray, audio_gate: float) -> list[dict]:
    n = len(scores)
    win = max(2, int(round(WINDOW_S * SAMPLE_FPS)))
    step = max(1, int(round(STEP_S * SAMPLE_FPS)))
    need = max(2, int(round(SIMULTANEOUS_S * SAMPLE_FPS)))
    hits = []
    for start in range(0, max(1, n - win + 1), step):
        part = scores[start:start + win]
        if len(part) < win // 2:
            break
        on = part >= LIP_ON
        simultaneous = on.sum(axis=1) >= 2
        if int(simultaneous.sum()) < need:
            continue
        if float(np.median(audio[start:start + win])) < audio_gate:
            continue
        active = []
        for i, key in enumerate(SPEAKERS):
            both = on[:, i] & simultaneous
            if int(both.sum()) >= need:
                active.append(key)
        if len(active) < 2:
            continue
        hits.append({
            "i0": start,
            "i1": start + len(part),
            "speakers": active,
        })
    return hits


def _regions_from_hits(activity: dict, hits: list[dict]) -> list[dict]:
    if not hits:
        return []
    times = activity["times"]
    scores = activity["scores"]
    audio = activity["audio_rms"]
    groups: list[list[dict]] = [[hits[0]]]
    for hit in hits[1:]:
        prev = groups[-1][-1]
        gap_frames = hit["i0"] - prev["i0"]
        gap_s = gap_frames / SAMPLE_FPS
        if gap_s <= STEP_S * 1.6:
            groups[-1].append(hit)
        else:
            groups.append([hit])
    regions = []
    for group in groups:
        if len(group) < MIN_WINDOWS:
            continue
        i0 = group[0]["i0"]
        i1 = group[-1]["i1"]
        start = float(times[i0])
        end = float(times[min(len(times) - 1, i1 - 1)] + 1.0 / SAMPLE_FPS)
        counts = {key: 0 for key in SPEAKERS}
        for hit in group:
            for key in hit["speakers"]:
                counts[key] += 1
        speakers = [key for key in SPEAKERS if counts[key] >= max(1, len(group) // 2)]
        if len(speakers) < 2:
            continue
        span = scores[i0:i1]
        means = {key: float(span[:, i].mean()) if len(span) else 0.0 for i, key in enumerate(SPEAKERS)}
        weaker = min(means[key] for key in speakers)
        # A listener's hand or a one-word backchannel can cross the frame test.
        # Both mouths have to stay active across the whole region.
        if weaker < 5.5:
            continue
        confidence = round(float(np.clip(0.42 + 0.07 * weaker, 0.42, 0.93)), 3)
        pair = " + ".join(speakers)
        regions.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "speakers_active": speakers,
            "duration": round(end - start, 3),
            "confidence": confidence,
            "kind": "overlap",
            "evidence": {
                "mouth_activity_a": round(means["speaker_a"], 3),
                "mouth_activity_b": round(means["speaker_b"], 3),
                "mouth_activity_c": round(means["speaker_c"], 3),
                "audio_activity": round(float(audio[i0:i1].mean()) if i1 > i0 else 0.0, 5),
            },
            "reason": (
                f"{pair} show sustained lip articulation together for {end - start:.2f}s "
                f"while the mixed audio is active. Floor labels are not changed."
            ),
        })
    return _merge_regions(regions)


def _merge_regions(regions: list[dict]) -> list[dict]:
    if not regions:
        return []
    merged = [dict(regions[0])]
    for region in regions[1:]:
        prev = merged[-1]
        if region["start"] - prev["end"] <= MERGE_GAP_S:
            prev["end"] = region["end"]
            prev["duration"] = round(prev["end"] - prev["start"], 3)
            names = list(dict.fromkeys(prev["speakers_active"] + region["speakers_active"]))
            prev["speakers_active"] = [key for key in SPEAKERS if key in names]
            prev["confidence"] = round(max(prev["confidence"], region["confidence"]), 3)
            for key, value in region["evidence"].items():
                prev["evidence"][key] = round((prev["evidence"][key] + value) / 2.0, 3 if key.startswith("mouth") else 5)
            prev["reason"] = (
                f"{' + '.join(prev['speakers_active'])} stay in the same overlap. "
                f"A short gap was joined so the wide shot does not flicker."
            )
            continue
        merged.append(dict(region))
    return [row for row in merged if row["duration"] >= 2.5]


def overlaps_from_activity(activity: dict) -> tuple[list[dict], dict]:
    audio = activity["audio_rms"]
    positive = audio[audio > 0]
    audio_gate = float(np.percentile(positive, 25)) if positive.size else 0.0
    hits = _window_hits(activity["scores"], audio, audio_gate)
    regions = _regions_from_hits(activity, hits)
    meta = {
        "sample_fps": SAMPLE_FPS,
        "window_s": WINDOW_S,
        "step_s": STEP_S,
        "simultaneous_s": SIMULTANEOUS_S,
        "min_windows": MIN_WINDOWS,
        "merge_gap_s": MERGE_GAP_S,
        "lip_on": LIP_ON,
        "audio_gate": round(audio_gate, 5),
        "frames": int(len(activity["times"])),
        "group_reaction": (
            "Laughter is not labeled as speech overlap. "
            "No separate group-energy event was detected on this range."
        ),
    }
    return regions, meta


def detect_overlaps(video: Path, origin: float, duration: float) -> tuple[list[dict], dict]:
    return overlaps_from_activity(collect_lip_activity(video, origin, duration))
