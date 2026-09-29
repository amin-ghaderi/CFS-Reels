# AMIX architecture review

Independent review of `docs/architecture/`, `docs/adr/`, `docs/migration/`, the root `README.md`, and `amix/README.md`.

I checked legacy code only where an architecture claim depended on it: `transcribe.py`, `cfs_audio_diarize_poc.py`, `cfs_overlap.py`, `cfs_offline_multicam_16x9.py`, `cfs_multicam_16x9.py`, `conversation.py`, `conversation_map.py`, `cursor_ai.py`, `faces.py`, `data/tmp_cfs03_preview/run_diarize_49_59.py`, and `data/tmp_edited_multicam/{diarize_edited,render_edited}.py`.

The existing documents and ADRs were not modified.

## Summary

| Severity | Count |
|---|---|
| BLOCKER | 1 |
| IMPORTANT | 13 |
| LATER | 8 |
| REJECTED CONCERN | 10 |

The core structure is sound for a small team: one engine process, SQLite plus files, capability-based AI, participant/region separation, immutable word times, and overlap that does not rewrite turns. Most findings are **underspecified rules** that would otherwise be decided ad hoc inside code, where they are expensive to reverse. The one blocker is a units error in the exact code path Phase 2 builds first.

---

## BLOCKER

### B-01 Legacy time import formula is off by a factor of 1000

- **Severity:** BLOCKER
- **Affected:** `TIMELINE_MODEL.md` (Conversion boundaries table)
- **Current decision:** “Legacy files that already used `round(seconds, 3)` import as `us = round(seconds, 3) * 1000`.”
- **Problem:** `round(seconds, 3) * 1000` gives **milliseconds**, not microseconds. It is also a float multiply, so `round(2960.123, 3) * 1000` gives `2960123.0000000005`, not an integer.
- **Failure scenario:** Phase 2 builds the legacy importer and the golden fixture from this sentence. If the fixture generator and the importer share the formula, every imported time is 1000× too small. The tests stay self-consistent, so they pass, while being wrong against the planner’s real-media thresholds: a 2 s minimum-turn rule compares against values that are 1000× too small. A second agent who notices the error and fixes only one side gets a large golden failure that looks like a planner bug.
- **Minimum correction:** Define the import as integer milliseconds first, then scale: `ms = round_half_away_from_zero(seconds * 1000)` and `us = ms * 1000`. Or parse the decimal string from JSON without a float round-trip. State that legacy imports therefore always land on whole-millisecond microsecond values.
- **ADR change:** No. ADR 0008 is correct; only the timeline document’s formula is wrong.

---

## IMPORTANT

### I-01 Time zero, stream start offsets, and variable frame rate are undefined

- **Severity:** IMPORTANT
- **Affected:** `TIMELINE_MODEL.md`, `MEDIA_PIPELINE.md` (PROBE, TRANSCRIBE, OVERLAP), ADR 0008
- **Current decision:** Times are microseconds “from the start of the referenced media asset”. Probe records `fps_num/fps_den`.
- **Problem:** “Start of the asset” has three plausible meanings: container time 0, the first video PTS, or the first audio sample. They differ on real files. MP4 edit lists, AAC priming, and screen or remote recordings can put the audio `start_time` at a non-zero value. Legacy code happens to be consistent only because every consumer uses FFmpeg `-ss` container time:
  - `transcribe_longform` extracts WAV chunks with `-ss` and adds the chunk offset.
  - `cfs_overlap.collect_lip_activity` computes frame time as `origin + index / SAMPLE_FPS`. That assumes constant frame rate and exact seek alignment, not decoded PTS.
  - The HTML `<video>` `currentTime` uses the browser’s own presentation timeline, which may subtract the first PTS.

  Variable-frame-rate sources (phone, OBS, and conferencing recordings are common for podcasts) have no single meaningful `fps_num/fps_den`. There, index-based frame timing drifts from true presentation time.
- **Failure scenario:** A master’s audio stream starts at 0.021 s and its video at 0.000 s, or a VFR recording drops frames. Word times (from audio) and overlap times (from frame indices) disagree by tens to hundreds of milliseconds. Late in a 2.5-hour VFR file the gap can reach seconds. Overlap-forced wide shots land on the wrong words, and the UI playhead and the transcript highlight disagree.
- **Minimum correction:**
  1. Define canonical zero as FFmpeg container presentation time, the same time base `-ss` uses.
  2. Probe records per-stream `start_time` and whether the video is constant or variable frame rate.
  3. Vision stages derive frame time from decoded PTS, not frame index.
  4. VFR policy: V1 either conforms VFR masters to a constant-frame-rate analysis/proxy file, recorded as an asset with provenance, or refuses them with a clear message. Pick one.
  5. The frontend converts between browser time and canonical time using the recorded offset, which is a probe field and not a guess.
