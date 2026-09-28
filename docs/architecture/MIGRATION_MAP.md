# Migration map

AMIX does not copy `legacy/` wholesale. Status labels match [LEGACY_INVENTORY.md](../migration/LEGACY_INVENTORY.md) plus how the current Reel pipeline actually calls code.

`conversation.py` still attributes speakers with `speakers.py` (silence gaps and mouth motion). The successful 16:9 programs use `cfs_audio_diarize_poc.py`, `cfs_overlap.py`, and the offline shot planners. Those are different generations. The diarized path is the one to preserve conceptually.

| Capability | Source | Status | Target | Migration |
|---|---|---|---|---|
| Transcription, word timestamps, long-form chunk cache | `legacy/reels_factory/transcribe.py`, `legacy/scripts/transcribe_cfs03.py` | PROVEN / CURRENT | Transcribe stage | PRESERVE BEHAVIOR |
| Transcript normalization | `ai_normalizer.py`, prompts | CURRENT | `transcript_normalization` task | ADAPT (provider capability, not Cursor-only) |
| Word-time preservation while cleaning text | `word_align.py` | CURRENT | `TextRevision` + deterministic aligner | PRESERVE BEHAVIOR |
| Historical speaker blocks | `speakers.py` | LEGACY | — | DO NOT MIGRATE |
| Speaker resolver v2 (mouth motion, mixed-audio correlation, continuity) | `speaker_resolver_v2.py` | LEGACY | — | DO NOT MIGRATE as the product speaker system. Pieces of mouth measurement may inform overlap; they are not a second attribution stack. |
| Audio diarization | `cfs_audio_diarize_poc.py` | Clustering PROVEN on CFS03 windows with fixed k=3. Mapping HAND-ANCHORED (solo frames at CFS03 times, mouth votes). Not a generic N-speaker diarizer. | Diarize stage | ADAPT the anonymous-cluster then map shape. Domain stays N-participant. The migrated proof does not discover k. Phase 2 pins the known map as fixture input. Do not describe this POC as production diarization. |
| Word-to-speaker alignment | `assign_word` | PROVEN | Align stage | PRESERVE BEHAVIOR |
| Turns | `build_turns` | PROVEN | Turn builder | PRESERVE BEHAVIOR |
| Overlap | `cfs_overlap.py` | PROVEN / EXPERIMENTAL | Overlap stage | ADAPT (thresholds and YuNet lip logic; regions must not rewrite turns). Tile constants `speaker_a/b/c` become layout regions. |
| Conversation mapping | `conversation_map.py`, `prompts/conversation_mapper.md` | CURRENT | `conversation_mapping` | ADAPT. Its legacy input is silence-gap `speakers.json`. AMIX must feed diarized turn ids, not that file. |
| Program mapping | `program_map.py` | CURRENT | Same thread model if still useful | ADAPT or fold into conversation mapping. Do not keep two LLM mappers with two schemas without a single `ConversationThread` output. |
| Heuristic Reel candidates | `candidates.py` | CURRENT | Local candidate stage | ADAPT (anchors become word/turn ids) |
| Conversation Reel mining | `conversation_reels.py` | CURRENT | Reel candidate stage | ADAPT |
| Semantic Reel edit | `semantic_editor.py`, `plan_validate.py` | CURRENT | `final_reel_edit` | ADAPT (validate ids, not free timestamps) |
| QA Reel editor | `qa_reel_editor.py` | CURRENT | Validator inside Reel plan | ADAPT rules that are deterministic. Drop filename-driven QA. |
| Keyword / inbox preprocess only | `pipeline.py` `preprocess_video` | CURRENT | Not a product spine | DO NOT MIGRATE as the architecture. Transcription and candidate mining survive as stages. |
| 9:16 render, composition, stack order | `render.py`, `composition.py`, `stack_order.py`, `portrait.py`, `subtitles.py` | PROVEN / CURRENT | `RENDER_9x16` | ADAPT. Keep frozen-crop behavior. Do not merge into the 16:9 renderer. |
| 16:9 offline directing | `cfs_offline_multicam_16x9.py`, `data/tmp_cfs03_preview/`, `data/tmp_edited_multicam/` | PROVEN / HAND-AUTHORED / EXPERIMENTAL | Shot planner + `RENDER_16x9` | ADAPT. Preserve vocabulary: one full participant or untouched frame; protected spans; overlap → wide; floor unchanged. Replace `FULL_A` with `full` + participant. Hand-authored scripts are references, not modules to ship. |
| Earlier 16:9 live-style helper | `cfs_multicam_16x9.py` tile table | PROVEN as geometry used by the offline renderer | Layout regions | WRAP geometry only. The live-style path is not the product planner. |
| Framing profiles | `framing.py`, `data/framing_profiles/` | PROVEN / CURRENT | `LayoutProfile` import | ADAPT. Profiles become data. `speaker_a` keys exist only in the importer. |
| Face tools | `faces.py` YuNet | CURRENT | Overlap and future layout proposals | WRAP |
| Visual verifier | `cfs_offline_verify.py` | EXPERIMENTAL | Optional later shot QA | REIMPLEMENT LATER as a plan override. Not a V1 shot-plan authority. The diarization POC does call its mouth measurement to map clusters; that mapping is pinned evidence for the golden fixture, not a reason to ship the verifier. |
| FFmpeg helpers | `utils.py` and call sites | PROVEN / CURRENT | Engine media tools | WRAP (probe, extract, cut, concat, mux). |
| Cursor client | `cursor_ai.py` | CURRENT | Optional dev adapter | WRAP behind `GENERATE_STRUCTURED`. Not the product default. |
| Roles and editorial prose | `legacy/roles/` | HAND-AUTHORED | Prompt templates if a task still needs that guidance | ADAPT as versioned prompt text, or leave in legacy until the task is implemented. |
| Episode summaries and trailers | `scripts/render_cfs03_episode_summary*.py` | EXPERIMENTAL / HAND-AUTHORED | `summary_generation` later | REIMPLEMENT LATER. Do not port the one-off scripts. |
| Visual hooks | `visual_hooks/`, fire/SFX POCs | EXPERIMENTAL | — | DO NOT MIGRATE |
| Covers, Instagram, publication packaging | `cover.py`, `instagram.py`, `publication.py`, `package_final.py` | CURRENT side paths | — | DO NOT MIGRATE in the architecture phase. Export is a file write. |
| Refine / second-pass ASR windows | `refine.py` | CURRENT | Possible later transcribe mode | REIMPLEMENT LATER |
| Work packets (markdown for a human or Cursor) | candidate work packet writer | CURRENT | — | DO NOT MIGRATE. The UI replaces the packet. |

