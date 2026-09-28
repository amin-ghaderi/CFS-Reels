# Timeline model

## Decision

AMIX stores every media time as an **int64 count of microseconds** from the start of the referenced media asset.

Ranges are **half-open**: `[start_us, end_us)`.

A point belongs to a range when `start_us <= t < end_us`. Adjacent shots meet when the next `start_us` equals the previous `end_us`. Nothing is stored as a binary float.

ADR: [0008-canonical-timeline-microseconds.md](../adr/0008-canonical-timeline-microseconds.md).

## Why microseconds

Legacy code already treats time as decimal seconds rounded to three places (`round(t, 3)` in transcription and turns). That is millisecond precision, but the values live in IEEE floats and are re-rounded at each stage. A long master (the Edited program is about 2.5 hours) accumulates conversion noise when those floats are added, compared, and passed back through FFmpeg.

| Representation | Fit |
|---|---|
| Float seconds | Matches legacy files. Drifts. Rejected as canonical storage. |
| Integer milliseconds | Matches Whisper’s stored precision. A 30 fps frame is `33.333…` ms, so every frame snap quantizes by up to 1 ms. Acceptable for words, weak as the only render clock. |
| Integer microseconds | Exact integer. Millisecond ASR values land on `…000` microsecond boundaries. Frame snap can use a rational frame duration without a schema change. One 48 kHz sample is about 20.83 µs, so audio-sample alignment can be added later without a new unit. |
| MPEG 90 kHz ticks | Exact for many broadcast timebases. Opaque in a desktop app and awkward next to Whisper’s millisecond grid. |

Microseconds are the canonical unit. Milliseconds remain a display and legacy-import convenience, not a second stored clock.

30 fps is still not a binary-even microsecond (`1/30 s = 33333.333… µs`). Render snaps cuts with an explicit rational; it does not pretend `1/30` is an integer.

## Frame snap

Project media records a rational frame rate when probe provides one (`fps_num`, `fps_den`), for example `30/1` or `30000/1001`.

Render boundaries that must fall on frames convert with integer arithmetic:

```
frame = round_half_away_from_zero(us * fps_num / (fps_den * 1_000_000))
snapped_us = frame * fps_den * 1_000_000 / fps_num
```

Division is integer division after the multiply, with the rounding rule fixed in tests. Shot plans store the editorial boundary in microseconds. The render stage may store the snapped boundary beside it. The editorial value is not overwritten, so a later fps correction can resnap.

Audio duration and video duration may differ by a few milliseconds, as they did on the Edited multicam render. The asset stores both probed durations. Render holds the last video frame or ends at the shorter stream according to an explicit job setting. It does not “fix” the difference inside word times.

## Conversion boundaries

| Boundary | Rule |
|---|---|
| faster-whisper | `us = round_half_away_from_zero(seconds * 1_000_000)`. Legacy files that already used `round(seconds, 3)` import as `us = round(seconds, 3) * 1000`. |
| FFmpeg / ffprobe | Format with six digits: `f"{us / 1_000_000:.6f}"`. Never pass a binary float that has been arithmetically combined in Python. |
| Frontend playback | Media elements need seconds. The UI converts for the player (`us / 1e6`) and writes edits back as integer microseconds. The player’s float is not written into the project as authority. |
| SRT and human timestamps | Derived. Not stored as the source of truth. |
| Legacy JSON | Import once. Keep the original file hash on the analysis run. Do not keep a parallel float field after import. |

## What uses the clock

All of these are `[start_us, end_us)` on a declared `media_asset_id` (or on a render output’s own timeline when the field is an output range):

- words
- speaker-assignment spans (usually the word’s own range)
- turns
- overlap regions
- layout spans
- protected regions
- shots
- Reel source ranges and rendered output ranges

A Reel plan stores **source** ranges on the master asset and, after render, **output** ranges on the export asset. Those are different timelines. They are never added together.

## Identity before time

Semantic stages should point at stable ids:

- `word_id`
- `turn_id`
- `conversation_thread_id`
- `overlap_region_id`

A model that returns a float timestamp is rejected by validation unless the task contract explicitly allows a hint that is then snapped to those ids (see Reel boundary repair). The snap reads word times. It does not trust the model’s clock.

ADR: [0009-word-ids-as-edit-anchors.md](../adr/0009-word-ids-as-edit-anchors.md).

## Transcript text versus time

Word timing is media data.

- `Word.raw_text`, `start_us`, and `end_us` are immutable after the transcription run that created them.
- A text revision may attach `normalized_text` when alignment is unambiguous (legacy `align_raw_words_to_clean` only copies tokens on `equal` opcodes).
- Unaligned tokens keep `normalized_text = null` and still display `raw_text`.
- A human correction creates a new text revision. It may replace display text for a word id. It must not move `start_us` / `end_us`.
- Splitting or merging words is a new transcription or a new word row with a new id and an explicit `derived_from` link. The original row stays.

Segment-level `clean_text` (legacy normalizer) is a revision of segment text. Timestamps on that revision are copies of the source segment, not model output.

## Ordering and gaps

- Turns may contain short gaps up to the turn-builder’s configured same-speaker gap (legacy: 1.50 s). That gap is configuration on the analysis run, not a hidden constant in the UI.
- Overlap regions sit on top of turns. They do not split or relabel the floor turn. The proven 16:9 behavior shows wide during overlap and remembers who held the floor.
- Protected regions override shot choice for their span. They are timeline annotations, not a second video.
- Unknown or wordless spans can be an explicit shot (legacy: original wide after a long wordless gap). They are still timed ranges, not missing data.

## Provenance

Every timed artifact row includes `analysis_run_id` or `revision_id`. Comparing two runs is a query, not a filename convention.