- **ADR change:** Amend ADR 0008 with the time-zero definition (one sentence). The VFR policy can live in the pipeline document.

### I-02 Render frame allocation must snap absolute boundaries, not round per-shot durations

- **Severity:** IMPORTANT
- **Affected:** `TIMELINE_MODEL.md` (Frame snap), `MEDIA_PIPELINE.md` (RENDER_16x9), `MIGRATION_MAP.md` (16:9 row says ADAPT/preserve)
- **Current decision:** Render “may store the snapped boundary beside” the editorial value. The migration map tells porters to preserve the 16:9 render behavior.
- **Problem:** Legacy renders (`cfs_offline_multicam_16x9.render_offline`, `render_edited.py`) do `counts.append(round(dur * FPS))` per shot, put all the leftover drift on the **last** shot, seek each part with `-ss shot_start`, concatenate, then mux master audio. The picture inside shot *i* comes from `shot_start_i`, but it appears in the output at `sum(counts[:i]) / FPS`. The difference is the accumulated per-shot rounding error, a random walk of about `sqrt(N/12)` frames. For roughly 900 shots on a 2.5-hour master that is about 9 frames (around 290 ms) of lip-sync error in the middle of the program, “corrected” only at the end. The 10-minute test is too short to notice it.
- **Failure scenario:** A ported renderer preserves this behavior. Long Edited-style programs have visible mid-program lip-sync drift against stream-copied audio, and no golden catches it because the rendered stream is not asserted.
- **Minimum correction:**
  1. Convert every shot boundary to an absolute output frame index on the **output** frame grid.
  2. Derive each shot’s frame count as the difference of adjacent snapped boundaries.
  3. Seek each shot at the snapped boundary time.
  4. Distinguish the source frame grid (for seeking) from the output grid. Legacy forces `fps=30` regardless of the source rate.
  5. Add one cheap render assertion: the cumulative frame index at each cut equals its snapped boundary.
- **ADR change:** No.

### I-03 Word-ID anchors cannot express real editorial cuts

- **Severity:** IMPORTANT (superseded for reels: AMIX V1 reel drafts are EditorialSequences on source microseconds; word-id ReelPlan is not the current product model — see ADR 0013)
- **Affected:** `DOMAIN_MODEL.md` (historical ReelPlan), `TIMELINE_MODEL.md`, ADR 0009
- **Current decision:** A Reel segment is `start_word_id..end_word_id`, expanded to the words’ times. Legacy timestamp-only plans snap to words.
- **Problem:** Whisper word boundaries are routinely early or late by 100–300 ms. Legacy padded them (`snap_range_to_words`, `pad_s=0.04`). Editors also cut inside the silence between words, add a breath of head or tail, or trim a clipped plosive. None of that can be expressed with ids alone. The documents also say both that the UI “writes edits back as integer microseconds” and that the player’s float “is not written as authority”, so a playhead-based trim has no defined home.
- **Failure scenario:** Every rendered Reel starts or ends clipped on a mistimed word. The first user request (“start 200 ms earlier”) forces either a schema change or reintroduces free timestamps, which ADR 0009 was written to prevent.
- **Minimum correction:** Keep the word id as the anchor and add an explicit signed **trim offset** in microseconds at each end. Validation bounds the offset by the neighboring words, or by a configured maximum, so a model cannot move a cut across content. Models still return ids only; offsets are set by deterministic padding rules or by the user. A playhead edit is converted by the engine into (nearest word id, offset).
- **ADR change:** Yes, a one-paragraph amendment to ADR 0009: an anchor is a word id plus a bounded offset.

### I-04 Active pointers are per project, but analysis is per source asset, and there is no staleness rule

- **Severity:** IMPORTANT
- **Affected:** `DOMAIN_MODEL.md` (Project, AnalysisRun), `STORAGE_ARCHITECTURE.md`, ADR 0010
- **Current decision:** `Project` holds one active id per kind. Runs record input artifact ids.
- **Problem:**
  1. The legacy case that motivated AMIX already has two timelines: raw `03.mp4` and `Edited.mp4`, each with its own transcript, diarization, turns, overlaps, and plan (“No timestamps from 03.mp4”). One active transcript per project cannot represent that.
  2. Nothing requires the active set to be consistent. The active turn run can be built from assignment run X while the active alignment pointer says Y.
  3. There is no defined answer to “is this downstream result stale?”
