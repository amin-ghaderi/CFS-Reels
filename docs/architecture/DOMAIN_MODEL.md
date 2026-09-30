# Domain model

V1 entities for the project database. Global app records (installed models, provider registry, recent projects) live in the application database. See [STORAGE_ARCHITECTURE.md](STORAGE_ARCHITECTURE.md).

Identities are UUID strings unless noted. Times are integer microseconds. See [TIMELINE_MODEL.md](TIMELINE_MODEL.md).

`speaker_a`, `speaker_b`, `speaker_c`, `FULL_A`, `FULL_B`, and `FULL_C` are not fields in this model. A legacy adapter may map them at import.

## Project

**Purpose.** One editable show or job of work.

**Identity.** `project_id`.

**Fields.** Name, created/updated time, schema version, active pointers (transcript revision, alignment run, turn run, overlap run, shot plan, reel plans), default frame-rate rational, language hint (not hardcoded).

**Relationships.** Owns assets, participants, layouts, runs, jobs.

**Provenance.** Schema version on the project. Not a dump of every model used; those sit on runs.

**Does not hold.** API keys, video bytes, “current filename winner”, UI layout pixels.

## MediaAsset

**Purpose.** A file the project depends on: master, proxy, WAV extract, export.

**Identity.** `asset_id`.

**Fields.** Role (`master`, `proxy`, `audio_extract`, `export`, `sidecar`), relative or external path, content hash, byte size, container, video/audio codecs, width, height, `fps_num`, `fps_den`, video duration µs, audio duration µs, probe JSON hash.

**Relationships.** Many assets per project. Runs cite `source_asset_id`. Shots and words cite the master unless a field says otherwise.

**Provenance.** Probe tool version and probe time.

**Does not hold.** Editorial cuts, speaker names, transcript text.

## Participant

**Purpose.** A person (or labeled voice) in the conversation. Count is data: 2, 3, or more.

**Identity.** `participant_id`.

**Fields.** Display name, optional color, sort order, notes. Optional link to a diarization cluster id from a specific run (the cluster is not the identity).

**Relationships.** Assignments, turns, layout bindings, and full-frame shots reference participants.

**Provenance.** `origin`: `manual` or `imported_mapping` plus source run.

**Does not hold.** Tile rectangles, ASR text, “speaker A” as a permanent key. Unknown speech uses no participant; assignment status is `unknown`.

## LayoutProfile

**Purpose.** Geometry of a source frame for a production look: where faces or graphic regions sit. Productions differ. Edited masters are not the same layout as a raw multicam recording.

**Identity.** `layout_profile_id`.

**Fields.** Name, reference width/height, notes.

**Relationships.** Has many `LayoutRegion`. Referenced by `LayoutSpan`.

**Provenance.** `origin`: `manual` or later `detected`, plus detector run if any.

**Does not hold.** A requirement that each participant owns exactly one region for the whole file. Does not hold shot decisions.

## LayoutRegion

**Purpose.** One rectangle in source pixels on a profile.

**Identity.** `region_id`.

**Fields.** `x`, `y`, `w`, `h` as integers in the profile’s reference frame. Optional label (not a participant id).

**Relationships.** Belongs to one profile. `LayoutBinding` attaches a participant to a region for a time span. A region may be unbound (graphic, empty, unknown).

**Does not hold.** FFmpeg filter strings, or a license to stretch this rectangle to the output frame. A region is source geometry. Whether a full shot may scale it is a render policy: only when the crop already has the output aspect ratio (true of the CFS 16:9 tiles). Other layouts need an explicit framing policy, which is not defined yet.

## LayoutSpan

**Purpose.** Layout can change over time (interview setup, then a full-screen graphic, then a different staging).

**Identity.** `layout_span_id`.

**Fields.** `start_us`, `end_us`, `layout_profile_id`.

**Relationships.** Bindings for that span: region → participant, many-to-one allowed only if the product later supports a region showing a group; V1 binding is one participant or none per region.

