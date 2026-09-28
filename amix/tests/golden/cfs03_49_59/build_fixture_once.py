"""Build compact golden JSON from legacy artifacts. Not part of the test suite.

Does not read video. Shot expectations come from the legacy automatic planner
with reaction inserts left out.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
LEGACY = REPO / "legacy"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(LEGACY))

PARTICIPANTS = {
    "speaker_a": "cfs03-a",
    "speaker_b": "cfs03-b",
    "speaker_c": "cfs03-c",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _us(seconds: float) -> int:
    # Same one-step rule the engine uses for JSON numbers.
    from amix.amix_engine.time.clock import legacy_seconds_to_us
    return legacy_seconds_to_us(seconds)


def _participant(label: str | None) -> str | None:
    if label is None or label == "unknown":
        return None
    return PARTICIPANTS[label]


def _legacy_planner():
    spec = importlib.util.spec_from_file_location(
        "diarized_plan",
        LEGACY / "data/tmp_cfs03_preview/build_offline_49_59_diarized_turns_v1_plan.py",
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    spec2 = importlib.util.spec_from_file_location(
        "overlap_plan",
        LEGACY / "data/tmp_cfs03_preview/build_offline_49_59_diarized_overlap_v1_plan.py",
    )
    over = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(over)
    return base, over


def main() -> None:
    sys.path.insert(0, str(REPO))
    speakers = LEGACY / "data" / "speakers"
    words_doc = _load(speakers / "CFS03_49-59_words_with_speakers.json")
    raw = _load(speakers / "CFS03_49-59_diarization_raw.json")
    turns_doc = _load(speakers / "CFS03_49-59_turns_v3.json")
    overlaps_doc = _load(speakers / "CFS03_49-59_overlaps_v3.json")

    _write(HERE / "inputs" / "words.json", {
        "role": "INPUT",
        "description": "Whisper words for the window. Speaker labels removed.",
        "source": "legacy/data/transcripts/CFS03.words.json via CFS03_49-59_words_with_speakers.json timestamps_unchanged",
        "not_for": "this file must not be treated as an assignment result",
        "words": [
            {
                "word_id": f"W{index + 1:04d}",
                "text": word["text"],
                "start": word["start"],
                "end": word["end"],
            }
            for index, word in enumerate(words_doc["words"])
        ],
    })
    _write(HERE / "inputs" / "diarization_segments.json", {
        "role": "INPUT",
        "description": "Anonymous diarization segments before word assignment.",
        "source": "legacy/data/speakers/CFS03_49-59_diarization_raw.json segments",
        "segments": [
            {
                "start": segment["start"],
                "end": segment["end"],
                "cluster_id": segment["anonymous_speaker"],
            }
            for segment in raw["segments"]
        ],
    })
    _write(HERE / "inputs" / "cluster_map.json", {
        "role": "INPUT",
        "description": "Pinned cluster-to-participant map for this CFS03 proof. Hand-anchored in legacy. Not discovered by AMIX.",
        "source": "legacy/data/speakers/CFS03_49-59_diarization_raw.json mapping",
        "map": {
            cluster: PARTICIPANTS[row["speaker"]]
            for cluster, row in raw["mapping"].items()
            if row.get("speaker")
        },
    })
    _write(HERE / "inputs" / "layout.json", {
        "role": "INPUT",
        "description": "CFS tile geometry bound to fixture participant ids for the whole window.",
        "source": "legacy/reels_factory/cfs_multicam_16x9.py TILES",
        "bindings": [
            {"participant_id": "cfs03-a", "x": 52, "y": 24, "w": 896, "h": 504},
            {"participant_id": "cfs03-b", "x": 972, "y": 24, "w": 896, "h": 504},
            {"participant_id": "cfs03-c", "x": 512, "y": 552, "w": 896, "h": 504},
        ],
    })
    _write(HERE / "inputs" / "config.json", {
        "role": "INPUT",
        "source_start_seconds": 2960,
        "duration_seconds": 600,
        "source_video": "legacy/data/inbox/03.mp4",
        "source_video_bytes": 8681934519,
        "assign": {"majority_fraction": 0.55, "tie_ratio": 0.75, "min_word_seconds": 0.02},
        "turns": {"same_turn_gap_seconds": 1.5},
        "overlap": {
            "sample_fps": 8,
            "window_s": 1.25,
            "step_s": 0.25,
            "simultaneous_s": 0.75,
            "min_windows": 2,
            "merge_gap_s": 0.75,
            "lip_on": 4.2,
            "weaker_min": 5.5,
            "min_region_s": 2.5,
        },
        "planner": {
            "min_floor_seconds": 2.0,
            "min_floor_words": 4,
            "long_wordless_seconds": 12.0,
            "reactions": "excluded; hand-authored in the legacy plan and not part of the automatic planner",
        },
    })

    _write(HERE / "expected" / "assignments.json", {
        "role": "EXPECTED",
        "description": "Assertion target for assign_words. Not an input.",
        "source": "legacy/data/speakers/CFS03_49-59_words_with_speakers.json",
        "assignments": [
            {"word_id": f"W{index + 1:04d}", "participant_id": _participant(word["speaker"])}
            for index, word in enumerate(words_doc["words"])
        ],
    })
    _write(HERE / "expected" / "turns.json", {
        "role": "EXPECTED",
        "description": "Assertion target for build_turns. Not an input.",
        "source": "legacy/data/speakers/CFS03_49-59_turns_v3.json",
        "turns": [
            {
                "turn_id": turn["turn_id"],
                "participant_id": _participant(turn["speaker"]),
                "start_us": _us(turn["start"]),
                "end_us": _us(turn["end"]),
                "word_count": turn["word_count"],
            }
            for turn in turns_doc["turns"]
        ],
    })
    _write(HERE / "expected" / "overlaps.json", {
        "role": "EXPECTED",
        "description": "Assertion target for overlap_regions. Not an input.",
        "source": "legacy/data/speakers/CFS03_49-59_overlaps_v3.json",
        "regions": [
            {
                "start_us": _us(region["start"]),
                "end_us": _us(region["end"]),
                "participant_ids": [_participant(name) for name in region["speakers_active"]],
                "confidence": region["confidence"],
            }
            for region in overlaps_doc["regions"]
        ],
    })

    base, over = _legacy_planner()
    floors, _stats = base.build_floors(turns_doc["turns"], words_doc["words"])
    shots = base.floors_to_shots(floors)
    prepared = over.prepare_overlaps(overlaps_doc["regions"], words_doc["words"])
    shots = over.overlay(shots, prepared)
    shots = over._merge(shots)
    normalized = []
    for shot in shots:
        if shot["reason"] == "reaction":
            raise SystemExit("automatic plan unexpectedly contains a reaction")
        presentation = "untouched_wide" if shot["shot_type"] == "ORIGINAL_WIDE" else "full"
        participant = None
        if presentation == "full":
            participant = _participant(shot["dominant"])
        normalized.append({
            "start_us": _us(shot["_start"]),
            "end_us": _us(shot["_end"]),
            "presentation": presentation,
            "participant_id": participant,
            "floor_participant_id": _participant(shot.get("active_speaker")),
            "reason": shot["reason"],
        })
    _write(HERE / "expected" / "shots.json", {
        "role": "EXPECTED",
        "description": "Automatic floor/overlap plan. Reaction inserts removed by not running them. Not an input.",
        "source": "legacy build_floors + prepare_overlaps + overlay, without insert_reactions",
        "shots": normalized,
    })
    print("words", len(words_doc["words"]), "segments", len(raw["segments"]))
    print("turns", len(turns_doc["turns"]), "overlaps", len(overlaps_doc["regions"]), "shots", len(normalized))


if __name__ == "__main__":
    main()