- **Failure scenario:** The user re-runs diarization and activates it. The active shot plan still displays, but it was built from turns of the old assignment run. The UI implies it is current, and a render ships the old decisions. Or the user adds the edited master, and activating its transcript silently deactivates the raw master’s transcript.
- **Minimum correction:**
  1. Key active pointers by `(source_asset_id, kind)`. Alternatively, declare one analyzed master per project in V1 and state it explicitly. Keying by asset is cheaper to do now than later.
  2. Define staleness as a query: a run is stale if any input run it recorded is not the active run of its kind for that asset.
  3. Stale results remain readable and renderable only with an explicit warning. Nothing is deleted.

  This is a query rule, not a dependency engine.
- **ADR change:** Amend ADR 0010 (pointer key plus staleness definition).

### I-05 Manual edits modeled as successor runs are lost when automation re-runs

- **Severity:** IMPORTANT
- **Affected:** `DOMAIN_MODEL.md` (SpeakerAssignment, Shot `manual_override`, AnalysisRun `manual_modification`, LayoutSpan), ADR 0010, ADR 0009
- **Current decision:** Hand edits create a successor run or revision with `manual_modification = true`. Shots carry a `manual_override` flag.
- **Problem:** User corrections are then a mutated copy of one automatic run. When the user retunes overlap or re-runs diarization, the new automatic run starts from scratch, and every speaker fix, shot override, and cluster-to-participant choice is gone or must be re-applied by hand. Re-transcription with a better model creates new word ids, which orphans every text revision, Reel plan, and thread anchored to the old ids. No policy says what happens to them.
- **Failure scenario:** An editor fixes 40 misattributed words and overrides 12 shots on a 2-hour episode, then updates the overlap threshold. The regenerated plan discards all 12 overrides. That is data loss from the user’s point of view, even though the old run still exists.
- **Minimum correction:**
  1. Store user decisions as a small **overlay** layer owned by the project, not by a run: speaker corrections keyed by word id, shot overrides keyed by source range, the cluster→participant map, and layout confirmations.
  2. Automatic stages read the overlay as an input and apply it after computation. The overlay’s hash is part of the cache key.
  3. Re-transcription creates a new transcript. Existing editorial objects stay bound to the old transcript, whose times remain valid for the same media. Moving them to the new transcript is an explicit, time-based remap with a report, never automatic.
- **ADR change:** Amend ADR 0010 (overlays as the home of manual edits) and ADR 0009 (anchors are transcript-scoped; remap is explicit).

### I-06 Pipeline dependencies and cache boundaries force expensive recomputation

- **Severity:** IMPORTANT
- **Affected:** `MEDIA_PIPELINE.md`
- **Current decision:** The DAG draws OVERLAP under TURNS (“needs video + layout + turns”), while the stage text lists inputs as video, layout, and span. DIARIZE optionally takes layout. The cache key is inputs, config, algorithm version, and model.
- **Problems:**
  1. Legacy overlap (`cfs_overlap.py`) does not read turns. If turns are an overlap input, one speaker correction invalidates the most expensive stage: a full decode at 8 fps with YuNet on every region for the whole master.
  2. Overlap mixes an expensive part (decode plus lip scoring, stored as `collect_lip_activity`) with a cheap part (thresholding, windowing, merging, `weaker >= 5.5`, the 2.5 s minimum). Retuning a threshold, which legacy did repeatedly, should not re-decode video.
  3. Diarization in legacy is two parts: anonymous clustering from audio, then mapping clusters to participants from vision. A layout change should only invalidate the mapping.
  4. **Analysis range is an input.** `diarize_edited.py` clusters only the *directable* regions: protected intervals are excluded, and the speech gate is the 18th percentile of energy **within those regions**. `overlaps_from_activity` gates on the 25th percentile of the analyzed span. Changing protected regions or the span changes diarization and overlap output. The DAG does not list protected regions as a diarization input.
- **Failure scenario:** The user fixes one word’s speaker and waits another hour-plus for overlap on a 2.5-hour master. Or the user edits a protected region, and diarization is silently reused from a cache computed over a different range.
- **Minimum correction:**
  1. OVERLAP inputs are video, layout bindings, and analysis range. No turns.
  2. Split overlap into cached **lip activity** (expensive) and **region detection** (cheap).
  3. Split diarization into **cluster** (audio plus analysis range) and **map** (clusters plus layout plus overlay).
  4. Add “analysis range / exclusion mask” as an explicit input with a hash for diarize and overlap.

  With that, partial recomputation works as intended:

  | Change | Recomputes |
  |---|---|
  | Transcript text | Semantic tasks only |
  | Speaker assignment (overlay) | Turns and shot plan |
  | Layout | Mapping, lip activity, overlap, shot plan |
  | Semantic provider | That task and its dependents |
  | Reel decision | That Reel’s render |
  | Render settings | Render only |
