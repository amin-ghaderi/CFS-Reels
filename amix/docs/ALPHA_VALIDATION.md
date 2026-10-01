# Internal Alpha validation

Date: 2026-09-30. Platform: Windows, 64-bit, about 16 GB RAM, no discrete GPU reported to the desktop session.

This is a hands-on WebView session of the development app (`npm run tauri dev`). Automated tests are recorded separately and are not treated as substitutes for the rows below.

## Environment

- AMIX desktop 0.4.0, schema `0010_caption_track`, local engine on loopback.
- FFmpeg 8.1.1, discovered by the engine.
- Speech: a local faster-whisper-small CTranslate2 snapshot already on the machine. Device `cpu`, compute `int8`. Nothing was downloaded.
- Vision: a local YuNet ONNX file already on the machine. OpenCV 4.14.0. Nothing was downloaded.
- Semantic provider: not configured. No remote API was called.
- The native folder dialog was not driven by this session. Create and open used the same engine commands the buttons call after a path is chosen. In-app controls were clicked in the WebView.

## Source media

Not committed.

- Alpha project: a scratch folder outside the repository, project name Alpha.
- Linked master: a 45-second stream copy of the known CFS03 program, taken at container offset 2960 s. H.264 1920×1080, AAC 48 kHz stereo, about 36 MB. Container start on the excerpt is 0, so this file is not the 2960–3560 s golden window.
- YuNet comparison: the known CFS03 master in the legacy inbox (about 8.6 GB, not opened by the default test suite). Window start 2960 s, duration 600 s. Layout tiles match `tests/golden/cfs03_49_59/inputs/layout.json` (cfs03-a, cfs03-b, cfs03-c).

## Manual flow

1. Start the desktop and confirm the engine is READY.
2. Create Alpha, link the excerpt, analyze it, and generate a V1 proxy. Play, pause, and seek in the WebView. Sibling proxy URLs return 403.
3. Reload the WebView with the project open. Close the project. Quit the desktop. Start it again and open Alpha. A second open in the same engine returns `project_already_open`.
4. Hide the source file. The media row shows Missing, and the transcript stays readable on the proxy. Relink the same bytes under a new file name. The asset id is unchanged and no second master is created. Probe metadata is cleared until Analyze media runs again.
5. Transcribe with the local small model (Persian). Correct a word, revert it, then keep one correction. Map three anonymous clusters to Nima R., Arman, and Unknown.
6. Run overlap on the excerpt from Multicam (no regions; the excerpt ends before the first golden region). Build a plan. Override Wide, then Use Automatic, then Full for one participant.
7. Split the primary sequence, remove the later clip (edit length 20.213 s), after an earlier reset had restored the full 45 s. Generate captions, edit one cue, restore generated text, export SRT and VTT.
8. Render Multicam Landscape 720 and Multicam Portrait 720. Inspect frames: landscape cuts between people and stays 16:9; portrait Wide is padded, portrait Full is center-filled.
9. Run the production overlap worker plus `overlap_regions` on CFS03 2960–3560 s. Compare with the six-region golden file.
10. Cancel a live transcription. Confirm a stale caption track, then revert the word so the track is ready again.
11. Close while a player is mounted, reopen, and play again.

## Checklist

| Item | Result |
| --- | --- |
| Project | PASS |
| Media | PASS |
| Playback | PASS |
| Transcript | PASS |
| Participants | PASS |
| Layout | PASS |
| Diarization | PASS |
| Conversation | BLOCKED BY RESOURCE — SEMANTIC PROVIDER |
| Overlap | PASS |
| Multicam | PASS |
| Timeline | PASS |
| Reels | BLOCKED BY RESOURCE — SEMANTIC PROVIDER |
| Captions | PASS |
| Rendering | PASS |
| Persistence | PASS |
| Cancellation/errors | PASS |

Overlap PASS is the production extractor on CFS03 2960–3560 s: EXACT MATCH with the six golden regions (times, participant ids, and confidences 0.93 / 0.93 / 0.93 / 0.93 / 0.93 / 0.876). The desktop overlap job on the 45 s excerpt is a different span and returned no regions.

Rendering PASS is primary Multicam Landscape 720 (1280×720, 20.233 s) and primary Multicam Portrait 720 (720×1280, 20.233 s). Source/Program and Multicam reel renders were not run.

Captions PASS is the primary sequence. Reel captions were not reached.

Cancellation/errors PASS covers a cancelled transcription, a missing source, a stale caption track, and the unconfigured semantic provider. These were not triggered in the UI because the resources were configured for the real runs: missing speech model, missing YuNet. Stale ShotPlan was not triggered. A protected shot was not present. Switching media was not possible (one master). Perceptual lip-sync on a long program was NOT TESTED; the exported span is 20.233 s.

## Known issues

- Frame rate is shown as the raw fraction `1366000/45533`.
- Speaker clusters keep the diarizer ids (`Cluster SPEAKER_00`) until they are mapped.
- The Export workspace points at Multicam and Reels. It does not start a render.
- The activity list is tall and pushes the workspace down until it is hidden.
- Relink keeps the same asset and clears probe metadata until the file is analyzed again.
- Analyze overlap in the desktop always uses the full asset. A 2960–3560 s window has to be requested on the job spec.
- The kept primary edit is 20.213 s, with one Wide override on the first shot. There is no reel draft and no conversation map.
- The native open/create folder dialog was not exercised by this session.
