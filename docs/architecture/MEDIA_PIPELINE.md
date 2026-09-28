# Media pipeline

V1 runs stages inside the Python engine. No Airflow, Celery, Prefect, or Kafka.

A stage has: inputs, outputs, config, algorithm version, cache key, status. Status lives on `ProcessingJob` and `AnalysisRun`.

## DAG

```
INGEST
  → PROBE
      → PROXY                 (optional; does not block transcribe)
      → TRANSCRIBE
          → NORMALIZE_TEXT    (optional semantic; text only)
          → DIARIZE           (parallel with normalize)
              → ALIGN
                  → TURNS
                      → OVERLAP          (needs video + layout + turns)
                      → CONVERSATION_MAP (optional semantic)
                          → REEL_CANDIDATES
                              → REEL_SCORE (optional)
                                  → REEL_PLAN
                                      → RENDER_9x16
                      → SHOT_PLAN        (turns + overlap + layout + protected)
                          → RENDER_16x9
```

NORMALIZE_TEXT is not an input to ALIGN, TURNS, OVERLAP, or SHOT_PLAN. Those read raw word times and assignments.

OVERLAP is not an input to TURNS. The floor is already decided.

SHOT_PLAN waits for overlap when the user asked for overlap-aware directing. A user may plan without overlap; missing overlap is then an explicit config (`overlap = off`), and the plan does not invent wide shots for overlap.

REEL stages wait for turns and a text revision if one exists; they can run on raw text if normalization was skipped.

## Stages

### INGEST

- **Inputs.** User-selected file.
- **Outputs.** `MediaAsset` row, path, hash. No decode required to finish ingest.
- **Config.** Copy into project or link externally.
- **Cache.** Hash of bytes. Re-ingest of the same hash reuses the asset.

### PROBE

- **Inputs.** Asset path.
- **Outputs.** Duration, fps rational, codecs, size. Probe blob stored as an artifact; summary columns on the asset.
- **Tool.** ffprobe, version recorded.

### PROXY

- **Inputs.** Master, target height.
- **Outputs.** Proxy asset.
- **Config.** Scale, codec. Playback may use the proxy. Analysis that needs full-frame lips (overlap, YuNet) uses the master unless a later ADR says a proxy is sufficient.
- **Skip.** Allowed. Not required to transcribe.

### TRANSCRIBE

- **Inputs.** Audio extract (FFmpeg WAV) or master audio.
- **Outputs.** `Transcript` and `Word` rows. Immutable times.
- **Config.** Model id, language hint, beam/settings that affect decode, chunking policy for long media.
- **Cache.** Audio hash + model version + config hash.
- **Behavior to preserve.** Local faster-whisper, word timestamps, chunking and reuse for long files. Times enter storage only through the microsecond conversion.

### DIARIZE

- **Inputs.** Audio, participant count hint if known, layout optional for later mapping.
- **Outputs.** Anonymous segments with times, then a cluster→participant map when the user has confirmed layout. Mapping may be a separate substep so diarization can finish before names exist.
- **Config.** Windowing and clustering parameters (versioned). Legacy implementation is MFCC and spectral-centroid clustering into anonymous speakers, then a visual map onto participants. That behavior is the migration reference, not a promise that the first AMIX code must paste the POC module unchanged.
- **Cache.** Audio hash + config + algorithm version.

### ALIGN

- **Inputs.** Words, diarized segments, cluster map.
- **Outputs.** `SpeakerAssignment` rows.
- **Config.** Majority fraction and tie margin (legacy defaults 0.55 and 0.75).
- **Deterministic.** No LLM.

### TURNS

- **Inputs.** Words in order, assignments.
- **Outputs.** `Turn` rows.
- **Config.** Same-speaker gap (legacy 1.50 s).
- **Deterministic.**

### OVERLAP

- **Inputs.** Master video, layout regions, time span.
- **Outputs.** `OverlapRegion` rows.
- **Config.** Sample rate, window, step, lip thresholds, minimum duration. Legacy values that produced the accepted 10-minute test are the first regression baseline (including the later retune: weaker lip threshold, minimum duration). Exact constants belong in the golden fixture’s config snapshot, not copied into this document as a new invention.
- **Rule.** Does not modify turns.
- **Deterministic** given pixels and config. Vision noise is why golden tests for this stage use tolerances or frozen intermediate activity — see [GOLDEN_TEST_STRATEGY.md](GOLDEN_TEST_STRATEGY.md).

### NORMALIZE_TEXT / CONVERSATION_MAP / REEL_* 

Semantic tasks in [AI_PROVIDER_ARCHITECTURE.md](AI_PROVIDER_ARCHITECTURE.md). Each is a stage with the same job/cache machinery. Fallback is part of config.

Heuristic Reel mining (keyword windows) is a local stage with no provider. It may run even when `reel_candidate_generation` is skipped.

### SHOT_PLAN

- **Inputs.** Turns, optional overlaps, layout spans, protected regions, planner config.
- **Outputs.** `ShotPlan` covering `[0, duration_us)` with no gaps or overlaps in shot ranges.
- **Config to preserve conceptually.**
  - Full-frame on the floor participant when the turn is “meaningful” (legacy: named participant, at least ~2 s, at least ~4 words — config, not A/B/C).
  - Program-wide when overlap is active; floor participant remembered but not framed full.
  - Program-wide on long wordless gaps (legacy ~12 s).
  - Protected regions win over all of the above and stay the master frame.
  - No reaction inserts.
  - No designed split-screen composites.
- **Deterministic** given those inputs. LLM does not place cuts.

### RENDER_16x9 / RENDER_9x16

- **Inputs.** Plan, source asset, encoder config.
- **Outputs.** Export asset, log, `RenderJob`.
- **16:9.** For `full`, crop the bound region and scale. For `program_wide` and `protected_master`, emit the source frame at the output size with no crop. Audio stream-copy when the source codec is acceptable; otherwise encode. Record which happened.
- **9:16.** Legacy Reel renderer (static/frozen vertical layouts, subtitles, stack order) is the behavioral reference. It stays a separate renderer from 16:9. Shared code is limited to FFmpeg invocation, time formatting, and asset records.
- **Cache.** Plan hash + source hash + encoder config + FFmpeg version. Re-render is explicit if the user wants a new file anyway.

## Jobs

- One active job per stage per project in V1, to keep CPU/GPU contention understandable. Queue is a table ordered by `created_time`.
- Cancel sets a flag the stage checks between chunks (transcribe chunks, FFmpeg segments). Kill the FFmpeg child on cancel.
- Resume: if `status = interrupted` or `running` after process start, mark `interrupted`, then rerun from the last cache-complete stage. Partial FFmpeg outputs are discarded.
- Progress events: stage id, fraction, short message. See desktop doc.

## Versions

`algorithm_version` changes when outputs can change for the same input. Cache keys include it. Golden fixtures pin it.

## Explicit non-goals

- Distributed workers.
- A plugin stage API.
- Rewriting diarization inside the shot planner.
- Using the legacy `speakers.py` silence-gap path as a hidden fallback when diarization returns `unknown`. Unknown stays unknown unless the user assigns a participant.