- **ADR change:** No.

### I-07 The migration map overstates what is proven and hides a dependency on a deferred module

- **Severity:** IMPORTANT
- **Affected:** `MIGRATION_MAP.md`, `LEGACY_INVENTORY.md` (the status labels it inherits), `GOLDEN_TEST_STRATEGY.md`
- **Current decision:** Audio diarization is “PROVEN / EXPERIMENTAL, ADAPT”. The visual verifier (`cfs_offline_verify.py`) is “REIMPLEMENT LATER, not on the V1 critical path”. Conversation mapping is “ADAPT”.
- **Problems verified in code:**
  1. `cfs_audio_diarize_poc.py` hard-codes `N_SPEAKERS = 3`, which is k-means with fixed k. For a two-person show, one voice is split into two clusters.
  2. Its cluster→participant mapping votes with **hand-inspected solo frames at CFS03-specific timestamps** (`VISUAL_SOLOS`) and a file-specific `HELDOUT` window. The accepted 49–59 result is therefore partly HAND-AUTHORED.
  3. The mapping (`map_clusters`, and `map_on_this_timeline` in the Edited path) calls `measure_mouth_window` / `open_verifier` from **`cfs_offline_verify`**, the module the map defers. V1 would have no automatic path from clusters to participants.
  4. `conversation_map.py` builds its prompt input from `speakers.json`, produced by `speakers.py`, the silence-gap system the map says not to migrate. `conversation.py` wires `attribute_speakers` directly. A porter who “adapts” `map_conversation` inherits the superseded speaker system.
- **Failure scenario:** Phase 3 ports diarization as “proven”, discovers that mapping needs the deferred verifier and hand anchors, and either quietly pulls the experimental verifier into the critical path or ships a two-person show with three clusters. Conversation mapping is ported and runs on silence-gap speaker blocks rather than diarized turns.
- **Minimum correction:**
  - Reclassify diarization as “clustering: PROVEN on CFS03 windows with k=3; mapping: HAND-ANCHORED”.
  - State that k comes from the number of participants bound in the analysis range.
  - Move the **mouth-activity measurement** (not the verifier’s override behavior) into the V1 migration list, because both mapping and overlap need it.
  - Make V1 mapping a user-confirmed step: suggested by mouth votes, confirmed or overridden in the overlay (see I-05).
  - Note on the conversation-mapping row that its input must be rebased from `speakers.json` blocks to turn ids.
- **ADR change:** No.

### I-08 `full` presentation silently depends on CFS’s exact 16:9 tiles

- **Severity:** IMPORTANT
- **Affected:** `DOMAIN_MODEL.md` (LayoutRegion, Shot), `MEDIA_PIPELINE.md` (RENDER_16x9, OVERLAP), ADR 0007
- **Current decision:** `full` means “crop that participant’s bound region for this time, scale to the output frame”. A region is used both for analysis (faces, lips) and for framing.
- **Problem:** This works in legacy only because CFS tiles are exactly 16:9 (`TILES`: 896×504; the code comment says “exactly 16:9, so this fills 1920x1080 with no pad”). A two-person side-by-side show has roughly 960×1080 regions. Crop-and-scale either distorts the picture or needs an unspecified crop or pad policy. Overlap also hard-codes `FRAME_W, FRAME_H = 1920, 1080` and one largest face per tile. The documents also do not say what the planner does when the floor participant has **no binding** in the active layout span (full-screen graphic, off-camera voice, a participant who changed position).
- **Failure scenario:** The first non-CFS show renders stretched faces, or someone adds a “CFS mode” flag to avoid them. A full-screen graphic span needs a manually drawn ProtectedRegion, or the planner emits `full(participant)` with no region to crop and fails at render.
- **Minimum correction:**
  1. Separate a region’s **analysis rectangle** from its **framing rectangle**. The framing rectangle defaults to the analysis rectangle and is constrained to the output aspect ratio. One extra rectangle is enough; do not add a framing engine.
  2. Resolution-independent regions: store the profile’s reference size and scale to the probed size.
  3. Planner rule: `full(p)` is only valid where the active layout span binds `p`; otherwise the shot is `program_wide` with reason `unbound`. Graphics then need no ProtectedRegion.
- **ADR change:** Small amendment to ADR 0007 (full shots require a binding and an aspect-valid framing rectangle).

### I-09 OFFLINE cannot currently be a hard guarantee

