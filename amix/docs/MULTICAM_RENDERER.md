# Multicam renderer

Automatic shots and manual camera choices are different layers. A render reads the effective plan and one output canvas. It does not create another shot plan.

## Overrides

An automatic `shot_plan` AnalysisRun stays as it was generated. A manual choice is a `shot_override` row tied to that run, that media, and that shot id. Matching shots by time is not used. `auto` deletes the row. `wide` forces the full program frame. `full` forces one participant.

The override changes the camera for the shot's existing `[start_us, end_us)`. It does not split, move, or trim the cut.

Priority is protected material, then the manual choice, then the automatic decision. A protected shot stays locked. An automatic overlap wide shot may be forced to one participant, and that is an editorial correction. A full override is stored only when that participant's layout covers the whole shot. Adjacent bindings count. A gap or two bindings at the same time is rejected. The renderer does not silently fall back to wide.

A newer automatic plan has new shot ids. Older overrides stay stored and do not apply to it.

`describe_shots` resolves the effective plan in memory. Each shot reports the automatic decision, the override if one is stored, the effective decision, and whether it is locked. That view is not written back over the automatic rows.

## One output canvas

Profile `amix.multicam.render.v1` takes a preset:

| Preset | Pixels | Aspect |
| --- | --- | --- |
| `landscape_1080` | 1920×1080 | 16:9 |
| `landscape_720` | 1280×720 | 16:9 |
| `portrait_1080` | 1080×1920 | 9:16 |
| `portrait_720` | 720×1280 | 9:16 |

Landscape and portrait are sizes of the same renderer. The shot plan does not store 1920×1080 or 1080×1920. Rendering both sizes creates two jobs and two export files.

The output frame rate is the source average frame rate (`fps_num` / `fps_den`) when that rational is valid. Otherwise it is 30/1. Output is constant frame rate. A variable-frame-rate source is converted once onto that grid. There is no frame-rate panel.

## Framing

`center_fill.v1` has two modes.

`FULL` resolves the participant region at that time and takes the largest even rectangle inside it with the output aspect, centered, then scales to the canvas. A 896×504 region in 1920×1080 is scaled only. The same region in 1080×1920 is a centered 9:16 crop inside the region. The picture is not stretched.

`WIDE` and `PROTECTED` fit the whole displayed source into the canvas and pad the rest with black. Protected means the program image is kept, including when the output aspect differs. There is no blurred background, graphic, or second portrait layout.

A full shot that crosses a layout boundary becomes two render segments. Those segments are not new editorial shots.

The render decode leaves FFmpeg autorotate on, so the filter sees the same display pixels the layout was drawn in.

## Frame grid

Every boundary is an output frame index from the render start:

```
round_half_up((time_us - render_start_us) * fps_num / (1_000_000 * fps_den))
```

The arithmetic is integer. Ties round away from zero. A segment's frame count is the next index minus the current index, so the counts add up to the index of the render end. Shot durations are not rounded one by one. A segment that lands on zero frames is omitted. Canonical shot times are not rewritten to make that happen.

## Audio and encode

Program audio is not cut on camera changes. With no editorial sequence, or with one clip that is the whole plan range, audio is one trim of that range. When the sequence keeps several source ranges, audio is one trim per kept clip, concatenated in sequence order, on the same source boundaries as the picture. There is no crossfade. A source with no audio produces a video-only file. Silence is not invented.

The developer encode is MP4, H.264 (`libx264`, `veryfast`, CRF 20), `yuv420p`, `+faststart`, and AAC at 128 kbps / 48 kHz when the source has audio. FFmpeg is an external development tool. This build is not a statement that `libx264` or the installed FFmpeg may be redistributed. That choice belongs to packaging.

Canonical times stay on the source timeline. Only the FFmpeg trim converts them with the media's container start. Proxy playback time is not used.

The filter graph is one constant-frame-rate conversion, then per-segment frame trims. Long graphs go through `-filter_complex_script`. The script is deleted when the job finishes. The frontend cannot pass FFmpeg arguments, a filter, or an output path.

## Job, cancellation, export

The job kind is `render_multicam`. The request is the source media id, the active shot-plan id, and a preset id. If an editorial sequence exists for that source, the render uses its kept clips. Optional `sequence_id` and `sequence_revision` must match that sequence or the job fails `sequence_changed`. Encoding starts only when the source is present, probed, and the plan belongs to it and is not stale. FFmpeg must be available.

Progress is FFmpeg `-progress` mapped to 0..10000 of the render range. It stays under 10000 until the file has been checked with ffprobe, moved into place, and stored as an export asset. 10000 means that export exists.

The file is written under `exports/.tmp/` and moved to `exports/<job id>.mp4` only after that check. The project folder is the only destination. Cancel stops the FFmpeg process tree, deletes the temp file, and does not add an export. The shot plan and the overrides stay. Shutdown cancels the same way before the project lock is released. A crash leaves the job `INTERRUPTED` on the next writable open. There is no resume. A retry is a new job.

The job result records the source, the shot-plan run, the override fingerprint, the effective-plan fingerprint, the editorial sequence id, revision, and fingerprint when a sequence exists, the profile and preset, the canvas, the frame-rate rational, the framing policy, the FFmpeg version, a lightweight source identity, and the export media id. The export asset stores the probed file, not the requested numbers alone. A later sequence edit does not delete an older export.

Completed exports are listed on the Multicam workspace. Playback of those files is not part of this phase. The proxy player is unchanged.

Switching 16:9 and 9:16 does not rebuild turns, overlap, the shot plan, or the editorial sequence.

## Sequence cuts

When a sequence is present, the compiler intersects each kept source clip with the effective shots and with layout boundaries. Removed source time produces no segment. Stored shots are not split or rewritten. A shot that crosses a cut is drawn only where it overlaps a kept clip.

One full-range clip uses the same continuous filter and frame count as a render with no sequence. Several clips use a different graph: each visual fragment is trimmed from source time, concatenated, then converted with one `fps` filter. Frame indexes are still computed in sequence time before FFmpeg runs. Sequence time is the cumulative duration of kept clips, starting at 0. Every boundary uses `frame_index(sequence_time_us, 0)`. The output frame count is `frame_index(kept_duration_us, 0)`. Clip durations and shot durations are not rounded separately and then added.

Camera changes still do not cut audio. Editorial clip boundaries do.

## Not in this phase

Reels, a stacked portrait layout, reaction inserts, crossfades, clip reordering, multiple sources, face-tracked framing, and publication are not implemented. A later framing policy can replace center-fill. This renderer does not have to change its job shape for a different canvas size.
