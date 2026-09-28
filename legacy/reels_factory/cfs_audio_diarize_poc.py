"""Classical audio diarization proof for one CFS range.

This is not the silence-gap visual labeler. It segments the mixed program
audio by speaker timbre, then maps those anonymous clusters onto the three
fixed participants with visually confirmed solo anchors.

It assigns one speaker per time window. Overlapping speech is not represented.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.cluster.vq import kmeans2
from scipy.fft import dct

SR = 16000
N_SPEAKERS = 3
FRAME = 400
HOP = 160
N_MELS = 40
N_MFCC = 13
WIN_S = 0.75
HOP_S = 0.25
MIN_RUN_S = 0.80
SAME_TURN_GAP_S = 1.50
# Held out of cluster-to-person mapping. Used only as a later checkpoint.
HELDOUT = (3060.0, 3115.0)
# Solo frames inspected on the fixed tiles, outside the held-out checkpoint.
# One mouth is open. The other two are closed. A hand on a closed mouth is not speech.
VISUAL_SOLOS = (
    (3146.0, "speaker_b"),
    (3152.0, "speaker_b"),
    (3158.0, "speaker_b"),
    (3188.0, "speaker_a"),
    (3364.0, "speaker_c"),
    (3542.0, "speaker_c"),
    (3555.0, "speaker_c"),
)


def load_audio(source: Path, start: float, duration: float) -> np.ndarray:
    import subprocess

    raw = subprocess.check_output(
        [
            "ffmpeg", "-v", "error",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", str(source),
            "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-",
        ]
    )
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if audio.size < SR:
        raise RuntimeError("audio extract was too short")
    return audio


def _mel_bank(n_fft: int) -> np.ndarray:
    def hz_mel(hz: float) -> float:
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def mel_hz(mel: float) -> float:
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    n_freq = n_fft // 2 + 1
    freqs = np.linspace(0, SR / 2, n_freq)
    mels = np.linspace(hz_mel(60), hz_mel(7600), N_MELS + 2)
    points = np.array([mel_hz(m) for m in mels])
    bank = np.zeros((N_MELS, n_freq), dtype=np.float64)
    for i in range(N_MELS):
        left, center, right = points[i], points[i + 1], points[i + 2]
        rising = (freqs - left) / max(center - left, 1e-6)
        falling = (right - freqs) / max(right - center, 1e-6)
        bank[i] = np.clip(np.minimum(rising, falling), 0.0, None)
        total = bank[i].sum()
        if total > 0:
            bank[i] /= total
    return bank


def frame_features(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MFCC without the energy coefficient, plus spectral centroid, per 10 ms frame."""
    if audio.size < FRAME:
        raise RuntimeError("audio shorter than one frame")
    count = 1 + (audio.size - FRAME) // HOP
    index = np.arange(FRAME)[None, :] + HOP * np.arange(count)[:, None]
    windowed = audio[index] * np.hanning(FRAME)
    spec = np.abs(np.fft.rfft(windowed, axis=1)).astype(np.float64)
    power = spec * spec
    mel = np.maximum(power @ _mel_bank(FRAME).T, 1e-10)
    cep = dct(np.log(mel), type=2, norm="ortho", axis=1)[:, 1:N_MFCC]
    freqs = np.fft.rfftfreq(FRAME, 1.0 / SR)
    centroid = (freqs * spec).sum(axis=1) / np.maximum(spec.sum(axis=1), 1e-8)
    rms = np.sqrt(np.mean(windowed * windowed, axis=1))
    return cep.astype(np.float32), centroid.astype(np.float32), rms.astype(np.float32)


