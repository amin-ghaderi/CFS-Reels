"""Align Edited Whisper words to Edited diarization and build turns.

Does not read CFS03 speaker timelines. Does not move word timestamps.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_audio_diarize_poc import SAME_TURN_GAP_S, assign_word, build_turns
from reels_factory.utils import ts

WORDS = ROOT / "data" / "transcripts" / "Edited.words.json"
DIAR = ROOT / "data" / "speakers" / "Edited.diarization_raw.json"
OUT_WORDS = ROOT / "data" / "speakers" / "Edited.words_with_speakers_v3.json"
OUT_TURNS = ROOT / "data" / "speakers" / "Edited.turns_v3.json"


def main() -> None:
    words_doc = json.loads(WORDS.read_text(encoding="utf-8"))
    diar = json.loads(DIAR.read_text(encoding="utf-8"))
    segments = diar["segments"]
    mapping = diar["mapping"]
    selected = []
    for word in words_doc["words"]:
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
    changes = 0
    close_changes = 0
    for a, b in zip(turns, turns[1:]):
        if a["speaker"] != b["speaker"]:
            changes += 1
            if b["start"] - a["end"] < 0.65:
                close_changes += 1
    named = [t for t in turns if t["speaker"] in {"speaker_a", "speaker_b", "speaker_c"}]
    meaningful = [
        t for t in named
        if t["duration_s"] >= 2.0 and t["word_count"] >= 4
    ]
    OUT_WORDS.write_text(json.dumps({
        "kind": "cfs_words_with_speakers",
        "source_video": "data/inbox/Edited.mp4",
        "source_words": "data/transcripts/Edited.words.json",
        "timestamps_unchanged": True,
        "raw_source_timestamps_used": False,
        "word_count": len(selected),
        "counts": counts,
        "words": selected,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_TURNS.write_text(json.dumps({
        "kind": "cfs_speaking_turns_v3",
        "source_video": "data/inbox/Edited.mp4",
        "built_from": "word-level diarized speakers",
        "speaker_change_splits_without_silence": True,
        "same_turn_gap_s": SAME_TURN_GAP_S,
        "raw_source_timestamps_used": False,
        "turn_count": len(turns),
        "meaningful_turn_count": len(meaningful),
        "median_turn_duration_s": durs[len(durs) // 2] if durs else 0,
        "longest_turn_duration_s": durs[-1] if durs else 0,
        "speaker_changes": changes,
        "speaker_changes_with_gap_under_0_65s": close_changes,
        "range": {"start": "00:00:00.000", "end": ts(float(words_doc.get("duration") or selected[-1]["end"]))},
        "turns": turns,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("words", counts, flush=True)
    print("turns", len(turns), "meaningful", len(meaningful), "changes", changes, flush=True)
    print("ALIGN_DONE", flush=True)


if __name__ == "__main__":
    main()
