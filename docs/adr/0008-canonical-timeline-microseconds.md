# ADR 0008: Canonical timeline in microseconds

## Context

Legacy times are float seconds rounded to milliseconds. Those floats are re-rounded through plans and FFmpeg. Frame time at 30 fps is not an integer millisecond. Word times do not need sample-accurate audio, but the stored clock should not drift.

## Decision

Store all media times as int64 microseconds. Ranges are half-open. Whisper and legacy JSON convert at the boundary with a fixed rounding rule. FFmpeg arguments are formatted from integers. The UI converts to seconds only for playback. Render may snap a copy of a boundary to a rational frame rate without overwriting the editorial time.

## Consequences

- One clock for words, turns, overlaps, shots, reels, and protected regions.
- Importers must not keep a second float column as authority.
- 1/30 second is still not an integer microsecond; frame snap is explicit.

## Status

Accepted
