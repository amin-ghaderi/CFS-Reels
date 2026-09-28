"""Speaking turns from assigned words.

Behavior migrated from:
legacy/reels_factory/cfs_audio_diarize_poc.py::build_turns

A speaker change splits the turn. The same participant continues across a gap
no longer than 1.50 s. Unknown stays unknown. Overlap is not an input.
"""
from __future__ import annotations

from amix.amix_engine.domain.types import SpeakerAssignment, Turn, Word

SAME_TURN_GAP_US = 1_500_000


def build_turns(
    words: list[Word],
    assignments: list[SpeakerAssignment],
    *,
    same_turn_gap_us: int = SAME_TURN_GAP_US,
) -> list[Turn]:
    if len(words) != len(assignments):
        raise ValueError("words and assignments differ in length")
    by_id = {row.word_id: row.participant_id for row in assignments}
    turns: list[Turn] = []
    who = None
    start = 0
    end = 0
    word_ids: list[str] = []
    open_turn = False

    def close() -> None:
        nonlocal open_turn
        if not open_turn:
            return
        turns.append(Turn(
            turn_id=f"T{len(turns) + 1:04d}",
            participant_id=who,
            start_us=start,
            end_us=end,
            word_ids=tuple(word_ids),
        ))
        open_turn = False

    for word in words:
        if word.word_id not in by_id:
            raise ValueError(f"no assignment for {word.word_id}")
        speaker = by_id[word.word_id]
        gap = None if not open_turn else word.start_us - end
        same = (
            open_turn
            and speaker == who
            and gap is not None
            and gap <= same_turn_gap_us
        )
        if same:
            end = word.end_us
            word_ids.append(word.word_id)
            continue
        close()
        who = speaker
        start = word.start_us
        end = word.end_us
        word_ids = [word.word_id]
        open_turn = True
    close()
    return turns