def window_matrix(cep: np.ndarray, centroid: np.ndarray, rms: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frames_per = max(1, int(WIN_S * SR / HOP))
    hop_frames = max(1, int(HOP_S * SR / HOP))
    rows = []
    times = []
    energy = []
    last = len(cep) - frames_per
    for start in range(0, max(1, last + 1), hop_frames):
        part = cep[start:start + frames_per]
        cen = centroid[start:start + frames_per]
        if part.shape[0] < frames_per // 2:
            break
        rows.append(np.concatenate([part.mean(axis=0), part.std(axis=0), [cen.mean()]]))
        times.append((start + part.shape[0] / 2) * HOP / SR)
        energy.append(float(np.median(rms[start:start + frames_per])))
    return np.vstack(rows), np.array(times), np.array(energy)


def _cluster(features: np.ndarray) -> np.ndarray:
    """Three clusters, seeded from mutually distant windows.

    Random k-means lands two centers inside the longest voice and never
    gives the shortest voice its own cluster. Farthest-point seeds avoid that.
    """
    clean = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    mean = clean.mean(axis=0)
    std = clean.std(axis=0)
    std[std < 1e-6] = 1.0
    scaled = (clean - mean) / std
    best_labels = None
    best_sep = -1.0
    rng = np.random.default_rng(1)
    n = len(scaled)
    for _ in range(8):
        first = int(rng.integers(0, n))
        dist_first = np.sum((scaled - scaled[first]) ** 2, axis=1)
        second = int(np.argmax(dist_first))
        dist_second = np.sum((scaled - scaled[second]) ** 2, axis=1)
        third = int(np.argmax(np.minimum(dist_first, dist_second)))
        init = np.vstack([scaled[first], scaled[second], scaled[third]])
        try:
            centroids, labels = kmeans2(scaled, init, minit="matrix", missing="warn", iter=40)
        except Exception:
            continue
        labels = labels.astype(int)
        sizes = [int((labels == k).sum()) for k in range(N_SPEAKERS)]
        if min(sizes) < 40:
            continue
        sep = min(
            float(np.sum((centroids[i] - centroids[j]) ** 2))
            for i in range(N_SPEAKERS)
            for j in range(i + 1, N_SPEAKERS)
        )
        if sep > best_sep:
            best_sep = sep
            best_labels = labels
    if best_labels is None:
        raise RuntimeError("speaker clustering failed")
    return best_labels


def _smooth(labels: np.ndarray, speech: np.ndarray) -> np.ndarray:
    """Drop sub-second label flickers. Do not require a silence gap to keep a change."""
    out = labels.copy()
    out[~speech] = -1
    changed = True
    while changed:
        changed = False
        start = 0
        while start < len(out):
            end = start + 1
            while end < len(out) and out[end] == out[start]:
                end += 1
            dur = (end - start) * HOP_S
            if out[start] >= 0 and dur < MIN_RUN_S:
                left = out[start - 1] if start else -1
                right = out[end] if end < len(out) else -1
                replacement = left if left >= 0 else right
                if replacement >= 0 and replacement != out[start]:
                    out[start:end] = replacement
                    changed = True
            start = end
    return out


def segments_from_labels(labels: np.ndarray, times: np.ndarray, origin: float) -> list[dict]:
    segments = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            if labels[start] >= 0:
                t0 = float(times[start] - WIN_S / 2)
                t1 = float(times[i - 1] + WIN_S / 2)
                segments.append({
                    "start": round(origin + max(0.0, t0), 3),
                    "end": round(origin + t1, 3),
                    "anonymous_speaker": f"SPEAKER_{labels[start]:02d}",
                    "cluster": int(labels[start]),
                })
            start = i
    return _merge_touching(segments)


def _merge_touching(segments: list[dict]) -> list[dict]:
    if not segments:
        return []
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg["anonymous_speaker"] == prev["anonymous_speaker"] and seg["start"] - prev["end"] <= 0.35:
            prev["end"] = seg["end"]
        else:
            merged.append(dict(seg))
    return merged


def diarize(audio: np.ndarray, origin: float) -> tuple[list[dict], dict]:
    cep, centroid, rms = frame_features(audio)
    features, times, energy = window_matrix(cep, centroid, rms)
    speech = energy >= np.percentile(energy, 18)
    if int(speech.sum()) < N_SPEAKERS * 4:
        raise RuntimeError("not enough speech windows to diarize")
    labels = np.full(len(times), -1, dtype=int)
    labels[speech] = _cluster(features[speech])
    labels = _smooth(labels, speech)
    segments = segments_from_labels(labels, times, origin)
    # Confidence is how separated this window's cluster is from the other speech.
    # A window far from a single timbre still gets one label. Overlap is not modeled.
    for seg in segments:
        seg["confidence"] = None
        seg.pop("cluster", None)
    meta = {
        "window_s": WIN_S,
        "hop_s": HOP_S,
        "min_run_s": MIN_RUN_S,
        "speech_windows": int(speech.sum()),
        "silence_windows": int((~speech).sum()),
        "overlap_supported": False,
    }
    return segments, meta


def _majority_speaker(mouth: dict[str, float]) -> str | None:
    ranked = sorted(mouth, key=lambda key: mouth[key], reverse=True)
    best, second = ranked[0], ranked[1]
    best_v = float(mouth[best])
    second_v = float(mouth[second])
    if best_v < 2.0:
        return None
    if second_v > 0.35 and best_v < second_v * 1.45:
        return None
    return best


def _segment_at(segments: list[dict], t: float) -> dict | None:
    hits = [seg for seg in segments if seg["start"] <= t < seg["end"]]
    if not hits:
        return None
    return max(hits, key=lambda seg: seg["end"] - seg["start"])


def map_clusters(segments: list[dict], source: Path) -> dict:
    """Map each anonymous cluster using several solo anchors outside the held-out window.

    Mouth motion is one vote per long segment. A hand resting on a closed mouth
    can outscore the person who is actually speaking, so inspected solo frames
    are recorded as separate votes and can outvote that false mouth score.
    """
    from .cfs_offline_verify import measure_mouth_window, open_verifier

    by_speaker: dict[str, list[dict]] = {}
    for seg in segments:
        if seg["end"] - seg["start"] < 3.0:
            continue
        if seg["end"] > HELDOUT[0] and seg["start"] < HELDOUT[1]:
            continue
        by_speaker.setdefault(seg["anonymous_speaker"], []).append(seg)
    cap, detector = open_verifier(source)
    mapping = {}
    try:
        for name, rows in by_speaker.items():
            rows = sorted(rows, key=lambda seg: seg["end"] - seg["start"], reverse=True)[:4]
            votes = []
            for seg in rows:
                span = seg["end"] - seg["start"]
                samples = []
                for frac in (0.25, 0.50, 0.75):
                    t = seg["start"] + span * frac
                    mouth = measure_mouth_window(cap, detector, t - 0.6, t + 0.6, samples=4)
                    samples.append({"t": round(t, 3), "mouth": mouth, "speaker": _majority_speaker(mouth)})
                counted_samples = [s["speaker"] for s in samples if s["speaker"]]
                who = None
                if counted_samples:
                    lead = max(set(counted_samples), key=counted_samples.count)
                    if counted_samples.count(lead) >= 2:
                        who = lead
                votes.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "kind": "mouth_motion",
                    "samples": samples,
                    "visual_speaker": who,
                })
            for t, person in VISUAL_SOLOS:
                if HELDOUT[0] <= t < HELDOUT[1]:
                    continue
                host = _segment_at(segments, t)
                if host is None or host["anonymous_speaker"] != name:
                    continue
                votes.append({
                    "start": t,
                    "end": t,
                    "kind": "inspected_solo_frame",
                    "visual_speaker": person,
                })
            counted = [v["visual_speaker"] for v in votes if v["visual_speaker"]]
            chosen = None
            if counted:
                winner = max(set(counted), key=counted.count)
                if counted.count(winner) >= 2 and counted.count(winner) > len(counted) / 2:
                    chosen = winner
            mapping[name] = {"speaker": chosen, "anchors": votes}
    finally:
        cap.release()
    used = [row["speaker"] for row in mapping.values() if row["speaker"]]
    if len(used) != len(set(used)):
        for name, row in mapping.items():
            if used.count(row["speaker"]) > 1:
                row["speaker"] = None
                row["rejected"] = "two anonymous clusters mapped to the same participant"
    return mapping


