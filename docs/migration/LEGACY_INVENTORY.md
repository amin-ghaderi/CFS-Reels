# Legacy capability inventory

This inventory records the preserved CFS/Reels implementation after repository relocation. Status labels describe the existing implementation; they are not migration recommendations.

| Capability | Current location | Role | Status |
|---|---|---|---|
| Transcription | `legacy/reels_factory/transcribe.py`; `legacy/scripts/transcribe_cfs03.py` | Local faster-whisper transcription, word timestamps, long-form chunk/cache handling | PROVEN / CURRENT |
| Transcript normalization | `legacy/reels_factory/ai_normalizer.py`; `legacy/reels_factory/word_align.py` | Cursor-assisted text cleanup while preserving source timestamps | CURRENT |
| Historical speaker attribution | `legacy/reels_factory/speakers.py` | Silence-gap speech blocks with visual mouth-motion attribution | LEGACY |
| Speaker resolver v2 | `legacy/reels_factory/speaker_resolver_v2.py` | Resolves historical blocks with mouth motion, mixed-audio correlation, and continuity | LEGACY |
| Audio diarization | `legacy/reels_factory/cfs_audio_diarize_poc.py` | MFCC and spectral-centroid windows clustered into three anonymous speakers | PROVEN / EXPERIMENTAL |
| Word-to-speaker alignment | `legacy/reels_factory/cfs_audio_diarize_poc.py` (`assign_word`) | Assigns unchanged Whisper words by temporal overlap with diarized segments | PROVEN |
| Speaking turns | `legacy/reels_factory/cfs_audio_diarize_poc.py` (`build_turns`) | Splits turns on speaker changes without requiring silence | PROVEN |
| Conversational overlap | `legacy/reels_factory/cfs_overlap.py` | Detects sustained simultaneous lip activity with mixed-audio activity gating | PROVEN / EXPERIMENTAL |
| Conversation mapping | `legacy/reels_factory/conversation_map.py`; `legacy/prompts/conversation_mapper.md` | Cursor/LLM mapping of attributed conversation blocks into discussion threads | CURRENT |
| Reel selection and editing | `legacy/reels_factory/conversation_reels.py`; `legacy/reels_factory/semantic_editor.py`; `legacy/reels_factory/qa_reel_editor.py` | LLM-assisted and deterministic candidate selection, boundary repair, and plan generation | CURRENT |
| 9:16 Reel rendering | `legacy/reels_factory/render.py`; `legacy/reels_factory/composition.py`; `legacy/reels_factory/stack_order.py` | Renders static/frozen vertical layouts and planned Reel clips | PROVEN / CURRENT |
| 16:9 Multicam planning | `legacy/data/tmp_cfs03_preview/`; `legacy/data/tmp_edited_multicam/` | Test-specific offline shot-plan construction from turns, overlap, and protected-layout intervals | PROVEN / HAND-AUTHORED / EXPERIMENTAL |
| 16:9 rendering | `legacy/reels_factory/cfs_offline_multicam_16x9.py`; `legacy/reels_factory/cfs_multicam_16x9.py` | Renders FULL_A/B/C and ORIGINAL_WIDE with FFmpeg | PROVEN |
| Visual verification | `legacy/reels_factory/cfs_offline_verify.py` | YuNet landmark and mouth-motion QA around proposed camera boundaries | EXPERIMENTAL |
| FFmpeg integration | `legacy/reels_factory/utils.py`; `legacy/reels_factory/transcribe.py`; `legacy/reels_factory/render.py`; multicam render modules | Media probing, extraction, cropping, scaling, encoding, concatenation, and muxing | PROVEN / CURRENT |
| Cursor/LLM integration | `legacy/reels_factory/cursor_ai.py`; `legacy/prompts/` | Invokes configured Cursor models for normalization and editorial analysis | CURRENT |
| Framing and layout | `legacy/data/framing_profiles/`; `legacy/reels_factory/framing.py`; `legacy/reels_factory/faces.py`; `legacy/reels_factory/composition.py` | Frozen CFS tile coordinates, face detection, and layout construction | PROVEN / CURRENT |
| Roles and editorial guidance | `legacy/roles/` | Human-authored editorial and workflow guidance | HAND-AUTHORED |
| Episode summaries and trailers | `legacy/scripts/render_cfs03_episode_summary*.py`; `legacy/data/episode_summaries/` | One-off summary/trailer plans and renderers | EXPERIMENTAL / HAND-AUTHORED |
| Visual hooks | `legacy/reels_factory/visual_hooks/`; `legacy/scripts/render_cfs03_visual_hook*.py` | Local segmentation, procedural effects, compositing, and synthesized SFX experiments | EXPERIMENTAL |

## Important preserved artifacts

- Source media, generated media, transcripts, speaker timelines, plans, QA, and temporary research material remain under `legacy/data/`.
- Frozen CFS framing profiles remain under `legacy/data/framing_profiles/`.
- The old root documentation is preserved at `legacy/README.md`.
- The old entry point remains `legacy/run_pipeline.py`.
