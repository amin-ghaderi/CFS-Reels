# Media and transcript workspace

Phase 6 is the first editing workspace. It lists and links media, and it shows an active transcript when one already exists. It does not transcribe. Preview playback of the V1 proxy is described in [PLAYBACK.md](PLAYBACK.md). Probing and preview proxies are described in [MEDIA_RUNTIME.md](MEDIA_RUNTIME.md).

## Workspace architecture

`App.tsx` only mounts the engine gate. Session hydration stays in `src/app/EngineGate.tsx` and still follows the Rust desktop session. It does not keep a second copy of the engine generation.

While a project is open:

- `ProjectShell` owns the top bar and which workspace is visible.
- `ProjectData` owns the media list and the selected asset for this project. Selection is memory only. A new project, or an asset that disappears, clears it.
- Media and Transcript choose their own panels. Conversation, Multicam, Reels, and Export stay empty placeholders.
- Background jobs live in the bottom Activity panel. The right inspector is for the selected media asset or the selected word.

Panel widths can be dragged during the visit. They are not saved.

## Window

The preferred window is 1200×720. The minimum is 800×520 so a scaled laptop can still reach the status bar. On startup the shell clamps that preferred size to the current monitor's work area.

## Media

Linking records an external `MediaAsset`. The file is not copied into the project. The role defaults to `master`. The other stored roles are `proxy`, `audio_extract`, `export`, and `sidecar`.

The engine stores the display filename, the external path, the file size, and a modification time from a stat of that one path. Duration, frame rate, and picture size stay empty until Analyze media runs. The desktop does not invent them. After a probe, the inspector shows the stored duration, display size, codecs, rational frame rate, and container start time.

Generate proxy is available for a present master. The proxy is a derivative of that asset, not another row in the source list. Its state is Not generated, Queued, Generating, Ready, Stale, Failed, or Missing. The preview pane plays a ready V1 proxy through the desktop asset protocol. It does not play the linked source file. See [PLAYBACK.md](PLAYBACK.md).

Availability is `present` or `missing`, from whether that path is a file. The Media list shows Missing without an integrity job.

Relink updates the path, display name, and size on the same asset id. Analysis runs, transcripts, and active pointers stay attached to that id.

The desktop sends only a path the user picked in the native file dialog. There is no API that lists a directory.

## Transcript authority

The active transcript is the run stored on `(media asset, kind=transcript)` in `active_analysis`. The newest transcript file or run is not used. If that pointer is absent, the API returns `active: false` and the workspace says that no transcript is available. It does not offer a Transcribe action.

Words are read in sequence order, `offset` + `limit`, with a maximum limit of 400. The workspace asks for 80 at a time and moves with Previous and Next. Times in the API are integer microseconds. The desktop formats them as `HH:MM:SS.mmm` and does not convert frames.

A manual word correction is a `word_text` overlay. The machine `word.text` is not rewritten. Clearing the overlay restores the machine text.

If an active `participant_assignment` run exists, each word includes that assignment, with a `speaker_override` correction when one is stored. The name comes from the participant row. Unknown stays unknown. Without an active assignment, the transcript is shown without speaker labels. Speaker correction is not a control in this phase.

A missing source file does not hide the transcript. The workspace warns that relink is required before media-dependent work. A valid project proxy can still preview, with that limitation stated on the player.

Words are buttons. Clicking one selects it and, when a proxy is playable, seeks the shared player to that word's `start_us`. The playhead highlights the loaded word whose half-open range contains the canonical time. If playback moves off the loaded page, the workspace asks for the word at that time once and loads the page that contains the returned sequence.

## Direction and chrome

The application chrome stays LTR (`dir="ltr"` on the document). A transcript whose language is Persian, Arabic, Hebrew, or Urdu sets `dir="rtl"` on the transcript text only. An unknown language uses `dir="auto"`. Each word is a `bdi` run. Timecodes stay `dir="ltr"`.

## Not in this phase

Whisper, transcription jobs, waveforms, the timeline, multicam, reels, conversation analysis, and packaging.
