# AMIX product architecture

Status: architecture specification. No product runtime exists yet.

AMIX is a local-first, cross-platform desktop application for long-form conversational video: transcription, speaker-aware timelines, conversation mapping, Reel discovery, multicam directing, and rendering.

`legacy/` is the working CFS/Reels reference. It is not the product. New work lives in `amix/`. See [MIGRATION_MAP.md](MIGRATION_MAP.md).

## What V1 is

A single-user desktop app that can open a project, ingest a master video, run a resumable local pipeline, and keep every derived result traceable to source media, algorithm version, and optional AI provider.

V1 does not include team sync, a cloud control plane, a plugin marketplace, or a second timeline engine.

## Product principles

1. **Local-first.** Probe, proxy, transcribe, diarize, align, turns, overlap, shot planning, and render run without a network.
2. **Provider-independent.** Editorial AI targets capabilities and task contracts. No task may require Cursor, Grok, OpenAI, Anthropic, Gemini, Jev, or llama.cpp by name.
3. **Cross-platform.** Windows and macOS are equal targets. Paths, credentials, and packaging differ; domain state does not.
4. **Installable.** The user does not install Python, FFmpeg, Node, Rust, or a Whisper runtime. Large models download separately. See [MODEL_DISTRIBUTION.md](MODEL_DISTRIBUTION.md).
5. **Deterministic media time.** Clocks, cuts, and render ranges are data. An LLM must not invent timestamps. See [TIMELINE_MODEL.md](TIMELINE_MODEL.md).
6. **Semantic AI only for meaning.** Normalization text, thread labels, Reel selection, and summaries may use a model. Word times, speaker alignment math, overlap detection, and FFmpeg filters must not.
7. **Participant-generalized.** Domain identities are `ParticipantId`. Two, three, and later N participants share one model. `speaker_a` / `FULL_A` are legacy serialization only.
8. **Auditable.** Derived artifacts record source, provider, model, versions, configuration, dependencies, time, and content hashes.
9. **Recoverable.** Jobs resume, cache, cancel, and recover after a crash. See [MEDIA_PIPELINE.md](MEDIA_PIPELINE.md) and [DESKTOP_ARCHITECTURE.md](DESKTOP_ARCHITECTURE.md).
10. **Small surface.** Abstractions exist only where a real substitute or a hard product boundary exists (AI providers, OS credentials, media tools).

## Agreed stack

| Layer | Choice |
|---|---|
| Desktop shell | Tauri 2 |
| UI | React, TypeScript |
| Local engine | Python 3.12, FastAPI, Pydantic |
| Structured state | SQLite, SQLAlchemy, Alembic |
| Large data | Filesystem |
| Media tools | FFmpeg, ffprobe |
| Local ASR | faster-whisper, CTranslate2 |
| Vision used by migrated logic | OpenCV, YuNet |
| Local LLM direction | llama.cpp or an equivalent adapter behind a capability |
| AI | Provider-independent. See [AI_PROVIDER_ARCHITECTURE.md](AI_PROVIDER_ARCHITECTURE.md) |

These are decisions unless a later ADR records a contradiction. None was found in the legacy media path: FFmpeg and local ASR already do the deterministic work; Cursor is only the current semantic client.

## Runtime shape

```
Tauri shell
  window, dialogs, sidecar lifecycle, OS credential bridge
        │
React UI
  workspaces, playback, editorial review
        │  localhost HTTP + job events
Python engine
  pipeline, domain rules, SQLite, filesystem, FFmpeg, local ML
```

The UI does not implement media intelligence. Python does not draw the desktop. The Rust shell does not own editorial or timeline rules. Detail: [DESKTOP_ARCHITECTURE.md](DESKTOP_ARCHITECTURE.md).

## Operating modes

| Mode | Media pipeline | Semantic tasks |
|---|---|---|
| Private / offline | Local only. Missing weights or runtime files fail as `resource_missing`. No download, no cloud fallback. | Local model already on disk, or skipped with an explicit gap |
| Hybrid | Local only | Optional decision/scoring service; selected semantic tasks may use cloud |
| Best quality | Local only | A frontier cloud model may be chosen for selected semantic tasks |
| Custom | Local only | User assigns a provider per task |

Cloud is never a silent requirement for ingest, probe, transcription, diarization, alignment, turns, overlap, shot planning, or render. Offline mode does not fetch Whisper weights, YuNet, or any other runtime file that the legacy tools downloaded on first use. If a semantic task has no configured provider, the project still opens and the media timeline remains usable.

## Workspaces

Pixel layout is out of scope. Each workspace reads domain data; it does not invent a second model.

| Workspace | Consumes |
|---|---|
| Projects | Project list from the global database, recent paths, missing-media flags |
| Media | `MediaAsset`, probe, proxies, `LayoutProfile`, `ProtectedRegion` |
| Transcript | Active `Transcript`, immutable `Word`s, active text revision, playback time |
| Conversation | Participants, active speaker assignments, `Turn`s, `OverlapRegion`s, `ConversationThread`s |
| Multicam | Layout spans, protected regions, active `ShotPlan` / `Shot`s, the primary sequence's caption track, render status |
| Reels | `ReelCandidate`s, reel `EditorialSequence` drafts, the same caption track on a selected draft, render jobs for any output profile |
| Export | Render outputs, destination paths, job history |
| Settings / Models | Provider assignments, model manager, mode (offline / hybrid / best / custom), no secrets in the project file |