## Obsolete or superseded

- **Silence-gap speaker attribution** (`speakers.py`) and **resolver v2** as the authority for who is speaking. Superseded for the multicam work by audio diarization plus word overlap.
- **Filename versions** (`turns_v3`, `resolved_v3_final`, `latest`) as the way to know which timeline is active.
- **A/B/C shot enums** as the directing model.
- **Designed two- and three-person composites** already rejected by `cfs_offline_multicam_16x9.py`. Stay rejected.
- **Cursor as a required runtime.**
- **Root-relative `data/` paths and `run_pipeline.py`** as the application shell.
- **Visual hooks and episode-summary scripts** as product features.

## Preserve conceptually from the latest 16:9 path

- Words stay the clock.
- Diarization proposes anonymous speakers; a map attaches participants.
- Alignment can return unknown.
- Turns follow speaker changes and a same-speaker gap; they ignore overlap.
- Overlap is a second layer and forces a wide shot in the planner used for the accepted tests.
- Protected master ranges outrank the director.
- Long wordless stretches fall back to the original frame.
- Render crops one tile or passes the frame through. Direct scale to 1920×1080 is valid because those CFS tiles are already 16:9. Do not treat stretch-to-frame as the general rule. Audio may be stream-copied.
- Plans are computed before render.

## Do not preserve

- POC module layout, tmp scripts under `data/tmp_*`, or CFS03-only constants as AMIX structure.
- Three participants as a schema limit. Fixed k=3 is a property of the current proof, not of the domain.
- Float seconds as stored authority.
- LLM-owned timestamps.