- **Severity:** IMPORTANT
- **Affected:** `AI_PROVIDER_ARCHITECTURE.md`, `DESKTOP_ARCHITECTURE.md`, `MODEL_DISTRIBUTION.md`, ADR 0006
- **Current decision:** Offline routes only to adapters with `execution = local`. Media stages have no provider slot.
- **Problems:**
  1. `execution` is a label on configuration. An “OpenAI-compatible” endpoint marked local can point at a remote host.
  2. Legacy libraries download implicitly. `faces.ensure_yunet_model()` fetches YuNet from GitHub (`urlretrieve`). `faster_whisper.WhisperModel(name)` pulls weights from Hugging Face when given a model name instead of a path. Wrapping these “as proven” adds network calls to *media* stages.
  3. Auto-update checks, crash reporting, and telemetry are not mentioned, so a later agent may add them with no offline gate.
  4. The WebView could load remote fonts or scripts unless the content security policy forbids it.
  5. The Cursor adapter sends the prompt to a cloud model and runs with `--trust --workspace <repo>`.
- **Failure scenario:** A user in Private mode opens a sensitive recording on a machine without YuNet. The overlap stage silently downloads the model, and the transcript stage reaches Hugging Face. Neither is project data, but the “no network” promise is broken, and a user-defined “local” endpoint on a LAN or VPN host sends the transcript off the machine.
- **Minimum correction:**
  1. All outbound network use in the engine goes through **one** gated client that refuses in Offline mode.
  2. Models load by local path only. Set the Hugging Face offline environment variables, and never pass a model name that can download.
  3. Classify `local` by endpoint (loopback address), not by user label.
  4. Offline mode disables update checks. V1 declares **no telemetry**.
  5. The shell sets a content security policy that allows no remote origins.
  6. The Cursor adapter is always classified as cloud.
- **ADR change:** Amend ADR 0006 with the enforcement rule (one sentence: offline is enforced at the engine egress and the shell, not by labels).

### I-10 Capabilities belong to models, and output enforcement differs by backend

- **Severity:** IMPORTANT
- **Affected:** `AI_PROVIDER_ARCHITECTURE.md`, ADR 0005
- **Current decision:** “An adapter advertises the subset it implements.” `LONG_CONTEXT` is a capability flag. Provenance stores a raw payload **hash**.
- **Problems:**
  1. Capabilities vary per model on the same adapter: one OpenAI-compatible server hosts models with and without JSON-schema support.
  2. `LONG_CONTEXT` is a number (context tokens) that the chunker needs, not a boolean.
  3. `GENERATE_STRUCTURED` has different strengths: server-enforced schema, JSON mode, grammar-constrained local decoding, or prompt-only text parsed afterward. Legacy Cursor is the last kind, via `extract_json_payload` on text output. Validation plus retry policy depends on which one is used.
  4. Storing only a hash means a validator bug fix requires paying for the call again, and there is no replay data for tests.
- **Failure scenario:** A task routed to a local model “with GENERATE_STRUCTURED” gets free text and fails every chunk. Or long-context routing sends 400k characters (the legacy `FULL_CONTEXT_CHAR_LIMIT`) to an 8k-context model. Testing semantic tasks requires live providers.
- **Minimum correction:**
  1. Capabilities and `context_tokens` live on `(provider, model)`.
  2. Record the structured-output mode as a model attribute. Each task defines its retry and repair policy against it.
  3. Store the raw response as a project artifact, which enables replay.
  4. A replay adapter that serves recorded responses is the standard test double.

  No new layers.
- **ADR change:** No. ADR 0005 already permits this.

### I-11 The golden “exact” layer asserts imported values against themselves

- **Severity:** IMPORTANT (required before Phase 2 builds the fixture)
- **Affected:** `GOLDEN_TEST_STRATEGY.md`
- **Current decision:** The exact layer’s *inputs* are words, assignments, turns, overlaps, and layout. Its *assertions* include words, assignments, turns, and the shot plan.
- **Problem:** If assignments and turns are inputs, asserting them tests only the importer. Alignment (`assign_word`: 0.55 majority fraction, 0.75 tie margin) and turn building (1.50 s gap, splits on speaker change) are deterministic and cheap to test exactly, but this design never runs them. Overlap region logic is also deterministic once lip activity is fixed, yet it is placed wholly in the tolerance layer.
- **Failure scenario:** A port changes `assign_word` tie handling or the gap comparison (`<=` vs `<`, which is exactly the half-open migration). Assignments and turns shift, and the golden passes because it compares fixture turns to fixture turns.
- **Minimum correction:** Restructure by stage.

  | Layer | Inputs | Asserted outputs |
  |---|---|---|
  | Exact | Words; diarization segments; cluster map; lip-activity series (about 600 s × 8 fps × regions, a few hundred KB); layout; config | Assignments, turns, overlap regions, shot plan, all computed by AMIX code |
  | Tolerance | Media, when available | Decode and YuNet lip activity; clustering |

  Also:
  - Pin the analysis range (legacy origin 2960 s, duration 600 s) and the hand anchors in the fixture config, because the gates are window-relative (I-06).
  - Report failures as a semantic diff (first differing turn or shot, with ids and times), not a raw JSON diff. At about 1,500 words, about 100 turns, and a few dozen shots, the fixture stays reviewable.
