# ADR 0009: Word IDs as semantic edit anchors

## Context

LLM stages in legacy sometimes see timestamps. Models are not a clock. Word rows from Whisper are the media measurement. Normalization already keeps raw times and attaches clean tokens only when alignment is exact.

## Decision

Semantic outputs reference `word_id`, `turn_id`, or `conversation_thread_id`. Validators reject unknown ids and ignore model-invented timestamps. Display text changes on a `TextRevision` and does not move `start_us` / `end_us`. Reel and thread ranges are derived from the anchored words.

## Consequences

- A normalization or Reel model cannot silently shift a cut.
- Legacy timestamp-only plans must be snapped once at import.
- Splitting a word is a new id, not an in-place edit of the original row.

## Status

Accepted
