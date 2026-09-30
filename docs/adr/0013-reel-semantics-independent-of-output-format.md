# ADR 0013: Reel semantics are independent from output format

## Context

Earlier notes described a reel as a vertical excerpt and a 9:16 edit plan. The legacy pipeline did render 9:16 that way. AMIX now keeps content, picture direction, and output canvas as separate choices. A reel is a short editorial selection from source time. It can be exported at 16:9 or 9:16, as the source program or as multicam, without becoming a different sequence.

## Decision

Three axes stay independent:

- Content selection is an `EditorialSequence`: which source ranges are kept.
- Camera and directing policy is a render-time visual treatment: source/program, or multicam using the source shot plan.
- Output canvas is a `RenderProfile`: size, aspect, and frame-rate policy.

A reel candidate does not store a score, an aspect, or a canvas. A reel draft does not store a visual treatment or a render preset. Changing one axis does not rewrite the other two.

## Consequences

- One sequence compiler serves the primary edit and every reel draft.
- Landscape and portrait presets are output choices, not reel modes.
- Multicam remains optional. A reel can render the whole source picture with no shot plan.
- Legacy 9:16 composition, stack order, and burned subtitles stay historical. They are not a second AMIX renderer.
- Caption text is a separate sequence overlay. See ADR 0014.

## Status

Accepted