**Does not hold.** The assumption that the first detected tile is `speaker_a` forever.

Manual confirmation is the V1 way to create spans. Automatic detection is a later analysis run that proposes spans; it does not replace the active span until the user or an explicit promotion rule accepts it.

## ProtectedRegion

**Purpose.** A source range where multicam must not reframe. Legacy examples: intro, full-screen text, a two-person insert that must stay the master frame, outro.

**Identity.** `protected_region_id`.

**Fields.** `start_us`, `end_us`, reason code, note, `presentation` locked to program frame.

**Relationships.** Shot planner treats these as hard overrides.

**Provenance.** `origin`: `manual` or imported editability map, with source hash.

**Does not hold.** Overlap or turn edits. Protection is not a speaker.

## Transcript

**Purpose.** One transcription result for one asset.

**Identity.** `transcript_id`.

**Fields.** `asset_id`, language, engine id (`faster-whisper`), model id, decode configuration hash, `analysis_run_id`.

**Relationships.** Owns segments and words.

**Does not hold.** Cleaned prose as a replacement for words, speaker names, Reel in/out points.

## Word

**Purpose.** Authoritative timed token.

**Identity.** `word_id` (stable for the life of that transcript).

**Fields.** `transcript_id`, segment index, `start_us`, `end_us`, `raw_text`, token probability, source order.

**Relationships.** Text revisions and speaker assignments point here. They do not update these columns.

**Provenance.** The parent transcript run.

**Does not hold.** Normalized spelling, participant id, shot id. Unknown speaker is not a word field.

## TextRevision

**Purpose.** Correct display text without moving clocks.

**Identity.** `text_revision_id`.

**Fields.** Parent transcript, parent revision or null, author (`human`, `provider_task`), provider/model/prompt hash when automated, created time.

**Child rows.** `word_id`, `normalized_text` nullable, optional segment `clean_text` keyed by segment index.

**Rules.** Automated alignment may set `normalized_text` only on a 1:1 token match. Failed matches stay null. Human edits may set display text and must set `origin = human` on that row. Times are not columns on this revision.

**Does not hold.** A second set of timestamps.

## SpeakerAssignment

**Purpose.** Which participant said a word, according to one analysis run.

**Identity.** `assignment_id`.

**Fields.** `analysis_run_id`, `word_id`, `participant_id` nullable, status (`assigned`, `unknown`), method (`temporal_overlap`), overlap fraction, margin versus the runner-up. Legacy rule to preserve conceptually: require majority overlap (about 0.55 of the word) and reject near-ties (runner-up within about 0.75 of the winner). Thresholds live in run config, not in the word.

**Does not hold.** Mouth-motion tiles. Cluster-to-participant mapping is a separate mapping table on the diarization run. The historical silence-gap speaker system is not this entity.

Active assignments are whichever run the project points at.

## Turn

**Purpose.** A floor-holding stretch of one participant (or unknown), built only from assigned words.

**Identity.** `turn_id`.

**Fields.** `analysis_run_id`, `participant_id` nullable, `start_us`, `end_us`, ordered `word_id`s, text snapshot (derived, rebuildable).

**Rules to preserve.** A turn breaks when the participant changes. The same participant continues across a gap no longer than the configured gap (legacy 1.50 s). Overlap does not split turns. Silence is not required to change turns.

**Does not hold.** Camera choice, overlap flags, “meaningful turn” cuts. Minimum duration and word count for a camera change are shot-planner config.

## OverlapRegion

**Purpose.** Evidence that two or more participants are articulating together. Secondary to the floor.

**Identity.** `overlap_region_id`.

**Fields.** `analysis_run_id`, `start_us`, `end_us`, participant ids active, confidence, detector config hash (window, step, lip thresholds).

**Rules.** Does not rewrite turns or word speakers. Shot planning may switch presentation to program-wide for this span while recording the floor participant.

**Does not hold.** A new transcript.