def assign_word(word: dict, segments: list[dict], mapping: dict) -> str:
    start = float(word["start"])
    end = float(word["end"])
    dur = max(0.02, end - start)
    totals: dict[str, float] = {}
    for seg in segments:
        overlap = min(end, seg["end"]) - max(start, seg["start"])
        if overlap <= 0:
            continue
        who = mapping.get(seg["anonymous_speaker"], {}).get("speaker") or "unknown"
        totals[who] = totals.get(who, 0.0) + overlap
    if not totals:
        return "unknown"
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    best_name, best = ranked[0]
    if best < dur * 0.55:
        return "unknown"
    if len(ranked) > 1 and ranked[1][1] >= best * 0.75:
        return "unknown"
    return best_name


def build_turns(words: list[dict]) -> list[dict]:
    turns = []
    current = None
    for word in words:
        speaker = word["speaker"]
        start, end = float(word["start"]), float(word["end"])
        gap = None if current is None else start - current["end"]
        same = (
            current is not None
            and speaker == current["speaker"]
            and gap is not None
            and gap <= SAME_TURN_GAP_S
        )
        if same:
            current["end"] = end
            current["words"].append(word["text"])
            continue
        if current is not None:
            turns.append(current)
        current = {
            "start": start,
            "end": end,
            "speaker": speaker,
            "words": [word["text"]],
        }
    if current is not None:
        turns.append(current)
    for i, turn in enumerate(turns, start=1):
        turn["turn_id"] = f"T{i:04d}"
        turn["start"] = round(turn["start"], 3)
        turn["end"] = round(turn["end"], 3)
        turn["duration_s"] = round(turn["end"] - turn["start"], 3)
        turn["word_count"] = len(turn["words"])
        turn["text"] = " ".join(turn["words"])
        del turn["words"]
    return turns
