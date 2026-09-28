# ADR 0008: Canonical timeline in microseconds

## Context

Legacy times are float seconds rounded to milliseconds. Those floats are re-rounded through plans and FFmpeg. Frame time at 30 fps is not an integer millisecond. Word times do not need sample-accurate audio, but the stored clock should not drift.

## Decision

Store all media times as int64 microseconds on the asset’s FFmpeg container presentation timeline. Time 0 is container presentation time 0. Ingest does not rebase, including when a stream `start_time` is non-zero; that offset is recorded and every stage keeps the same origin. Ranges are half-open.

Legacy files are millisecond timestamps. Import them once to a whole millisecond, then `us = ms * 1000` in integer arithmetic. Do not use `round(seconds, 3) * 1000`. Do not invent sub-millisecond precision those files did not have.

FFmpeg arguments are formatted from the integers. The UI converts to seconds only for playback. Render may snap a copy of a boundary to a rational frame rate without overwriting the editorial time.

## Consequences

- One clock for words, turns, overlaps, shots, reels, and protected regions. Source-relative windows stay on that clock.
- Importers must not keep a second float column as authority.
- 1/30 second is still not an integer microsecond; frame snap is explicit.

## Status

Accepted