## ConversationThread

**Purpose.** A semantic grouping of turns or word spans that discuss one topic.

**Identity.** `thread_id`.

**Fields.** Title, summary optional, ordered anchors (`turn_id`s or `word_id` ranges by id), `analysis_run_id`.

**Provenance.** Provider, model, prompt hash, input transcript revision id.

**Does not hold.** Invented in/out timestamps that are not snapped to anchors. Legacy Cursor mapping is one producer, not the schema.

## ReelCandidate

**Purpose.** A proposed contiguous source selection. It is not an output format and it is not inherently vertical.

**Identity.** `candidate_id`.

**Fields.** Anchor (`conversation_thread_id`, `first_turn_id`, `last_turn_id`), title, summary, hook, `analysis_run_id`. Source time and word ids are derived by the engine from those turns.

**Does not hold.** A required numeric score, aspect ratio, canvas size, render preset, FFmpeg commands, or burned-in subtitles. A later decision provider may rank candidates; V1 does not store a score.

## Reel draft

**Purpose.** An independent `EditorialSequence` with purpose `reel`, created from one candidate. It is the kept source content, not a 9:16 plan.

**Identity.** The sequence id. A source may have many reel drafts and at most one primary sequence.

**Does not hold.** Visual treatment, aspect ratio, or render preset. Those are chosen when rendering. See ADR 0013.

## CaptionTrack

**Purpose.** Sequence-scoped caption cues derived from the active transcript. Caption text is a fourth axis, independent of picture treatment and output canvas. See ADR 0014 and `amix/docs/CAPTIONS.md`.

**Identity.** `caption_track_id`, belonging to one `EditorialSequence`. A sequence has one current track. Regeneration keeps the previous track as history.

**Does not hold.** Render profile, aspect ratio, visual treatment, font, or burned-in styling. Manual cue text does not replace machine word text.

## ShotPlan

**Purpose.** A complete directing decision for a master, from start to end, with no gaps. The output canvas is chosen later.

**Identity.** `shot_plan_id`.

**Fields.** `asset_id`, `analysis_run_id`, planner version, input run ids (turns, overlaps, layout, protected regions), coverage assertion.

**Does not hold.** `FULL_A` labels. Render mux options (those belong to the render job).

## Shot

**Purpose.** One directing decision over a source range.

**Identity.** `shot_id`.

**Fields.**

- `start_us`, `end_us`
- `presentation`: `full` | `program_wide` | `protected_master`
- `participant_id` when `presentation = full`; otherwise null
- `floor_participant_id` optional (who held the turn even if the image is wide or protected)
- `reason`: `active_speaker` | `overlap` | `unknown_hold` | `protected` | `unbound` | `manual`
- note, source turn ids, source overlap id nullable
- `manual_override` boolean

**Planner invariant.** A `full` shot may exist only where that `participant_id` has a layout-region binding on the span. If not, the shot is `program_wide` with reason `unbound`. The planner does not stretch an unrelated region, guess a region, reuse a binding from another span, or abort. Protected regions still win over `full`, `program_wide`, and `unbound`.

**Render meaning.**

- `full`: crop the bound region and scale it only if that crop already matches the output aspect ratio. The CFS tiles are 16:9, so those regions scale to 1920×1080 directly. A rectangle that is not the output aspect is not stretched to fill the frame. A later framing policy will say how to frame it; V1 does not invent that policy.
- `program_wide`: the source frame unchanged (legacy `ORIGINAL_WIDE`, conceptually UNTOUCHED_WIDE). No crop, no blur bed, no split screen.
- `protected_master`: same pixels as program-wide, but the reason is an editability lock, not an editorial wide.

V1 shot vocabulary matches the proven offline director: one full participant, or the untouched frame, or a protected master. Designed two- and three-person composites stay out of the vocabulary until a product decision adds them. The renderer rejects unknown presentations.

**Does not hold.** Filter graphs as source of truth.