- **ADR change:** No.

### I-12 The per-project SQLite location and lifecycle need guardrails

- **Severity:** IMPORTANT (before any project database is written)
- **Affected:** `STORAGE_ARCHITECTURE.md`, `DESKTOP_ARCHITECTURE.md`
- **Current decision:** A project is a copyable folder containing `project.sqlite`. Alembic migrates forward. Portability is by copying the folder.
- **Problems:**
  1. On Windows, Documents is often synced by OneDrive by default, and users put projects in Dropbox or iCloud or on network shares. SQLite, especially in WAL mode, is not safe under file-sync or network locking. Sync tools also upload the `-wal` and `-shm` files mid-write.
  2. Nothing prevents two AMIX instances, or two machines through a synced folder, from opening the same project.
  3. A forward migration on the user’s only copy has no rollback.
- **Failure scenario:** A project in a OneDrive folder is corrupted or forked by the sync client during a long job. Or an app update migrates `project.sqlite`, fails partway, and leaves an unopenable project.
- **Minimum correction:**
  1. A project lock file with owner, process, and host.
  2. Detect known sync and network locations and warn. Write-heavy cache and artifacts may live outside the folder (see L-05).
  3. Copy `project.sqlite` before every migration.
  4. Explicitly document one writer per project (the engine).
- **ADR change:** No.

### I-13 Desktop lifecycle details that fail on real machines

- **Severity:** IMPORTANT (before the desktop phase)
- **Affected:** `DESKTOP_ARCHITECTURE.md`, `MEDIA_PIPELINE.md` (PROXY)
- **Current decision:** Tauri picks port 0 and passes the port to the sidecar. A header token protects the API. On shell exit, the engine is not left running. Playback uses a custom protocol or the engine. The proxy is optional.
- **Problems:**
  1. **Port.** The shell cannot know an ephemeral port it did not bind. Pre-selecting a free port and passing it is racy. The sidecar should bind port 0 and report the chosen port back over stdout.
  2. **Zombies.** On Windows, killing or crashing the shell does not kill the sidecar or its FFmpeg grandchildren. That needs a Job Object with kill-on-close. On macOS, the sidecar must exit when its parent dies (stdin end-of-file or a parent-process check).
  3. **Media authentication.** `<video src>` cannot send a header, so the token ends up in the URL and in engine access logs unless those logs are disabled. Tauri’s custom protocol range support for multi-gigabyte files has been unreliable; engine-served range requests are the safer default.
  4. **Codecs.** WebView2 does not play ProRes and plays HEVC only with an OS extension. WKWebView behavior differs again. For such masters the proxy is **required** for playback, not optional.
  5. **Projects per instance.** It is unclear whether a second window can open another project. V1 should say one open project per app instance.
- **Failure scenario:** Users accumulate orphaned `python` and `ffmpeg` processes holding files open, so the next launch cannot open the project. The engine port collides at startup. A ProRes master shows a black player.
- **Minimum correction:** Record the five rules above in the desktop document. Loopback binding does not usually trigger a Windows firewall prompt; keep it strictly `127.0.0.1`.
- **ADR change:** No.

---

## LATER

### L-01 ProcessingJob and AnalysisRun both carry execution status

- **Affected:** `DOMAIN_MODEL.md`
- **Problem:** Both have running, failed, cancelled, and interrupted states. Crash recovery must reconcile two state machines.
- **Correction when the schema is written:** The job owns execution state. A run is written once, at success, as an immutable result record. Failed attempts live only on the job.
- **ADR:** No.

### L-02 Transcription performance on macOS and GPU packaging on Windows

- **Affected:** `MODEL_DISTRIBUTION.md`, stack table
- **Problem:** CTranslate2, and therefore faster-whisper, has no Metal GPU backend. On Apple Silicon, long-form transcription is CPU-bound. On Windows, CUDA acceleration needs cuBLAS and cuDNN, which are large and license-gated. The “optional accelerator pack” is the right shape, but multi-hour masters on CPU may be unacceptable on Macs.
- **Correction:** Benchmark a 2-hour master on target Macs before Phase 3. The transcription stage already records its engine id, so a second ASR engine can be added without domain changes.
- **ADR:** No, unless the benchmark fails.

