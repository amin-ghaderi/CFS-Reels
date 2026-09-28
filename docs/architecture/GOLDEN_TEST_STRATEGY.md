# Golden test strategy

The first AMIX regression is the successful CFS **10-minute** multicam sample: the diarized overlap cut of CFS03 in the 49–59 minute window (legacy artifacts and the offline 16:9 plan/render path). It is a migration proof, not a demo reel.

The full Edited.mp4 program is a later fixture. It is long, and its protected regions are hand-authored. It is not the first golden.

## What must not drift

AMIX code recomputes, from pinned inputs:

- speaker assignment
- turn boundaries
- overlap regions
- shot-plan decisions

Word timing is an **input** (the accepted Whisper words), not an output of this fixture. Rendering bitstreams are not golden. Encoder drift is expected.

The expected output of a stage is never that stage’s input.

## Pinned analysis window

The window is an input, not a comment. Legacy diarization and overlap thresholds are percentiles of the analyzed span, so this window is not interchangeable with “the whole episode”.

| Field | Value |
|---|---|
| Source | CFS03 master (`03.mp4` in the legacy tree) |
| Container start | 2960 seconds |
| Duration | 600 seconds |
| Container end | 3560 seconds |

Times in the fixture are imported with the legacy rule in [TIMELINE_MODEL.md](TIMELINE_MODEL.md): whole milliseconds, then integer microseconds. The window itself is `2960 * 1_000_000` µs for `600 * 1_000_000` µs on the container presentation timeline. It is not rebased to zero.

Record the window on the fixture config and on the cache identity of any stage that reads it.

## No video in Git

Do not commit `03.mp4`, Edited.mp4, WAVs, or rendered MP4s.

Commit small JSON under `amix/tests/golden/cfs03_49_59/` when tests exist. This document does not add those files.

If a local media hash does not match the manifest, the tolerance layer skips. The exact layer does not need the video.

## Two layers

### Exact (decision)

Inputs, committed once from the accepted legacy evidence:

- Whisper words for the window: id, `start_us`, `end_us`, `raw_text` (timing is not recomputed)
- Diarization segments for the window (anonymous clusters, times). Not turns, and not word speaker labels
- The pinned cluster→participant map used by that proof, including the fact that it was hand-anchored for CFS03. The test does not rediscover this map
- Lip-activity series for the window (scores per region over time, plus the audio energy the detector gated on). Not the finished overlap regions. This is small next to the video: 600 s at the detector’s sample rate
- Layout rectangles and the participant binding for this file
- Protected regions: none in this window
- Algorithm config the legacy behavior used (alignment fractions, turn gap, overlap thresholds, planner minima) and the analysis window above

AMIX then computes, and the test asserts:

| Stage | Computed output |
|---|---|
| Align | Word speaker assignment, or `unknown` |
| Turns | Turn id, participant, `start_us`, `end_us`, word ids |
| Overlap regions | Regions from the lip-activity series and the pinned config. No video decode |
| Shot plan | Contiguous half-open coverage of the window: presentation, participant id, reason, floor participant |

Assertions are value comparisons after canonical sorting. Failures should name the first differing word, turn, region, or shot (ids and times), not dump the whole fixture.

Participant ids in the fixture are the imported mapping of legacy `speaker_a/b/c` for this file. The test fails if the planner emits `FULL_A`. A full shot whose participant has no region binding in the layout is a failure of the planner invariant; this fixture’s three tiles are bound, so the expected plans still use those bindings.

This layer runs in CI without media and without a GPU.

### Tolerance (perception)

Runs clustering and lip measurement against a local media file whose hash matches the manifest. This is the signal path the exact layer deliberately does not replay.

| Output | Assertion |
|---|---|
| Word times from a fresh Whisper run | Not in the default CI golden. The exact layer uses the accepted word JSON. |
| Diarization segments | Boundary tolerance of one clustering hop, or skip until the ported algorithm is bit-stable. The migrated clusterer is the fixed three-cluster CFS proof, not a generic N-speaker system. |
| Lip-activity series | Not byte-compared. Optional later. |
| Overlap regions from a fresh decode | Start/end within one detector step (legacy step 0.25 s) and the same participant set, only when media is present. The exact layer already checks region logic from frozen activity. |
| FFmpeg video | Not byte-compared. Optional: duration within 1 frame, audio stream copy flag, shot count. |

A perception failure does not rewrite the decision fixture. Someone updates expected JSON only after a reviewed algorithm change, and that change bumps `algorithm_version`.

## Import bridge

Legacy files store float seconds and `speaker_a`. The golden import:

1. Converts times with the legacy rule in [TIMELINE_MODEL.md](TIMELINE_MODEL.md) (millisecond, then `× 1000`).
2. Maps speakers through a fixture table to `ParticipantId`.
3. Maps `FULL_*` / `ORIGINAL_WIDE` / `PROTECTED_MASTER` into `presentation` + `participant_id` **only in the expected shot file**. Those labels are not inputs to the planner.

The expected shot JSON is the AMIX shape. The test is not a string compare against legacy plan filenames.

## Layout

Suggested tree when implemented (not created in this task):

```
amix/tests/golden/cfs03_49_59/
  manifest.json          # source hash, window 2960s / 600s, where media may live locally
  config.json            # algorithm config + analysis window
  participants.json
  layout.json
  inputs/words.json
  inputs/diarization_segments.json
  inputs/cluster_map.json
  inputs/lip_activity.json
  expected/assignments.json
  expected/turns.json
  expected/overlaps.json
  expected/shots.json
```

`manifest.json` records where a developer may place the media locally. The path is not a repo path.

## Pass rule for migration

Phase 2 is not allowed to call the multicam port “behavior preserved” until the exact layer passes: assignments, turns, overlap regions, and shots are produced by AMIX from the inputs above.

The tolerance layer is required before replacing the legacy overlap **decoder** or the clusterer. It is optional while those stages still consume the frozen inputs.
