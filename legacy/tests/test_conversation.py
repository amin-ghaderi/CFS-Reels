from reels_factory.conversation_reels import (
    ALLOWED_ROLES,
    CEILING,
    evaluate_conversation_integrity,
    thread_opportunity_score,
)
from reels_factory.speakers import UNKNOWN, group_speech_blocks
from reels_factory.transcribe import flatten_words
from reels_factory.word_align import align_raw_words_to_clean, snap_range_to_words


def test_flatten_words_keeps_segment_id_and_probability():
    transcript = {
        "segments": [
            {
                "id": 7,
                "start": 1.0,
                "end": 2.0,
                "text": "hello there",
                "words": [
                    {"start": 1.0, "end": 1.4, "word": "hello", "probability": 0.91},
                    {"start": 1.4, "end": 2.0, "word": "there", "probability": 0.8},
                ],
            }
        ]
    }
    words = flatten_words(transcript)
    assert words[0] == {
        "text": "hello",
        "start": 1.0,
        "end": 1.4,
        "probability": 0.91,
        "segment_id": 7,
    }
    assert words[1]["segment_id"] == 7


def test_align_preserves_raw_timing_when_normalized_differs():
    raw = [
        {"text": "حضینه", "start": 1.0, "end": 1.4, "probability": 0.5, "segment_id": 1},
        {"text": "موندن", "start": 1.4, "end": 2.0, "probability": 0.6, "segment_id": 1},
    ]
    linked = align_raw_words_to_clean(raw, "هزینه ماندن")
    assert linked[0]["start"] == 1.0
    assert linked[0]["end"] == 1.4
    assert linked[0]["text"] == "حضینه"
    assert {row["normalized_text"] for row in linked} <= {"هزینه", "ماندن", None}


def test_snap_range_does_not_cut_mid_word():
    words = [
        {"text": "a", "start": 10.0, "end": 10.3},
        {"text": "b", "start": 10.3, "end": 10.8},
        {"text": "c", "start": 10.8, "end": 11.2},
    ]
    start, end = snap_range_to_words(10.15, 10.95, words)
    assert start == 10.0
    assert end == 11.2


def test_uncertain_speech_stays_unknown():
    words = [
        {"text": "x", "start": 0.0, "end": 0.4, "probability": 0.9, "segment_id": 0},
        {"text": "y", "start": 0.5, "end": 0.9, "probability": 0.9, "segment_id": 0},
        {"text": "z", "start": 3.0, "end": 3.5, "probability": 0.9, "segment_id": 1},
    ]
    blocks = group_speech_blocks(words)
    assert len(blocks) == 2
    assert all(b["speaker"] == UNKNOWN for b in blocks)


def test_conversation_integrity_rejects_qa_roles_and_overlong():
    plan = {
        "segments": [
            {"start": "00:00:00.000", "end": "00:02:00.000", "role": "question_core"},
            {"start": "00:02:00.000", "end": "00:04:00.000", "role": "answer_core"},
        ],
        "playback_check": {},
    }
    gate = evaluate_conversation_integrity(plan)
    assert gate["integrity_status"] == "FAIL"
    assert gate["no_qa_roles"] is False
    assert gate["duration_le_150"] is False
    assert CEILING == 150.0
    assert "hook" in ALLOWED_ROLES
    assert "question_core" not in ALLOWED_ROLES


def test_thread_score_prefers_disagreement_and_hooks():
    weak = {"reel_signals": ["relatable_situation"], "hook_candidates": []}
    strong = {
        "reel_signals": ["disagreement", "strong_hook", "memorable_punchline"],
        "hook_candidates": [{"text": "x"}],
        "disagreement_or_tension": "they clash",
        "start": "00:01:00.000",
        "end": "00:03:00.000",
    }
    assert thread_opportunity_score(strong) > thread_opportunity_score(weak)
