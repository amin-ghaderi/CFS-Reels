# CFS03 49–59 golden fixture

Migration proof for the automatic diarized multicam window. No video is stored here.

| | |
|---|---|
| Source video | `legacy/data/inbox/03.mp4` (8,681,934,519 bytes; not in Git) |
| Window | container time 2960 s for 600 s (00:49:20–00:59:20). Times are not rebased to 0. |
| Generated | 2026-09-28 |

## What is an input

`inputs/` is evidence. Stages recompute from it.

| File | Evidence |
|---|---|
| `words.json` | Whisper words and legacy timings. No speaker labels. |
| `diarization_segments.json` | Anonymous clusters before word assignment. |
| `cluster_map.json` | Pinned CFS03 cluster→participant map. Hand-anchored in legacy. Not discovered here. |
| `layout.json` | Tile rectangles bound to `cfs03-a/b/c` for the whole window. |
| `config.json` | Window, thresholds, and provenance. |
| `lip_activity.json` | Per-frame lip scores and audio RMS **before** overlap regions. Produced once by `extract_lip_activity_once.py` (legacy decoder + local video). Tests do not run that script. |

## What is an assertion

`expected/` is not fed back into the stage it checks.

| File | Asserts |
|---|---|
| `assignments.json` | `assign_words` against `CFS03_49-59_words_with_speakers.json` |
| `turns.json` | `build_turns` against `CFS03_49-59_turns_v3.json` |
| `overlaps.json` | `overlap_regions` against `CFS03_49-59_overlaps_v3.json` |
| `shots.json` | Automatic planner against legacy `build_floors` + overlap overlay |

## Reactions

The published legacy file `CFS03_49-59_diarized_overlap_v1_plan.json` inserts hand-authored reaction shots. Those are not part of the automatic planner. `expected/shots.json` is the floor/overlap plan **without** `insert_reactions`. A match against the published file would be wrong.

## Rebuild

Only when regenerating fixtures. Requires the legacy tree and, for lip activity, the local video, FFmpeg, and the existing virtualenv. The test suite does not.

```
.\.venv\Scripts\python.exe amix/tests/golden/cfs03_49_59/build_fixture_once.py
.\.venv\Scripts\python.exe amix/tests/golden/cfs03_49_59/extract_lip_activity_once.py
```