## Authority

Filename words such as `final`, `latest`, `v2`, and `resolved_v3_final` are not authority. The project database stores which analysis run and which artifact revision are active. Older runs stay readable.

## Pipeline in one picture

Deterministic spine, then two editorial branches:

```
INGEST → PROBE → PROXY (optional)

TRANSCRIBE → ALIGN → TURNS ─┐
DIARIZE (analysis window) ──┼→ SHOT PLAN → 16:9 RENDER
OVERLAP (video, layout,     │
         analysis window) ──┘

NORMALIZE → SEMANTIC TASKS → REEL DISCOVERY → REEL DRAFT → RENDER PROFILE
```

Overlap does not depend on turns. The analysis window is part of diarize and overlap identity: a 10-minute span is not the same job as the whole episode. Normalize (text only) feeds semantic tasks and does not feed clocks. Detail: [MEDIA_PIPELINE.md](MEDIA_PIPELINE.md).

## Domain

Entities, fields, and exclusions: [DOMAIN_MODEL.md](DOMAIN_MODEL.md).

Time: integer microseconds, half-open ranges. [TIMELINE_MODEL.md](TIMELINE_MODEL.md).

Storage split: global app database versus per-project SQLite plus files. [STORAGE_ARCHITECTURE.md](STORAGE_ARCHITECTURE.md).

## What this architecture refuses

- One `LLMProvider` interface that pretends every model can score, see, and emit tools.
- `speaker_a` / `FULL_A` as domain concepts.
- Business rules in Rust.
- Video blobs in SQLite.
- API keys in the project database.
- Celery, Airflow, Prefect, or Kafka in V1.
- A port, repository, and service for every noun.
- Copying `legacy/` into `amix/`.

## Over-engineering review

Reviewed before freezing this spec:

| Temptation | V1 decision |
|---|---|
| Hexagonal ports for FFmpeg, SQLite, and Whisper | One engine package. Swap FFmpeg by executable path. Swap ASR behind a single transcription function when a second engine exists, not before. |
| Generic event bus | In-process job records and a local progress channel. |
| Separate “decision service” process | A capability on the AI adapter, called by the semantic stage. |
| Shot-type enum per participant (`FULL_A`) | One presentation `full` plus `participant_id`. |
| Storing both float seconds and integer ticks | Integer microseconds only. Display and FFmpeg convert at the boundary. |
| Microservices for diarize vs render | One Python process, staged jobs, filesystem cache. |
| Plugin API | Provider and model registries are enough until a third-party contract is real. |
| Merging Reel and multicam into one “edit graph” framework | One editorial sequence model. Multicam is a visual treatment of that sequence, not a second timeline. |

## Self-review

| Concern | How this spec addresses it |
|---|---|
| Maintainability | One engine, explicit entities, few processes. |
| Installability | Sidecar Python, bundled FFmpeg, models on demand. |
| Windows / macOS | Tauri plus OS credential stores; domain is path-format neutral. |
| Offline | Media DAG has no cloud node. |
| Provider lock-in | Tasks name capabilities and schemas. Cursor is a dev/compatibility adapter, not the product API. |
| Provenance | `AnalysisRun` plus active pointers. |
| Timestamp integrity | Immutable word times; semantic edits use IDs. |
| Participant count | `Participant` and layout regions are independent. |
| Model replacement | Global model records; runs store the id they used. |
| Portability | Project folder, relative paths, content hashes, relink. |
| Migration safety | Golden fixtures from the CFS 10-minute multicam sample. [GOLDEN_TEST_STRATEGY.md](GOLDEN_TEST_STRATEGY.md). |
| Testability | Decision goldens need no video. Perception goldens are optional and local. |
| Later cloud / team | Project SQLite is the unit to sync later. V1 does not design that sync. |
| Over-engineering | Table above. |

## Related documents

- [DOMAIN_MODEL.md](DOMAIN_MODEL.md)
- [TIMELINE_MODEL.md](TIMELINE_MODEL.md)
- [STORAGE_ARCHITECTURE.md](STORAGE_ARCHITECTURE.md)
- [AI_PROVIDER_ARCHITECTURE.md](AI_PROVIDER_ARCHITECTURE.md)
- [MEDIA_PIPELINE.md](MEDIA_PIPELINE.md)
- [DESKTOP_ARCHITECTURE.md](DESKTOP_ARCHITECTURE.md)
- [MODEL_DISTRIBUTION.md](MODEL_DISTRIBUTION.md)
- [GOLDEN_TEST_STRATEGY.md](GOLDEN_TEST_STRATEGY.md)
- [MIGRATION_MAP.md](MIGRATION_MAP.md)
- [../adr/](../adr/)
