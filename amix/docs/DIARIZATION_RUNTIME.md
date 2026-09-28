# Diarization runtime

Phase 10 adds participants, manual layout bindings, and one local diarization profile. The profile is the migrated CFS proof. It is not automatic participant identification, and it is not a generic N-speaker diarizer.

## Proven algorithm

The constants and rules come from `legacy/reels_factory/cfs_audio_diarize_poc.py` (`diarize` and the feature, cluster, smooth, and segment helpers). The visual mapping in that file is not production behavior. YuNet, mouth-motion verification, hardcoded CFS03 solo timestamps, automatic cluster anchors, and `cfs_offline_verify` are historical references only.

Profile id: `amix.diarize.mfcc_kmeans.v1`.

The port keeps:

- 16 kHz mono float32 audio
- 25 ms frames, 10 ms hop
- 40 mel bands, MFCC coefficients 1–12, spectral centroid
- 0.75 s feature windows, 0.25 s hop
- speech RMS gating at the 18th percentile
- feature z-scoring
- SciPy `kmeans2`, seed 1, eight farthest-point attempts
- sub-second flicker removal
- speaker changes that do not require silence
- touching segments of the same cluster merged within 0.35 s

Thresholds are not retuned in this phase. There is no confidence score. The algorithm sets none, and the product does not invent one.

## Three clusters, any number of participants

This profile always asks for three clusters. The desktop states that limit. A two-person recording is not a supported input for this profile. The domain still allows any number of participants. A later profile can use a different cluster count without changing `ParticipantId`, assignments, or turns.

Cluster keys such as `SPEAKER_00` are analysis-local labels. They are not participant ids. Cluster 0 is not a person. The same number can mean a different voice in another run. More than one cluster may be mapped to the same participant. A cluster may be mapped to Unknown.

## Audio and clock

Diarization reads the original master `MediaAsset`. It does not read the preview proxy. If the master file is missing, a new run cannot start. Previously stored diarization, assignments, and turns stay readable.

FFmpeg, through the existing media-tool boundary, decodes to a temporary mono 16 kHz float32 PCM file. The command is an argument list. There is no shell. The heavy work runs in `python -m amix.amix_engine.workers.diarize`, not inside FastAPI. Cancelling the job kills that process tree, including FFmpeg.

Sample time zero is the start of that decoded master audio. Segment times are rounded on the legacy millisecond grid, then the source container start is added as an integer. Stored times are canonical microseconds. The playback clock (`canonical_origin_us`, proxy container start, HTML `currentTime`) is not the diarization clock.

The product job covers the full source. The CFS proof window (2960 s for 600 s) is a regression fixture, not a product mode.

## Persistence

Migration `0004_diarization` adds `diarization_segment` (`analysis_run_id`, `sequence`, `cluster_key`, `start_us`, `end_us`). Segments are rows, not one JSON blob.

A successful run is an `AnalysisRun` of kind `diarization`. Its config records the profile, implementation version, analysis window, source container start, lightweight source fingerprint, FFmpeg version, feature config, cluster count, and decode config. It does not record a participant map.

Activating that run switches only the active diarization pointer. It does not replace `participant_assignment` or `turns`.

## Review and mapping

The speaker-analysis API returns, per cluster, the key, segment count, total voiced duration, and up to three representative ranges. Those ranges are the longer segments spread across the run. The desktop seeks the existing playback controller to the sample's canonical `start_us`.

Mapping is manual and belongs to one diarization run. Applying it requires the active transcript and the active diarization run. The engine calls the existing Phase 2 `assign_word` and `build_turns` functions. It does not realign words on its own.

That creates two new immutable runs:

- `participant_assignment`, depending on that transcript run and that diarization run, with the cluster map stored on the run
- `turns`, depending on the assignment run

Both active pointers switch in one database commit after both runs are written. A failed apply leaves the previous pointers in place. Older runs stay stored.

Unknown is a valid assignment. The transcript shows the participant display name, or `Unknown`. Cluster keys stay in the mapping UI.

## Transcript versions

An assignment belongs to one transcript run. After a new transcription becomes active, word pages do not show the old labels. The API checks that the active assignment depends on the current transcript. If it does not, speaker fields are omitted and the analysis state is stale. Nothing is reapplied by word sequence.

The diarization run does not depend on the transcript. The user can later choose **Apply speaker mapping to current transcript**. Phase 10 does not do that automatically.

Per-word speaker overrides are not a control in this phase. A single-word override can disagree with the generated turns, so that editing stays deferred. Stored override rows are still read only when the assignment matches the current transcript.

## Jobs

Kind: `diarize_audio`. The desktop may send `media_asset_id` and the profile id. It cannot send DSP parameters, a cluster count, an executable, or a path.

Progress uses basis points. Stages are coarse: decode, features, clustering, segments, then persistence. The job reaches 10000 only after the diarization run is stored and activated. Progress does not move backward.

Cancellation does not publish a partial run and does not change assignments or turns. Temporary files are removed.

If the engine stops while a job is queued or running, the next writable open marks it `INTERRUPTED`. Partial output is not authoritative. There is no resume. Retry creates a new job.

The job requires a present master with audio and an active transcript. A probed file with no audio fails before the worker.

## What this does not do

Automatic visual cluster-to-person mapping, overlap detection, multicam editing, camera directing, reels, conversation mapping, and a generic production diarizer are out of scope.

A later visual mapper would need its own evidence, a human-confirmed or separately validated link from cluster to participant, and it would still write through the same assignment and turn runs. A later generic diarizer would be a new profile. It could change the cluster count and the segment producer. It should leave `ParticipantId`, layout bindings, assignment rows, and turns in place.
