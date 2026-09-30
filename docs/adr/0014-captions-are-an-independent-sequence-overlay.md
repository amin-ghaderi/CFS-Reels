# ADR 0014: Captions are an independent sequence overlay

## Context

AMIX already separates editorial content, picture treatment, and output canvas. A transcript is the timed source text. A caption is how that text is grouped and optionally rewritten for a specific editorial sequence. Burning that text into a picture depends on fonts and a later render decision.

## Decision

Caption content is a fourth axis:

- Content selection remains an `EditorialSequence`.
- Picture direction remains a visual treatment.
- Output canvas remains a `RenderProfile`.
- Caption text is a `CaptionTrack` on one sequence.

A caption track records the sequence revision, transcript run, and effective-text fingerprint it was built from. It does not record an aspect ratio or a visual treatment. The same cues stay valid for landscape and portrait until the sequence or the transcript changes. Manual caption text does not edit the transcript. SRT and WebVTT use sequence time. Editor preview uses the cue's source range because playback is still the source. Burn-in is not part of this axis yet.

## Consequences

- Primary edits and reel drafts use the same caption model.
- Changing 16:9 to 9:16 does not regenerate captions.
- A reel does not receive captions unless someone generates them.
- The sequence renderer does not draw captions.

## Status

Accepted