### L-03 The FFmpeg license decision changes the render encoder

- **Affected:** `MODEL_DISTRIBUTION.md`, `MEDIA_PIPELINE.md`, golden render checks
- **Problem:** Legacy renders with `libx264`, which is GPL. An LGPL FFmpeg build excludes it, so render would move to platform encoders (VideoToolbox, Media Foundation, NVENC, QSV) or another encoder, with different quality and flags.
- **Correction:** Treat the encoder as render config with a capability check. Golden render checks must not assume `libx264`. The license itself is not decided here.
- **ADR:** No.

### L-04 Freezing and signing the Python sidecar

- **Affected:** `MODEL_DISTRIBUTION.md`, `DESKTOP_ARCHITECTURE.md`
- **Problem:** numpy, scipy, OpenCV, CTranslate2, and FastAPI produce hundreds of native binaries. macOS notarization requires every nested `.so`/`.dylib` to be signed under the hardened runtime. Single-file freezers that extract to a temp directory at startup break signing, slow startup, and trigger Windows antivirus false positives.
- **Correction:** Plan an unpacked (directory-mode) sidecar signed file by file. Avoid runtime `pip`, dynamic plugin imports, and self-modifying install directories in the engine. Prove signing and notarization with a trivial sidecar early.
- **ADR:** No.

### L-05 Cache and proxies inside the portable project folder

- **Affected:** `STORAGE_ARCHITECTURE.md`
- **Problem:** `cache/` and `proxy/` can reach tens of gigabytes. Treating the whole folder as the backup and portability unit makes copies huge and pushes the write-heavy files into synced locations (I-12).
- **Correction:** Mark `cache/` and `proxy/` as disposable and rebuildable. Allow a per-machine cache root outside the project. Backup equals the database, manifest, active artifacts, and media.
- **ADR:** No.

### L-06 Project references into the global database

- **Affected:** `DOMAIN_MODEL.md`, `STORAGE_ARCHITECTURE.md`
- **Problem:** Runs reference `model_id`, and custom task routing references `provider_config_id`, both of which live in the per-machine global database. On another machine those ids may not exist.
- **Correction:** Runs store a snapshot (model id, version, hash, provider kind), never a foreign key into the global database. Project-level routing, if any, references provider *kinds* and model ids, and resolves them locally.
- **ADR:** No.

### L-07 Generative and decision roles duplicate capabilities

- **Affected:** `AI_PROVIDER_ARCHITECTURE.md`
- **Problem:** “GenerativeProvider” and “DecisionProvider” are fully derivable from the capability set. Two interface hierarchies would add a second axis for no substitution benefit.
- **Correction:** Keep them as documentation labels, not types.
- **ADR:** No.

### L-08 How secrets reach the engine

- **Affected:** `STORAGE_ARCHITECTURE.md`, `DESKTOP_ARCHITECTURE.md`
- **Problem:** “Supplied by the shell or by a small local unlock” leaves two paths open.
- **Correction:** Pick one before the first cloud adapter. Either the shell reads the OS store and passes the secret per call over the token-authenticated loopback, or the engine reads it through the OS store API itself. Either way, redact secrets from logs and crash reports.
- **ADR:** No.

---

## REJECTED CONCERNS

| ID | Concern | Why it is acceptable for V1 |
|---|---|---|
| R-01 | FastAPI on loopback is heavier than stdio IPC | Progress streaming, cancel, and especially HTTP range requests for playback are native to HTTP. stdio JSON-RPC would need a separate media path. Loopback plus a per-session token is adequate once I-13 is applied. |
| R-02 | Microseconds instead of rational time or 90 kHz ticks | Integers remove drift. The only inexactness is frame snapping, which the design already treats as an explicit, separate value. Rational storage would complicate every comparison for no V1 gain. |
| R-03 | Word, assignment, and turn rows in SQLite are too many | A 2.5-hour master is about 25k words. Even with several runs, that is well within SQLite’s comfortable range. |
| R-04 | SQLite rather than PostgreSQL | Single-user local app. No blocking reason. |
| R-05 | No time mapping between a raw master and an edited master | Legacy already analyzed Edited.mp4 independently (“No timestamps from 03.mp4”). Separate analysis per asset is correct for V1 once I-04 keys pointers per asset. |
| R-06 | `program_wide` and `protected_master` render the same pixels | They differ in intent: an editorial choice versus an editability lock. Keeping both prevents the planner or a user override from “fixing” a protected span. |
| R-07 | Layout spans without bindings duplicate ProtectedRegion | They describe different things: what is physically on screen versus what the editor forbids. With I-08’s unbound fallback, graphics do not need a ProtectedRegion, and protection remains a deliberate lock. |
| R-08 | One engine process, one active job per stage, no queue system | Correct for a desktop app. The job table with a worker token is enough. |
| R-09 | Future team or cloud processing would force a rewrite | UUID identities, immutable runs, content hashes, and a per-project database are sync-friendly. The loopback API can gain real authentication later. Nothing here forces a rewrite; only external absolute media paths need resolution by hash, which the design already records. |
| R-10 | Full-file hashing of multi-gigabyte masters on open | The document already allows a recorded fast hash (for example, size plus sampled blocks) with full verification on demand. |

