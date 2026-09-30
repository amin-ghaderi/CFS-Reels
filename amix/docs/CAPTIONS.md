# Captions

A `CaptionTrack` is editorial state for one `EditorialSequence`. It is not an analysis run, not the transcript, and not a render profile.

## Axes

Content, picture, captions, and canvas stay independent.

- The sequence decides which source ranges are kept.
- The visual treatment decides how the picture is framed.
- The caption track decides the subtitle cues.
- The render profile decides the canvas.

A reel is not a caption. Portrait is not a caption. Generating captions is a separate choice for a primary sequence or a reel draft. Both use this same track.

## Transcript and caption text

Generation reads the active transcript's effective word text, including manual word corrections. Each cue stores that generated text. A manual caption edit stores `manual_text` on the cue and leaves `generated_text` in place. The text a viewer sees is the manual text when it is present, otherwise the generated text.

Use Generated Text clears `manual_text` for that cue. It does not rebuild the track.

A manual caption edit does not change machine word text, does not write a word correction, and does not stale conversation map, reel discovery, turns, overlap, or the shot plan. A word correction does stale the caption track. Whitespace-only manual text is rejected. Stored cue text is one logical line: line breaks are not a canvas wrap.

## Word anchors and time

A word belongs to a kept clip when its integer midpoint is inside that clip's half-open source range. The midpoint is `start_us + (end_us - start_us) // 2`. A midpoint exactly at a clip start is included. A midpoint exactly at a clip end is not. One word therefore belongs to at most one clip. The sequence itself is not snapped to words.

Each cue keeps `first_word_id`, `last_word_id`, `source_start_us`, and `source_end_us`. Those word ids are the identity. The generated sentence is not.

Sequence times come from `source_to_sequence_us`. They are integer microseconds. A cue never crosses a sequence clip, including when two kept clips are adjacent, so a removed gap cannot sit inside one caption.

Profile `amix.caption.segment.v1` groups words inside one clip by source order. It starts a new cue after sentence punctuation (`.`, `!`, `?`, `؟`, `۔`, `…`), when the gap since the previous word is at least 800 ms, when the cue would exceed 6 seconds, or when the cue already has 12 words. Those limits are reading limits. They do not use output width, so 1920×1080 and 1080×1920 get the same cues.

## Staleness

The current track records the sequence revision, the transcript run, and a fingerprint of effective word text. It is stale when any of those change. Splitting a clip changes the sequence revision even when the kept source is the same, so the track becomes stale. Regeneration replaces the current track. The previous track and its manual edits stay in the database and are not copied onto the new cues.

It is not stale when the render profile, aspect, visual treatment, shot plan, or camera override changes.

## Preview and export

Editor playback is still the source. The caption overlay shows the cue whose source range contains the playhead, using `[source_start_us, source_end_us)`. A removed source range shows no sequence caption. The overlay does not skip the player across removed ranges. Clicking a cue seeks to `source_start_us`, not to sequence time.

SRT and WebVTT use sequence time. Serialization rounds microseconds to milliseconds half up, and writes UTF-8. SRT uses `HH:MM:SS,mmm`. WebVTT uses a dot and has no style block. The files are written under `exports/captions/` inside the project and stored as `sidecar` media assets. Provenance on `caption_export` records the source asset, sequence id, purpose, revision, fingerprint, caption track id and revision, transcript run, effective-text fingerprint, profile, and format. It does not record a render profile. An export is refused while the track is stale. Later edits do not delete an existing sidecar.

## Burn-in

This phase does not draw captions into the video. Font packaging, libass availability, safe area, and cross-platform font consistency need their own decision. The sequence renderer is unchanged and adds no caption filter. Styling stays in the editor preview, not in the caption track.
