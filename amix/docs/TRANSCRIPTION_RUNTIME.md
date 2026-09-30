# Transcription runtime

Phase 9 adds local speech-to-text. It does not diarize, normalize with an LLM, or download models.

## Adapter

`amix_engine/adapters/stt/faster_whisper.py` is the only module that constructs a speech model. Application code, the FastAPI process, and the job handler do not import `faster-whisper`. The adapter accepts a local model directory, a transcription profile, a language override or automatic detection, a device, and a compute type. It returns neutral evidence: machine text, relative integer microseconds, optional confidence, and segment order. It does not assign participants.

Word timestamps are required. The V1 profile is `amix.transcribe.v1`:

- task `transcribe`
- beam size 5
- VAD filter on
- temperature `(0.0,)`
- word timestamps on

faster-whisper is not bit-deterministic across every device and build. The word times stored for a completed run are the authority for that run. The profile and the runtime versions are recorded on the AnalysisRun so a later reader can see what produced them.

## Local models only

A job resolves a model through `SpeechModelResolver` (`amix_engine/stt/resolver.py`). The transcription job, the AnalysisRun, and the Transcribe action depend on the descriptor, not on environment variables.

The Phase 9 resolver is a development adapter. It reads:

- `AMIX_STT_MODEL_PATH` — an existing directory that contains `model.bin`
- `AMIX_STT_MODEL_ID` — optional display id
- `AMIX_STT_MODEL_VERSION` — optional declared version
- `AMIX_STT_DEVICE` — `cpu` (default) or `cuda`
- `AMIX_STT_COMPUTE_TYPE` — `int8` by default

An empty path is `MODEL_MISSING` (`speech_model_missing`). A path that is set but is not a usable local directory is `INVALID_MODEL` (`invalid_speech_model`). There is no fallback to a repository name, a Hugging Face id, or a legacy cache. GPU selection is not automatic: `cuda` is used only when it is configured.

The worker sets `HF_HUB_OFFLINE` before importing the model library and passes `local_files_only=True`. A missing model fails the job. It does not open a download.

Phase 9 does not bundle weights. Whisper-compatible models do not share one license. A future Model Manager has to store license metadata for each model it installs.

`GET /v1/runtime/speech-model` is authenticated. It reports `READY`, `MODEL_MISSING`, `INVALID_MODEL`, or `RUNTIME_UNAVAILABLE`, plus a display name when one exists. It does not return the model path, and it does not browse the disk.

## What the Model Manager replaces

A later Model Manager supplies the same descriptor (`model_id`, display name, runtime, local path, declared version, a lightweight identity, device, compute type, capabilities). It does not need to change:

- the `transcribe` job spec (`media_asset_id`, optional language, profile id)
- AnalysisRun provenance
- transcript persistence or activation
- the desktop Transcribe action

The React client cannot send a model path, an executable, or a worker command.

## Worker

The job handler starts `sys.executable -m amix.amix_engine.workers.transcribe` with a spec file. That spec contains the source path, the resolved model path, the profile, the language, the canonical origin inputs the parent already checked, and a temporary result path. It does not contain secrets or a callable name.

Stdout is NDJSON progress and status. The transcript is a temporary JSON file, not a command argument. Human diagnostics go to stderr. The parent validates the file before it writes a transcript, then deletes the temporary directory.

Progress uses the existing 0..10000 scale and never moves backward. Segment end divided by the known source duration can advance it, capped at 9999. If the duration is unknown, progress stays put instead of inventing a percentage. 10000 is recorded only after the new transcript is persisted and activated.

Cancellation uses the same process-tree termination as FFmpeg. The worker is registered when it is spawned, so shutdown cannot miss a process that is still starting, and it does not release the project lock until that spawn has finished and the child is gone. On Windows that is `taskkill /T`, then a forced kill. On macOS and Linux it is the process group. A cancelled job does not publish words, does not switch the active transcript, and deletes the temporary result. If cancellation arrives after the transcript has already been persisted and activated, the successful activation stands.

The worker publishes its diagnostic pid, and the result JSON, by writing a temporary sibling and replacing the final path only after the bytes are flushed. Seeing the final path means the payload is complete. A partial result is not a transcript.

A crashed worker leaves a job that the next writable open marks `INTERRUPTED`. A partial result file is not a transcript and is not resumed. Retry creates a new ProcessingJob from the stored spec.

## Source media and time

Transcription reads the selected master MediaAsset. It does not read the preview proxy. If the master file is missing, the job fails with `media_missing` even when a proxy exists. A transcript that was already stored stays readable.

If a completed probe recorded no audio codec, the job fails with `media_has_no_audio` before inference. An asset that has not been probed is not treated as silent.

faster-whisper times are seconds from the start of the decoded file. AMIX converts each value once, with `Decimal`, to an integer number of relative microseconds, then adds the source MediaAsset's container start:

`canonical_us = source_container_start_us + relative_us`

A missing container start counts as 0. The start is not subtracted, and a non-zero start is not rebased to zero. Playback's canonical origin (`source start - proxy start`) is not an input. Phase 9 always analyzes the full source. The AnalysisRun window is that full span. There is no partial-window mode.

## Provenance and activation

A successful job writes one AnalysisRun (`kind=transcript`, profile `amix.transcribe.v1`), one Transcript, and new Word rows, then switches `active_analysis` in that same commit. The run records the source asset, profile, model id and runtime, lightweight model identity, faster-whisper and CTranslate2 versions, device, compute type, requested language, detected language and probability, the full-source window, and the origin rule `source_container_start_us`. The fingerprint is size, mtime, model identity, and profile. The filename is not the identity.

Failed and cancelled attempts stay in ProcessingJob history. They do not create an AnalysisRun.

The active transcript is unchanged while a job is queued, running, failed, cancelled, or interrupted. Re-transcription creates a new run, a new transcript, and new word ids. The previous run remains. Manual corrections stay on the old word ids. They are not copied onto the new words, and the old machine text is not rewritten.

The transcript language is the detected language when the model reports one, otherwise the requested code. The desktop uses that value for text direction. It does not change word times.

## Desktop

The Transcript workspace offers Transcribe when there is no active transcript, and Re-transcribe when there is. Re-transcribe warns that a new version becomes active only after success and that existing history and corrections are kept. The dialog shows the selected media, the model name, Auto (the default), and an optional Whisper language code. It does not show the model path or beam settings.

If the model is not configured, the workspace says so. It does not offer a download. A running job shows `Transcribing…` and a percent when the job has real progress, in addition to the Activity panel. Cancel calls the existing job API. Success reloads the active transcript and the first word page without reopening the project. Failure leaves the current transcript on screen. The failed job appears in Activity.

## Not in this phase

Diarization, speaker identity, overlap, transcript normalization, conversation mapping, multicam, reels, the timeline, waveform, model download, cloud transcription, and packaging.
