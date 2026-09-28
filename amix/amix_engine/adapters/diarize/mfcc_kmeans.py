"""MFCC k-means diarization migrated from the CFS proof.

Source of the constants and the clustering rules:
legacy/reels_factory/cfs_audio_diarize_poc.py

That proof is not a generic N-speaker diarizer. This module keeps the proven
three-cluster path. It does not map clusters to participants. Visual anchors,
YuNet, and the offline verifier are not imported.

Audio sample time zero is the start of the decoded source audio. The caller
adds the source container start in integer microseconds after the legacy
millisecond rounding. Playback ``canonical_origin_us`` is not an input.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.cluster.vq import kmeans2
from scipy.fft import dct

from amix.amix_engine.domain.types import DiarizationSegment
from amix.amix_engine.time.clock import legacy_seconds_to_us

SR = 16000
N_SPEAKERS = 3
FRAME = 400
HOP = 160
N_MELS = 40
N_MFCC = 13
WIN_S = 0.75
HOP_S = 0.25
MIN_RUN_S = 0.80
MERGE_GAP_S = 0.35
SPEECH_PERCENTILE = 18
MIN_CLUSTER_SIZE = 40
CLUSTER_ATTEMPTS = 8
CLUSTER_SEED = 1
KMEANS_ITER = 40

FEATURE_CONFIG = {
    "sample_rate": SR,
    "frame_samples": FRAME,
    "hop_samples": HOP,
    "mel_bands": N_MELS,
    "mfcc_coefficients": "1-12",
    "window_s": WIN_S,
    "window_hop_s": HOP_S,
    "min_run_s": MIN_RUN_S,
    "merge_gap_s": MERGE_GAP_S,
    "speech_percentile": SPEECH_PERCENTILE,
    "cluster_count": N_SPEAKERS,
    "min_cluster_size": MIN_CLUSTER_SIZE,
    "cluster_attempts": CLUSTER_ATTEMPTS,
    "cluster_seed": CLUSTER_SEED,
    "kmeans_iter": KMEANS_ITER,
}

DECODE_CONFIG = {
    "codec": "pcm_f32le",
    "sample_rate": SR,
    "channels": 1,
    "layout": "mono",
}


class DiarizationFailed(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "diarization_failed"


@dataclass(frozen=True)
class DiarizationResult:
    segments: list[DiarizationSegment]
    speech_windows: int
    silence_windows: int
    window_end_offset_us: int


def mel_bank(n_fft: int) -> np.ndarray:
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
        raise DiarizationFailed("audio shorter than one frame")
    count = 1 + (audio.size - FRAME) // HOP
    index = np.arange(FRAME)[None, :] + HOP * np.arange(count)[:, None]
    windowed = audio[index] * np.hanning(FRAME)
    spec = np.abs(np.fft.rfft(windowed, axis=1)).astype(np.float64)
    power = spec * spec
    mel = np.maximum(power @ mel_bank(FRAME).T, 1e-10)
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
    if not rows:
        raise DiarizationFailed("not enough audio frames to diarize")
    return np.vstack(rows), np.array(times), np.array(energy)


def zscore(features: np.ndarray) -> np.ndarray:
    clean = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    mean = clean.mean(axis=0)
    std = clean.std(axis=0)
    std = std.copy()
    std[std < 1e-6] = 1.0
    return (clean - mean) / std


def speech_mask(energy: np.ndarray) -> np.ndarray:
    return energy >= np.percentile(energy, SPEECH_PERCENTILE)


def cluster_speech(features: np.ndarray) -> np.ndarray:
    """Three clusters, seeded from mutually distant windows.

    The seed and the rejection rules are the proven CFS path. Labels are local
    to this matrix. They are not participant ids.
    """
    if features.ndim != 2 or features.shape[0] < N_SPEAKERS * 4:
        raise DiarizationFailed("not enough speech windows to diarize")
    scaled = zscore(features)
    best_labels = None
    best_sep = -1.0
    rng = np.random.default_rng(CLUSTER_SEED)
    n = len(scaled)
    for _ in range(CLUSTER_ATTEMPTS):
        first = int(rng.integers(0, n))
        dist_first = np.sum((scaled - scaled[first]) ** 2, axis=1)
        second = int(np.argmax(dist_first))
        dist_second = np.sum((scaled - scaled[second]) ** 2, axis=1)
        third = int(np.argmax(np.minimum(dist_first, dist_second)))
        init = np.vstack([scaled[first], scaled[second], scaled[third]])
        try:
            centroids, labels = kmeans2(scaled, init, minit="matrix", missing="warn", iter=KMEANS_ITER)
        except Exception:
            continue
        labels = labels.astype(int)
        sizes = [int((labels == k).sum()) for k in range(N_SPEAKERS)]
        if min(sizes) < MIN_CLUSTER_SIZE:
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
        raise DiarizationFailed("speaker clustering failed")
    return best_labels


def smooth_labels(labels: np.ndarray, speech: np.ndarray) -> np.ndarray:
    """Drop sub-second label flickers. A speaker change does not require silence."""
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
                    "cluster_key": f"SPEAKER_{int(labels[start]):02d}",
                })
            start = i
    return _merge_touching(segments)


def _merge_touching(segments: list[dict]) -> list[dict]:
    if not segments:
        return []
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg["cluster_key"] == prev["cluster_key"] and seg["start"] - prev["end"] <= MERGE_GAP_S:
            prev["end"] = seg["end"]
        else:
            merged.append(dict(seg))
    return merged


def cluster_windows(
    features: np.ndarray,
    times: np.ndarray,
    energy: np.ndarray,
    origin: float,
) -> tuple[list[dict], dict]:
    """Cluster a saved window matrix. ``origin`` is seconds on the source timeline.

    This is the post-feature stage used by the proof comparison. Cluster numbers
    are arbitrary across equivalent partitions.
    """
    speech = speech_mask(energy)
    if int(speech.sum()) < N_SPEAKERS * 4:
        raise DiarizationFailed("not enough speech windows to diarize")
    labels = np.full(len(times), -1, dtype=int)
    labels[speech] = cluster_speech(features[speech])
    labels = smooth_labels(labels, speech)
    segments = segments_from_labels(labels, times, origin)
    meta = {
        "speech_windows": int(speech.sum()),
        "silence_windows": int((~speech).sum()),
        "cluster_count": N_SPEAKERS,
        "overlap_supported": False,
    }
    return segments, meta


def diarize_pcm(audio: np.ndarray, origin_us: int) -> DiarizationResult:
    """Diarize decoded PCM. ``origin_us`` is the source container start.

    Relative segment times are rounded on the legacy millisecond grid, then
    the container start is added as an integer. The result is canonical
    microseconds. Clusters stay anonymous.
    """
    if isinstance(origin_us, bool) or not isinstance(origin_us, int) or origin_us < 0:
        raise DiarizationFailed("source origin is not a canonical timestamp")
    cep, centroid, rms = frame_features(audio)
    features, times, energy = window_matrix(cep, centroid, rms)
    relative, meta = cluster_windows(features, times, energy, 0.0)
    segments: list[DiarizationSegment] = []
    for item in relative:
        start_us = legacy_seconds_to_us(item["start"]) + origin_us
        end_us = legacy_seconds_to_us(item["end"]) + origin_us
        if end_us <= start_us:
            continue
        segments.append(DiarizationSegment(start_us, end_us, item["cluster_key"]))
    if not segments:
        raise DiarizationFailed("diarization produced no segments")
    sample_us = int(audio.shape[0]) * 1_000_000 // SR
    return DiarizationResult(
        segments=segments,
        speech_windows=meta["speech_windows"],
        silence_windows=meta["silence_windows"],
        window_end_offset_us=sample_us,
    )
