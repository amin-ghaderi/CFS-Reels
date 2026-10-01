# Internal Alpha validation

Date: 2026-09-30. Platform: Windows, 64-bit, about 16 GB RAM, no discrete GPU reported to the desktop session.

This is a hands-on WebView session of the development app (`npm run tauri dev`). Automated tests are recorded separately and are not treated as substitutes for the rows below.

## Environment

- AMIX desktop 0.4.0, schema `0010_caption_track`, local engine on loopback.
- FFmpeg 8.1.1, discovered by the engine.
- Speech: a local faster-whisper-small CTranslate2 snapshot already on the machine. Device `cpu`, compute `int8`. Nothing was downloaded.
- Vision: a local YuNet ONNX file already on the machine. OpenCV 4.14.0. Nothing was downloaded.
- Semantic provider: not configured in this 2026-09-30 session. No remote API was called.
- Phase 19 adds Settings so speech, vision, a semantic provider, and FFmpeg can be configured without those environment variables. The 2026-09-30 rows below still describe the session that used development paths for speech, vision, and FFmpeg.

On 2026-10-01 the desktop was started again with those speech, vision, and FFmpeg environment variables unset. Settings was opened with no project. A local speech folder, the existing YuNet file, and an FFmpeg folder were registered from the same engine commands the Settings actions call after the native picker returns a path. The native picker itself was not driven. Speech, vision, FFmpeg, and FFprobe then showed ready, including after quitting and starting the desktop again. No semantic provider was available, and no remote API was called. Conversation still reports that no semantic provider is configured. Map Conversation, reel discovery, and reel renders were not run.
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

## Semantic / Reels dogfood

Recorded in the live desktop after the managed local runtime was implemented. Imports used the settings import routes because the native file dialog cannot be completed by this session. No `AMIX_AI_*` variables were set. The server was not left running after the window closed.

| Item | Result |
| --- | --- |
| Runtime | llama.cpp, reported version `version: 1 (ac4cdde)`. Loopback `127.0.0.1`, application-chosen port, context 16384. |
| Model identity | gemma-3-4b-it. GGUF version 3, architecture gemma3, about 2.5 GB, semantic compatibility unknown, license unknown. |
| Local-only | PASS. Offline policy stayed in place. No API key. No remote fallback. |
| Settings | PASS. Runtime and model registered in place, selected, started to Local AI ready, still present after quit and relaunch, then started again. The screen showed Local AI stopped, then Loading model. |
| Conversation map | FAIL. Map Conversation showed Loading model, then Mapping conversation. The job ended `semantic_timeout`. |
| Reel discovery | Not reached. |
| Reel draft | Not reached. |
| Captions | Not reached. |
| Source/Program landscape | Not reached. |
| Source/Program portrait | Not reached. |
| Multicam landscape | Not reached. |
| Multicam portrait | Not reached. |
| Quality observations | A tiny structured request returned JSON wrapped in Markdown fences. Existing validation rejects that. The 45-second excerpt is one chunk of about 7200 tokens. That request did not return within 300 seconds on this CPU. |
| Overall | BLOCKED BY MODEL CAPABILITY |

The model loads and the provider path is the existing structured-generation adapter. It did not produce a validated conversation map, so reel discovery, drafts, captions, and renders were not run. Validation was not relaxed.

## Semantic efficiency retest

Recorded in the live desktop with the same llama.cpp `version: 1 (ac4cdde)`, the same gemma-3-4b-it GGUF, and the same 45-second Alpha project. No `AMIX_AI_*` variables were set. Imports and project open used the engine routes because the native file dialog cannot be completed by this session. Buttons that do not open a dialog were clicked.

The previous request was one chunk. The server reported 7182 tokens against a 4096 context. Measured character attribution of that payload, without copying transcript text: system prompt 447, payload 9245, effective text 470, turn ids 95, participant names 62, participant ids 360, word ids 3780, JSON syntax 4335. The word-id UUID arrays and the JSON around them were the inflation. Turn ids were already 5 characters.

After the payload change the same chunk is 19 turns and 105 words. Effective text is still 470 characters. Word ids and participant ids in the model payload are 0. Payload is 3749 characters, the compact schema is 332, and the deterministic estimate is 1133 tokens. That is under the 4096 request limit and the 3072 data budget. The desktop job log did not surface the server's own usage counters.

| Item | Result |
| --- | --- |
| Conversation map | PASS. One request, no repair, 10 threads, 76 seconds including model load. Threads cover T0001 through T0019 in order. Clicking a thread seeked the source preview to 3.420 seconds. The map was still present after close and reopen. |
| Reel discovery | PASS. 11 requests, no repair, 1 candidate, about 137 seconds. |
| Reel draft | PASS. "Question and Answer", source 3.420–4.720 seconds, revision 1, one clip. Split and remove were not used: the only clip is 1.3 seconds and the playhead was on its start. |
| Captions | PASS. One cue, sequence 0–1.300 seconds, source 3.420–4.720 seconds. SRT and VTT use that same interval. |
| Source/Program landscape | PASS. 1280×720, 1.300 seconds, revision 1. |
| Source/Program portrait | PASS. 720×1280, 1.300 seconds, revision 1. |
| Multicam landscape | PASS. 1280×720, revision 1. Byte-identical to source/program because the covering shot is untouched wide. |
| Multicam portrait | PASS. 720×1280, revision 1. Byte-identical to source/program portrait for the same reason. |
| Inspection | The landscape frame is the three-up program. The portrait frame keeps that layout with square pixels and does not stretch the faces. Audio is continuous speech, about −20 dB mean, and is the same on all four files. |
| Overall | COMPLETE |

Some thread titles name a participant who is not in that thread's participant list. The anchors, order, and coverage still validated. The discovered reel is one short exchange, not a longer selection. Validation was not relaxed.

## Known issues

- Frame rate is shown as the raw fraction `1366000/45533`.
- Speaker clusters keep the diarizer ids (`Cluster SPEAKER_00`) until they are mapped.
- The Export workspace points at Multicam and Reels. It does not start a render.
- The activity list is tall and pushes the workspace down until it is hidden.
- Relink keeps the same asset and clears probe metadata until the file is analyzed again.
- Analyze overlap in the desktop always uses the full asset. A 2960–3560 s window has to be requested on the job spec.
- The kept primary edit is 20.213 s, with one Wide override on the first shot. The Phase 20.1 retest added a conversation map and one reel draft on the 45-second excerpt.
- The native open/create folder dialog was not exercised by this session.
