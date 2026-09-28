# Media pipeline

V1 runs stages inside the Python engine. No Airflow, Celery, Prefect, or Kafka.

A stage has: inputs, outputs, config, algorithm version, cache key, status. Status lives on `ProcessingJob` and `AnalysisRun`.

## DAG

```
INGEST → PROBE → PROXY                         (optional; playback only)

PROBE → TRANSCRIBE → ALIGN → TURNS ─────────┐
                 ↘                            ├→ SHOT_PLAN → RENDER_16x9
PROBE → DIARIZE (audio + analysis window) ───┘        ↑
                                                       │
PROBE → OVERLAP (video + layout + analysis window) ───┘

TRANSCRIBE → NORMALIZE_TEXT → CONVERSATION_MAP → REEL_CANDIDATES
TURNS ──────────────────────────────────────────────↗
    → REEL_SCORE (optional) → REEL_PLAN → RENDER_9x16
```

Overlap is a sibling of diarize and turns, not a child of turns. Shot planning is where turns and overlaps meet. Reels read turns and optional semantic output; they do not read overlap.

NORMALIZE_TEXT is not an input to ALIGN, TURNS, OVERLAP, or SHOT_PLAN. Those read raw word times and assignments.

OVERLAP does not read turns, and TURNS does not read overlap. Changing a speaker assignment or rebuilding turns must not invalidate the overlap decode. The shot planner is the stage that reads both.

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

- **Inputs.** Audio and the **analysis window** (and any exclusion mask inside that window). Layout is not required to cluster. A cluster→participant map is a later, separate substep.
- **Outputs.** Anonymous segments with times. The map, when it exists, is its own output and its own cache entry.
- **Config.** Windowing and clustering parameters, plus the analysis window. Legacy speech gating uses a percentile of energy **inside the analyzed span**, so a 600 s window and a full episode are different inputs even with the same audio file.
- **What the migrated proof actually is.** The working CFS path clusters with a fixed `k = 3`. It does not discover an arbitrary participant count. Mapping those clusters onto people in the 49–59 proof uses hand-chosen solo frames at CFS03-specific times and visual mouth evidence. That is pinned fixture evidence for the golden test, not a generic automatic diarizer. The domain still allows N participants; this implementation does not solve N-speaker discovery. Do not paste the POC in unchanged, and do not describe it as production diarization.
- **Cache.** Audio hash + analysis-window identity + config + algorithm version. The map’s cache key adds the cluster artifact and the mapping evidence. A speaker-assignment edit does not bust the cluster cache.

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

- **Inputs.** Master video, layout regions for the window, and the **analysis window**. Not turns. Not speaker assignments.
- **Outputs.** `OverlapRegion` rows.
- **Config.** Sample rate, window, step, lip thresholds, minimum duration, and the analysis window. Legacy audio gating uses a percentile of energy inside that span, so the window is part of the result. Exact constants belong in the golden fixture’s config snapshot, not copied into this document as a new invention.
- **Cache.** Changing turns or assignments does not rebuild overlap. Changing the window, the layout bindings, or the detector config does. The golden exact layer may skip the video decode and start from a frozen lip-activity series; that series is then the cacheable expensive input, and region detection is the cheap stage. Splitting those two caches in the product engine can wait until overlap is implemented; the dependency rule cannot.
- **Rule.** Does not modify turns.
- **Deterministic** given the activity series and config. Vision noise is why a fresh decode is a tolerance test. See [GOLDEN_TEST_STRATEGY.md](GOLDEN_TEST_STRATEGY.md).

### NORMALIZE_TEXT / CONVERSATION_MAP / REEL_* 

Semantic tasks in [AI_PROVIDER_ARCHITECTURE.md](AI_PROVIDER_ARCHITECTURE.md). Each is a stage with the same job/cache machinery. Fallback is part of config.

Heuristic Reel mining (keyword windows) is a local stage with no provider. It may run even when `reel_candidate_generation` is skipped.

### SHOT_PLAN

- **Inputs.** Turns, optional overlaps, layout spans, protected regions, planner config.
- **Outputs.** `ShotPlan` covering `[0, duration_us)` with no gaps or overlaps in shot ranges.
- **Config to preserve conceptually.**
  - Full-frame on the floor participant when the turn is “meaningful” (legacy: named participant, at least ~2 s, at least ~4 words — config, not A/B/C) **and** that participant has a layout-region binding on this span.
  - If the floor participant has no usable binding, emit the untouched program frame (`program_wide`). Do not stretch another region, reuse a binding from a different span, or abort the plan.
  - Program-wide when overlap is active; floor participant remembered but not framed full.
  - Program-wide on long wordless gaps (legacy ~12 s).
  - Protected regions win over all of the above and stay the master frame.
  - No reaction inserts.
  - No designed split-screen composites.
- **Framing.** `full` crops the bound region and scales it only when that crop already matches the output aspect, as the CFS 16:9 tiles do. The planner must not define `full` as stretching an arbitrary rectangle to 1920×1080. A framing policy for other aspect ratios is later work.
- **Deterministic** given those inputs. LLM does not place cuts.

### RENDER_16x9 / RENDER_9x16

- **Inputs.** Plan, source asset, encoder config.
- **Outputs.** Export asset, log, `RenderJob`.
- **16:9.** For `full`, crop the bound region and scale **without changing its aspect ratio**. CFS migration regions are already 16:9, so a direct scale to 1920×1080 is valid for those regions only. For `program_wide` and `protected_master`, emit the source frame with no participant crop. Audio stream-copy when the source codec is acceptable; otherwise encode. Record which happened.
- **9:16.** Legacy Reel renderer (static/frozen vertical layouts, subtitles, stack order) is the behavioral reference. It stays a separate renderer from 16:9. Shared code is limited to FFmpeg invocation, time formatting, and asset records.
- **Cache.** Plan hash + source hash + encoder config + FFmpeg version. Re-render is explicit if the user wants a new file anyway.

## Jobs

- One active job per stage per project in V1, to keep CPU/GPU contention understandable. Queue is a table ordered by `created_time`.
- Cancel sets a flag the stage checks between chunks (transcribe chunks, FFmpeg segments). Kill the FFmpeg child on cancel.
- Resume: if `status = interrupted` or `running` after process start, mark `interrupted`, then rerun from the last cache-complete stage. Partial FFmpeg outputs are discarded.
- Progress events: stage id, fraction, short message. See desktop doc.

## Versions

`algorithm_version` changes when outputs can change for the same input. Cache keys include it, the config snapshot, and the **analysis window** for any stage whose thresholds or features are computed from that span (diarize and overlap). A 49–59 minute window must not reuse a cache entry built on the whole episode. Golden fixtures pin the same identity.

## Offline resources

Before an offline job starts, the weights and runtime files it needs must already be on disk. Legacy first-use downloads (faster-whisper weights, YuNet) are not allowed in offline mode. A missing file is a `resource_missing` failure. It does not open a network connection. Model installation itself is later work; this rule is the contract.

## Explicit non-goals

- Distributed workers.
- A plugin stage API.
- Rewriting diarization inside the shot planner.
- Using the legacy `speakers.py` silence-gap path as a hidden fallback when diarization returns `unknown`. Unknown stays unknown unless the user assigns a participant.
