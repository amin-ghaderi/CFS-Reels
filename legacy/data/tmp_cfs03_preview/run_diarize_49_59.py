"""Build the 00:49:20-00:59:20 diarized speaker proof. Does not render."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_audio_diarize_poc import (
    HELDOUT,
    SAME_TURN_GAP_S,
    assign_word,
    build_turns,
    diarize,
    load_audio,
    map_clusters,
)

ORIGIN = 2960.0
DURATION = 600.0
END = ORIGIN + DURATION
SOURCE = ROOT / "data/inbox/03.mp4"


def main() -> None:
    print("extract", flush=True)
    audio = load_audio(SOURCE, ORIGIN, DURATION)
    print("diarize", audio.size, flush=True)
    segments, meta = diarize(audio, ORIGIN)
    print("segments", len(segments), "clusters", sorted({s["anonymous_speaker"] for s in segments}), flush=True)
    print("map", flush=True)
    mapping = map_clusters(segments, SOURCE)
    for name, row in mapping.items():
        votes = [a["visual_speaker"] for a in row["anchors"]]
        print(name, "->", row["speaker"], votes, flush=True)

    words_doc = json.loads((ROOT / "data/transcripts/CFS03.words.json").read_text(encoding="utf-8"))
    selected = []
    for word in words_doc["words"]:
        if float(word["end"]) <= ORIGIN or float(word["start"]) >= END:
            continue
        selected.append({
            "text": word["text"],
            "start": word["start"],
            "end": word["end"],
            "probability": word["probability"],
            "segment_id": word["segment_id"],
            "speaker": assign_word(word, segments, mapping),
        })
    turns = build_turns(selected)
    counts = {}
    for word in selected:
        counts[word["speaker"]] = counts.get(word["speaker"], 0) + 1
    durs = sorted(t["duration_s"] for t in turns)
    median = durs[len(durs) // 2] if durs else 0
    changes = 0
    close_changes = 0
    for a, b in zip(turns, turns[1:]):
        if a["speaker"] != b["speaker"]:
            changes += 1
            if b["start"] - a["end"] < 0.65:
                close_changes += 1

    raw = {
        "kind": "cfs_audio_diarization_raw",
        "source_video": "data/inbox/03.mp4",
        "range": {"start": "00:49:20.000", "end": "00:59:20.000", "start_s": ORIGIN, "end_s": END},
        "method": "local_mfcc_kmeans_diarization",
        "true_audio_diarization": True,
        "num_speakers": 3,
        "silence_gap_required_for_speaker_change": False,
        "overlap_supported": False,
        "overlap_note": "Each time window receives one cluster. Simultaneous speech is not split into two speakers.",
        "held_out_from_mapping_s": list(HELDOUT),
        "same_turn_gap_s": SAME_TURN_GAP_S,
        "meta": meta,
        "mapping": mapping,
        "segments": segments,
    }
    words_out = {
        "kind": "cfs_words_with_speakers",
        "source_words": "data/transcripts/CFS03.words.json",
        "timestamps_unchanged": True,
        "range": raw["range"],
        "word_count": len(selected),
        "counts": counts,
        "words": selected,
    }
    turns_out = {
        "kind": "cfs_speaking_turns_v3",
        "range": raw["range"],
        "built_from": "word-level diarized speakers",
        "speaker_change_splits_without_silence": True,
        "turn_count": len(turns),
        "median_turn_duration_s": median,
        "longest_turn_duration_s": durs[-1] if durs else 0,
        "speaker_changes": changes,
        "speaker_changes_with_gap_under_0_65s": close_changes,
        "turns": turns,
    }
    speakers = ROOT / "data/speakers"
    (speakers / "CFS03_49-59_diarization_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (speakers / "CFS03_49-59_words_with_speakers.json").write_text(
        json.dumps(words_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (speakers / "CFS03_49-59_turns_v3.json").write_text(
        json.dumps(turns_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("counts", counts, flush=True)
    print("turns", len(turns), "median", median, "longest", durs[-1] if durs else None, flush=True)
    print("changes", changes, "under_0.65", close_changes, flush=True)
    print("--- 00:51:00 to 00:51:55 ---", flush=True)
    for turn in turns:
        if turn["end"] <= 3060 or turn["start"] >= 3115:
            continue
        text = turn["text"]
        if len(text) > 140:
            text = text[:140] + "..."
        print(f"{turn['start']:.3f} -> {turn['end']:.3f} {turn['speaker']} {text}", flush=True)
    print("--- overlap old B0186 2986.07-3106.8 ---", flush=True)
    for turn in turns:
        if turn["end"] <= 2986.07 or turn["start"] >= 3106.8:
            continue
        print(f"{turn['start']:.3f} -> {turn['end']:.3f} {turn['speaker']} words={turn['word_count']} dur={turn['duration_s']}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
