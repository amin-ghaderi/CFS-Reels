# Overlap runtime

Overlap is its own analysis. It reads the original source media, the active layout, and local visual and audio evidence. It does not read turns, participant assignments, or speaker identity. Changing a speaker or a turn does not make an overlap run stale and does not start this job again.

## Model policy

The development resolver is `VisionModelResolver` in `amix_engine/adapters/vision/resolver.py`. It reads `AMIX_YUNET_MODEL_PATH`. Optional `AMIX_YUNET_MODEL_ID` and `AMIX_YUNET_MODEL_VERSION` are labels only.

- The file must already exist.
- An explicit path that is missing or too small fails as `invalid_vision_model`.
- An unset path fails as `vision_model_missing`.
- There is no GitHub download, no network fallback, and no legacy cache fallback.
- The desktop status does not include the filesystem path.
- The overlap job stores the descriptor identity. It does not read the environment variable itself. A later Model Manager can replace the resolver.

OpenCV is the runtime (`opencv-python-headless`). YuNet is `cv2.FaceDetectorYN` inside the worker. FastAPI does not run YuNet.

## Profile

`amix.overlap.lip_audio.v1` keeps the CFS overlap proof:

- 8 samples per second
- 1.25 s windows, 0.25 s step
- two articulating participants for 0.75 s
- lip-on 4.2, weaker mouth 5.5
- merge gap 0.75 s
- minimum region 2.5 s
- audio gate at the 25th percentile of positive RMS in the analyzed span

Those numbers are not retuned. The proof was measured on a three-person frame. The activity columns are participant ids, and a region still requires two articulating participants. The profile does not name tiles and does not fix the count at three.

Each layout crop is resampled to 448×252 before YuNet and the mouth bands. That tile is the measurement scale the thresholds were measured on. It is not a source-frame size.

## Geometry

Bindings use display pixels, the same space as probed width and height. At each sample the binding that contains that canonical time is the crop. Two bindings for one participant at the same time are ambiguous: that participant has no region for the sample. A participant with no binding, or a crop that does not meet the minimum patch, scores as no measurable mouth and the previous mouth state is cleared. That is the proof's behavior when landmarks are missing. It is not a stored zero that claims the mouth was still.

A binding change also clears mouth state, so motion is not compared across two different rectangles.

Decoded frames are rotated to the display size before the crop. The worker passes `-noautorotate` and then `fps=8` plus `transpose` or `hflip,vflip` for 90, 270, and 180 degrees. If the frame size is not the probed display size, the sample is rejected. Encoded size and display size are not mixed.

## Analysis window

The percentile gate belongs to the span that was measured. A 2960–3560 s window is not the same analysis as the whole episode. The window is stored on the AnalysisRun and included in the fingerprint.

The desktop asks for the full source, from the container start through the probed duration. The end is snapped down to the 125 ms sample grid and that snapped span is the recorded window. Tests and later workflows may pass an explicit `start_us` and `end_us`. The desktop does not send thresholds, model paths, or commands.

## Activity

The worker writes neutral samples: time, participant id to lip score, and audio RMS. The parent calls the existing `overlap_regions` builder. OpenCV does not write overlap regions.

The activity matrix stays in the job's temporary directory and is deleted with that directory. It is not stored in SQLite and it is not an authority. The AnalysisRun and its overlap regions are the authority. Keeping a multi-hour matrix in the project database is not useful for review, and a second artifact would invite treating it as a source of truth.

Audio RMS uses the original source, 16 kHz mono float, through FFmpeg. Proxy audio is not used. Sample `i` is the RMS of the audio that belongs to that same 125 ms step on the source timeline.

## Worker

`python -m amix.amix_engine.workers.overlap` is a child of the job. FFmpeg is a child of that process. Cancel kills the process tree, deletes the temporary output, and does not publish regions. The previous active overlap stays active.

A crash leaves the job `INTERRUPTED` on the next writable open. It does not resume. Retry creates a new job. Partial activity is not authoritative.

Progress is basis points, monotonic, and stays below 10000 until the run is committed.

## Provenance and staleness

A successful job writes one immutable overlap AnalysisRun and then points the active overlap at it. Failed, cancelled, and interrupted jobs leave the previous pointer alone. Older runs stay stored.

The run records the source asset, profile, snapped window, source size and mtime, layout fingerprint, YuNet identity, OpenCV version, FFmpeg version, sample rate, and the threshold config. It does not depend on a turn run.

The layout fingerprint is the exact binding list in display pixels. A later layout edit makes the overlap stale. The run is kept. It is not recomputed until someone starts overlap analysis again.

## Limits

Overlap analysis does not identify speakers from faces and does not download a model. The detector still needs a usable layout before it starts. Fewer than two participants with a region in the window fails as `insufficient_layout`.

Rendering a multicam program is separate. See [MULTICAM_RENDERER.md](MULTICAM_RENDERER.md).

The production overlap extractor has not been compared with the six known CFS03 regions, because `AMIX_YUNET_MODEL_PATH` was not set. The overlap thresholds were not changed for that reason.
