"""Diarize Edited.mp4 from DIRECTABLE_PROGRAM audio only.

Uses the same MFCC windowing, centroid, and 3-means clustering as
cfs_audio_diarize_poc. Cluster-to-person mapping uses mouth votes on
this file's own solo program segments. It does not read the old
CFS03 timelines or their hardcoded solo timestamps.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_audio_diarize_poc import (
    _cluster,
    _majority_speaker,
    _merge_touching,
    _smooth,
    frame_features,
    load_audio,
    segments_from_labels,
    window_matrix,
)
from reels_factory.cfs_offline_verify import measure_mouth_window, open_verifier

SOURCE = ROOT / "data" / "inbox" / "Edited.mp4"
MAP = ROOT / "data" / "director_tests" / "Edited_editability_map.json"
OUT = ROOT / "data" / "speakers" / "Edited.diarization_raw.json"


def map_on_this_timeline(segments: list[dict], source: Path) -> dict:
    by_speaker: dict[str, list[dict]] = {}
    for seg in segments:
        if seg["end"] - seg["start"] < 3.0:
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
                    samples.append({
                        "t": round(t, 3),
                        "mouth": mouth,
                        "speaker": _majority_speaker(mouth),
                    })
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
        for row in mapping.values():
            if row["speaker"] is not None and used.count(row["speaker"]) > 1:
                row["speaker"] = None
                row["rejected"] = "two anonymous clusters mapped to the same participant"
    return mapping


def main() -> None:
    edit = json.loads(MAP.read_text(encoding="utf-8"))
    regions = [(float(r["start"]), float(r["end"])) for r in edit["directable"]]
    if not regions:
        raise RuntimeError("no directable program regions")
    feature_rows = []
    energy_rows = []
    time_rows = []
    for start, end in regions:
        if end - start < 1.0:
            continue
        ceps, centroids, energies = [], [], []
        cursor = start
        while cursor < end - 0.5:
            stop = min(end, cursor + 600.0)
            print(f"features {cursor:.1f}-{stop:.1f}", flush=True)
            audio = load_audio(SOURCE, cursor, stop - cursor)
            cep, centroid, rms = frame_features(audio)
            ceps.append(cep)
            centroids.append(centroid)
            energies.append(rms)
            del audio
            cursor = stop
        features, times, energy = window_matrix(
            np.concatenate(ceps), np.concatenate(centroids), np.concatenate(energies)
        )
        times = times + start
        feature_rows.append(features)
        energy_rows.append(energy)
        time_rows.append(times)
        del ceps, centroids, energies
    features = np.vstack(feature_rows)
    energy = np.concatenate(energy_rows)
    speech_gate = float(np.percentile(energy, 18))
    print("windows", len(energy), "gate", round(speech_gate, 5), flush=True)
    labels_by_row = []
    speech_features = []
    speech_index = []
    cursor = 0
    for features_i, energy_i in zip(feature_rows, energy_rows):
        speech_i = energy_i >= speech_gate
        for local, is_speech in enumerate(speech_i):
            if is_speech:
                speech_features.append(features_i[local])
                speech_index.append(cursor + local)
        cursor += len(energy_i)
    speech_features = np.vstack(speech_features)
    print("cluster", len(speech_features), flush=True)
    clustered = _cluster(speech_features)
    segments = []
    cursor = 0
    speech_cursor = 0
    taken = {i: lab for i, lab in zip(speech_index, clustered)}
    for times, energy_i, features_i in zip(time_rows, energy_rows, feature_rows):
        n = len(times)
        labels = np.full(n, -1, dtype=int)
        speech = np.zeros(n, dtype=bool)
        for local in range(n):
            global_i = cursor + local
            if global_i in taken:
                labels[local] = taken[global_i]
                speech[local] = True
        labels = _smooth(labels, speech)
        part = segments_from_labels(labels, times, 0.0)
        segments.extend(part)
        cursor += n
    segments = _merge_touching(sorted(segments, key=lambda s: s["start"]))
    for seg in segments:
        seg["confidence"] = None
        seg.pop("cluster", None)
    print("segments", len(segments), sorted({s["anonymous_speaker"] for s in segments}), flush=True)
    mapping = map_on_this_timeline(segments, SOURCE)
    for name, row in mapping.items():
        votes = [a["visual_speaker"] for a in row["anchors"]]
        print(name, "->", row["speaker"], votes, flush=True)
    payload = {
        "kind": "cfs_audio_diarization_raw",
        "source_video": "data/inbox/Edited.mp4",
        "timeline": "Edited.mp4",
        "raw_source_timestamps_used": False,
        "method": "local_mfcc_kmeans_diarization",
        "learned_from": "DIRECTABLE_PROGRAM regions only",
        "true_audio_diarization": True,
        "num_speakers": 3,
        "silence_gap_required_for_speaker_change": False,
        "overlap_supported": False,
        "mapping_method": "mouth votes on this file's own long program segments",
        "meta": {
            "window_s": 0.75,
            "hop_s": 0.25,
            "speech_gate": speech_gate,
            "speech_windows": int(len(speech_features)),
        },
        "mapping": mapping,
        "segments": segments,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    mapped = [row["speaker"] for row in mapping.values() if row["speaker"]]
    if len(mapped) != 3 or len(set(mapped)) != 3:
        print("MAPPING_INCOMPLETE", mapped, flush=True)
        raise SystemExit(2)
    print("DIARIZE_DONE", flush=True)


if __name__ == "__main__":
    main()
