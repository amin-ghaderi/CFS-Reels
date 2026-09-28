# Editorial timeline

An editorial sequence is manual state. It is not an analysis run. Creating, splitting, removing, or resetting clips does not change the source media, the transcript, words, turns, overlap, the automatic shot plan, or stored shot overrides.

The sequence answers one question: which source ranges are present in the output, in source order.

## V1 limit

One sequence belongs to one source media asset. Clips stay in source order. They may leave gaps out of the output. They may not reorder source time, overlap, or repeat a source span. A later version can add reordering, more than one source, or B-roll without changing the meaning of canonical source time.

There is no persistent undo. Session undo was not added.

## Sequence and clips

`editorial_sequence` stores the id, the source media, a display name, the source range, and a revision. `sequence_clip` stores each kept range as its own row: order, `source_start_us`, and `source_end_us`. Clip times are not moved to zero.

The id stays the same across edits. The revision increments when the kept clips change. That revision is for staleness and render provenance. It is not a schema version.

Ranges are half-open: `[start_us, end_us)`. A clip requires `start < end`, must sit inside the sequence source range, and must follow the previous clip without overlap. The source range for a multicam edit is the shot plan span at the moment the sequence is created. A later plan with a different span does not silently move the clips. The render fails `sequence_changed` instead.

Create Edit requires a current shot plan. The first sequence is one clip, `[plan_start_us, plan_end_us)`. Rendering that sequence matches a render of the whole plan.

`split_clip` at time T, with `start < T < end`, replaces one clip with `[start, T)` and `[T, end)`. `remove_clip` drops that source range from the output only. `reset_sequence` restores one clip over the original source range and keeps the sequence id. The timeline asks for confirmation before reset.

Removing every clip is allowed. A render of an empty sequence fails because it has no frames.

## Protected regions

A protected region means multicam must not reframe that source range. It is a camera and render lock. It is not a lock on whether the range may be cut from the sequence. A clip that contains protected material can be removed. Any protected portion that remains is still rendered as the full program frame, with no crop and no manual camera override.

## Source time and sequence time

Analyses stay on source time. Sequence time is derived:

- the first kept clip starts at sequence time 0
- each later clip starts at the sum of the durations of the clips before it

`source_to_sequence_us` returns nothing for a source instant that is not inside a kept clip, including the exact end of a clip when the next kept clip starts later. `sequence_to_source_us` returns nothing before 0 and at or past the sequence duration. Adjacent clips `[0, 10)` and `[10, 20)` put source time 10 in the second clip. The sequence duration is the integer sum of `end - start` for every kept clip.

## Timeline

The Multicam workspace draws the timeline on one Canvas 2D surface: ruler, kept clips, removed gaps, camera fragments, a protected bar, the playhead, and the selection. React owns the buttons and the selected-clip text. The canvas is `aria-hidden`. Split, remove, and reset are buttons, and S / Delete / Backspace repeat split and remove when focus is not in a field and no dialog is open.

The horizontal axis is source time. A removed gap occupies source time on the ruler and is drawn as a gap. It does not have output duration. Camera fragments are the effective plan (automatic shots plus shot overrides) clipped to kept clips. The stored shots are not split. The selected shot list and its override control stay the camera authority. The timeline does not create camera cuts.

Zoom in, zoom out, and fit source change a pure viewport: origin, span, and width. Clicking the canvas seeks the existing preview to that source time, including a click in a removed gap. The playhead is the preview's canonical source time. The engine is not called on each tick.

Playback does not skip removed spans. Phase 13 does not build an edited proxy and does not pretend the preview is the cut sequence. The timeline shows what the export will keep. The player is still the source proxy.

## Render

The same multicam renderer compiles the sequence. Each kept clip is intersected with effective shots, layout boundaries, and protected boundaries. Removed source ranges produce no render segments. Output frames belong to one sequence-time grid: cumulative kept microseconds, then the same integer frame index used for an uncut render, with origin 0. Clips and shots are not rounded independently and summed.

Audio is one trim per kept clip, then concatenated. Camera changes do not cut audio. Editorial cuts do. There is no crossfade, transition, or handle.

A render records the sequence id, revision, and fingerprint beside the existing shot-plan provenance. The preset, aspect, and resolution stay on the render profile. Changing 16:9 and 9:16 does not change the sequence, the clips, the shot plan, the overrides, turns, or overlap. An older export remains after a later edit. A new render is a new job and a new export asset.

If an overridden shot is entirely outside the kept clips, the override row stays stored and has no effect on that render.