## AnalysisRun

**Purpose.** Answer: which model, which source, which transcript, which config, which algorithm, which parent run, local or cloud, hand-edited or not, and whether it is active.

**Identity.** `analysis_run_id`.

**Fields.**

- `kind`: `probe` | `transcribe` | `normalize_text` | `diarize` | `align` | `turns` | `overlap` | `layout_proposal` | `conversation_map` | `reel_candidates` | `reel_plan` | `shot_plan` | `summary`
- `status`: `running` | `succeeded` | `failed` | `cancelled` | `interrupted`
- `source_asset_id`
- input artifact ids (transcript, revision, prior run)
- `algorithm_id`, `algorithm_version`
- `config_hash`, config snapshot JSON (small). When thresholds or features depend on the analyzed span, the snapshot includes that window (start, end, and any exclusion mask). A run on 2960–3560 s is not the same run as one on the whole asset.
- `execution`: `local` | `cloud`
- provider id, model id, model version, prompt hash (null when the stage is deterministic code)
- `manual_modification`: boolean on the run or on a child revision
- started/finished time
- output content hash
- cache key

**Active flag** is not a column that many runs can set. `Project` holds the active id per kind. Promoting a run is an explicit write. Hand edits create a successor run or a manual revision that points at the parent, with `manual_modification = true`.

**Does not hold.** The video, the full word list inline if that list is large (words are rows or a hashed artifact file), API keys, the string `latest`.

## ProcessingJob

**Purpose.** Execution of pipeline work: progress, cancel, resume.

**Identity.** `job_id`.

**Fields.** `kind` (stage or a fan-out), `status`, progress 0–1, message, `analysis_run_id` nullable until the run exists, cache hit boolean, error text, cancel requested boolean, worker token, created/updated time.

**Does not hold.** Domain results duplicated “for the UI”. The UI reads the run and the job.

## RenderJob

**Purpose.** A processing job that produces an export asset.

**Identity.** `render_job_id` (may share the job table with `kind = render` if that stays simpler in implementation; the domain still distinguishes it).

**Fields.** Plan id (`shot_plan` or `reel_plan`), output `asset_id`, encoder settings snapshot, FFmpeg version, log path, whether audio was stream-copied.

**Does not hold.** A second shot list.

## ModelDefinition

**Purpose.** A model the app can run or call. Stored in the **global** database.

**Identity.** `model_id`.

**Fields.** See [MODEL_DISTRIBUTION.md](MODEL_DISTRIBUTION.md): display name, provider, runtime, license, version, size, hash, download source, local path, capabilities, hardware requirements, redistributable, bundled, download-on-demand.

**Does not hold.** Per-project editorial state. A project run stores `model_id` plus the version it actually used.

## ProviderConfiguration

**Purpose.** How a provider is reached. Global, not inside the project file the user copies to another machine by accident with secrets.

**Identity.** `provider_config_id`.

**Fields.** Provider kind, display name, endpoint (if any), default model id, enabled flag, **credential reference** (OS store key), capability flags the user expects.

**Does not hold.** The secret string. See [STORAGE_ARCHITECTURE.md](STORAGE_ARCHITECTURE.md).

## Entities considered and not split further

| Idea | Decision |
|---|---|
| Separate `Segment` aggregate | Segment index on `Word` is enough. Segment clean text hangs off `TextRevision`. |
| `Camera` entity | Presentation plus participant plus layout region. A camera table would freeze A/B/C. |
| `EditDecisionList` superclass of shots and reels | Shared time and word types only. The two plans stay separate. |
| `Speaker` distinct from `Participant` | One identity. Diarization clusters are run-local labels. |
| Filename-versioned artifact rows | Rejected. Runs and active pointers only. |

## Legacy import names

An importer may read `speaker_a` and `FULL_A` and write `participant_id` plus `presentation = full`. The mapping table is an import document for that asset (“this file’s tile A is participant P”). It is not a product enum.
