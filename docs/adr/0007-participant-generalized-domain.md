# ADR 0007: Participant-generalized domain

## Context

Legacy framing, diarization maps, and 16:9 shots are built around `speaker_a`, `speaker_b`, `speaker_c` and `FULL_A`, `FULL_B`, `FULL_C`. Real programs vary: two people, three people, graphics, and layout changes. The successful director only needs “this participant full frame” or “the original frame”.

## Decision

The domain uses `ParticipantId`. A full shot is presentation `full` plus `participant_id`, and only when that participant has a layout-region binding on the span being planned. If there is no usable binding, the planner emits the untouched program frame. It does not stretch another rectangle, reuse a stale binding, or fail the plan. Protected master spans still override every other presentation.

A layout region is source geometry. It is not permission to stretch that rectangle to the output aspect. A full shot must preserve the subject’s aspect ratio. CFS tiles that are already 16:9 may be scaled directly. Other layouts need an explicit framing policy later; this decision does not define that policy.

Program-wide and protected-master shots have no participant crop. Layout regions stay separate from identity and may change over time. Three named tiles are not a schema limit. Legacy A/B/C labels are import mappings.

## Consequences

- N participants do not require new shot enums.
- Importers must carry a per-asset map from old names to participants.
- Designed split-screen composites stay out of V1, matching the offline renderer’s rejection of those compositions.
- The first non-CFS layout cannot be rendered by blindly scaling whatever rectangle was stored.

## Status

Accepted