---

## Participant and layout check (area 4)

Apart from I-07 and I-08, the separation holds. `Participant` carries no geometry. `LayoutSpan` plus bindings supports two people, three people, more later, position changes, graphics spans, intro and outro, and protected sections. Assumptions that would quietly recreate CFS behavior, all covered by the findings above:

- Fixed k=3 clustering (I-07)
- Exact-16:9 tiles as framing (I-08)
- 1920×1080 hard-coded analysis frames (I-08)
- Three `mouth_activity_a/b/c` evidence fields in overlap output (I-08)
- Hand-anchored cluster mapping presented as automatic (I-07)

## Future scale (area 13)

Today’s choices do not force a complete rewrite for team projects, central processing, or multiple workers, provided I-04 (per-asset pointers), I-05 (overlays separate from runs), and L-06 (snapshots, not cross-database foreign keys) are applied. Those three are also what a later sync design would need.

---

## Phase 2 Readiness

**READY WITH SMALL CORRECTIONS**

The recommended Phase 2 scope is: time helpers, legacy importer, pure alignment, turn, overlap-region, and shot-planner logic, and the CFS03 49–59 golden fixture. Required before that work starts:

1. **B-01.** Fix the legacy import formula in `TIMELINE_MODEL.md` (integer milliseconds × 1000, no float round-trip).
2. **I-01 (import part only).** State that canonical zero is FFmpeg container presentation time, the same base as legacy `-ss` times. The VFR policy and frontend offset can wait for their phases.
3. **I-11.** Restructure `GOLDEN_TEST_STRATEGY.md` so the exact layer feeds words, diarization segments, the cluster map, the lip-activity series, layout, and pinned config (including the 2960 s / 600 s analysis range), and asserts computed assignments, turns, overlap regions, and shots.
4. **I-08 (planner part only).** Add the planner rule that `full(participant)` requires a binding in the active layout span, with `program_wide` / `unbound` otherwise.
5. **I-06 (overlap inputs only).** Remove turns from overlap’s inputs in `MEDIA_PIPELINE.md`, so the Phase 2 overlap-region logic is not built with a false dependency.

The remaining IMPORTANT findings belong before the database, render, desktop, or provider work that each one touches, not before Phase 2.

## Things We Should Explicitly NOT Change

- **Integer microseconds with half-open ranges** as the single stored clock (ADR 0008).
- **Immutable word times;** text corrections as revisions that never move times; semantic outputs as ids (ADR 0009, extended by I-03 but not replaced).
- **Overlap as a separate layer** that never rewrites turns or word speakers. Turns split on speaker change without requiring silence.
- **The 16:9 shot vocabulary:** one full participant, the untouched program frame, or a protected master span. No designed composites, no reaction inserts in V1.
- **Participant identity separate from screen region,** with layout spans over time. No A/B/C in the domain (ADR 0007).
- **No provider slot on media stages.** Cloud only for semantic tasks. Offline mode never falls through to the network (ADR 0006, strengthened by I-09).
- **Capability- and task-contract-based AI** with engine-side validation and explicit fallbacks. Cursor stays a development adapter (ADR 0005).
- **Explicit run records and active pointers instead of filename authority** (ADR 0010, refined by I-04 and I-05).
- **Global SQLite plus per-project SQLite plus filesystem.** No media blobs in the database. Secrets only as OS credential references (ADR 0004, ADR 0012).
- **One Python sidecar started by a thin Tauri shell,** with no business logic in Rust and no media intelligence in React (ADR 0002, ADR 0003).
- **No distributed infrastructure in V1:** no Celery, Airflow, Kafka, event sourcing, or microservices.
- **`legacy/` as reference only;** the silence-gap `speakers.py` and resolver v2 stay out of the product.
- **Separate 9:16 and 16:9 plans and renderers,** sharing only time, words, turns, and FFmpeg invocation.
