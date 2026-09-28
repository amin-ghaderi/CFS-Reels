# Desktop UX foundation review

Status: review only. Scope is the Phase 5 shell in `amix/apps/desktop/` and whether it can carry the first real editing workspace. Product code, docs other than this file, ADRs, and `legacy/` were not changed.

Read for this review:

- `amix/apps/desktop/` (React source, styles, Tauri config, Rust `engine.rs`, `launch.rs`, `transport.rs`, `ready.rs`, `paths.rs`, `lib.rs`)
- `amix/docs/DESKTOP_FOUNDATION.md`, `amix/docs/ENGINE_SERVICE.md`, `amix/README.md`
- `docs/architecture/DESKTOP_ARCHITECTURE.md`, `PRODUCT_ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `TIMELINE_MODEL.md`, `MEDIA_PIPELINE.md`, `AI_PROVIDER_ARCHITECTURE.md`, ADR 0002
- Python only where a UI state depends on it: job ordering (`storage/jobs.py`), failure text (`jobs/runner.py`), close semantics (`service/runtime.py`)

## Summary

The Phase 5 split is sound. Rust owns the engine process and the token. The webview reaches the engine only through one allow-listed command. The frontend has one typed client, and progress stays in basis points until display. None of that should be redesigned.

Two things must change before an editing workspace is built on top of it:

1. The UI's idea of "engine ready, project open" is not reconciled with the real engine process. A crash, a retry, or a webview reload can leave the UI, Rust, and the engine disagreeing about which project is open.
2. Every engine request runs as a blocking Tauri command, which holds the window's UI thread for the length of the HTTP call.

The rest are shell-structure and presentation corrections for the next UI pass, plus product concerns that need no foundation change today.

| Severity | Count |
|---|---|
| BLOCKER | 2 |
| IMPORTANT | 7 |
| LATER | 12 |
| REJECTED CONCERN | 10 |

---

## 1. Application information architecture

The six destinations map onto the workspaces in `PRODUCT_ARCHITECTURE.md` and each has a distinct primary object:

| Destination | Primary object | Verdict |
|---|---|---|
| Media | `MediaAsset`, layout profiles, protected regions | Keep. Also the natural home for participant setup and relink. |
| Transcript | Words, text revisions | Keep. |
| Conversation | Turns, overlap, threads | Keep for now. It shares preview and time navigation with Transcript. Decide whether it becomes a mode of Transcript only after Transcript exists and the overlap is visible in use. |
| Multicam | `ShotPlan` / `Shot` | Keep. |
| Reels | `ReelCandidate` / `ReelPlan` | Keep. Candidate browser, preview, and plan editing are one workflow, not three destinations. |
| Export | Render outputs and render history | Keep as a destination for the render queue and outputs. Render actions must also be reachable from Multicam and Reels, so Export is not the only way to render. |

Six to seven destinations will not clutter a switcher. Clutter would come from promoting sub-views (candidate list, participant setup, render queue) to top-level entries. They should stay inside their workspace.

**Settings / Models is application-level, not project-level.** Provider references, operating mode, and installed models live in the global database (`DESKTOP_ARCHITECTURE.md`, "Settings workspace data"). A user must be able to install a Whisper model before any project is open. It belongs in the app menu and on the start screen, not in the project workspace switcher. Project-level settings (language hint, participants) belong in Media or a project properties sheet.

**Project-level and app-level actions are not yet separated.** Today the only project action in the chrome is Close project in the top bar, and there are no app-level actions. That is fine for Phase 5. The separation should arrive with native menus (see section 21): File for project actions, the application menu for Settings and Models.

"Projects" from `PRODUCT_ARCHITECTURE.md` is correctly the start screen and not a workspace.

## 2. Core desktop layout

The conceptual frame (top bar, workspace area, bottom status) can carry video, transcript, timeline, tracks, and inspectors. The current implementation of the middle of that frame cannot, because the three columns are global and their contents are fixed. See UX-I1.

What the shell should own permanently:

- Top bar: product, project identity, workspace switcher, project-level status.
- Bottom bar: engine, project, and job summary.
- The mechanism for panels: split, resize, collapse, minimum sizes.

What each workspace should own:

- Which panels exist, where, and their default sizes. Transcript needs preview + transcript + optional inspector + a time strip. Multicam needs preview + multi-track timeline + inspector. Reels needs a candidate list + preview + plan inspector. Not every workspace needs a left column or an inspector.

## 3. Project lifecycle UX

| State | Current modeling | Assessment |
|---|---|---|
| No project | `project === null` | Clear. |
| Creating | Native dialog, then `NameDialog`, then `busy` | Works. `busy` is shared by every action. |
| Opening | `busy` only | No visible "Opening…" state. Fine while opening is instant. It will not be once migrations or media checks take time. |
| Open | `project` set | Clear. `read_only` is returned but never shown. |
| Closing | `busy` makes the button say "Closing" | Works for now. Close silently cancels running jobs; no confirmation. |
| Locked | `project_already_locked` mapped to a sentence | Good. The message says "another AMIX window". The lock is held by a process, so the wording is accurate. |
| Missing media | Not represented | The integrity job reports media status and problems in `result`. The UI shows only `SUCCEEDED`. See UX-I3. |
| Migration required | Writable open migrates silently | Correct today (only 0001 → 0002). See UX-L8. |
| Engine unavailable | `FAILED` gate | Clear at startup. Not reachable after startup. See UX-B1. |

The states become ambiguous once real media operations exist because "open" will carry sub-states: media missing, analysis stale, jobs running. That needs a named session state, not more booleans (UX-I3).

## 4. Engine failure UX

- **Retry engine is enough as the recovery action.** A restart button plus a clear message is the right scope.
- **Diagnostics are correctly separated.** `Diagnostics` renders only under `import.meta.env.DEV` and shows state, version, host, and port. The token never reaches JavaScript, so it cannot be shown by mistake.
- **Project actions are correctly hidden until READY.** The start screen and shell render only in READY.
- **Restart semantics after a project was open are not defined in the UI.** Rust closes the tracked project on retry (`begin_start` in `engine.rs`), but the React `project` state is never cleared. And READY never changes to FAILED after startup, because nothing watches the child process. See UX-B1.
- The failure message for a missing interpreter ("The development engine was not found in amix/.venv…") is developer text. That is right for Phase 5 and must change when the packaged sidecar arrives (UX-L7).
- `STOPPED` renders as "Starting the local engine". STOPPED occurs only during exit, so this is harmless.

## 5. Job UX

The inspector is the wrong permanent home for jobs. In an editor, the inspector shows properties of the current selection (a word, a shot, a candidate). If jobs occupy it, the first editing workspace must either evict jobs or build a second inspector.

Long-term shape, without a new backend event system:

- The status bar shows a compact summary: "2 running · 1 failed". It is always visible and never takes workspace space.
- Clicking the summary opens an activity panel (bottom drawer or popover). Active jobs sort first. History is below, collapsed by default.
- Each row shows only the actions its state allows. Cancel for QUEUED, RUNNING, and CANCEL_REQUESTED. Retry for FAILED, INTERRUPTED, and CANCELLED. Not two disabled buttons on every succeeded row.
- Retry attempts stay separate rows. Show `attempt` and optionally group by `resumed_from_job_id`. History stays history.
- Workspace-specific job actions ("Transcribe", "Plan shots") stay in their workspace and report into the same activity list.

Current defects are in UX-I2.

## 6. Future Transcript workspace (shell requirements only)

The shell must allow:

- A layout of video preview + scrollable transcript + optional inspector + time strip, with resizable splits (UX-I1).
- A long, virtualized transcript list without the shell imposing page scroll. `.workspace` currently has `padding: 24px` and `overflow: auto`, which is document-style scrolling. Workspaces need to own their own scroll regions.
- RTL content inside an LTR chrome (section 11).
- A playhead updated at display rate without re-rendering the shell (section 19).
- Keyboard input routed to the transcript without fighting text inputs or IME composition (section 13).
- Engine calls that return large word lists without freezing the window (UX-B2).

No current shell decision prevents this once UX-I1 and UX-B2 are addressed.

## 7. Future Multicam workspace (shell requirements only)

Preview, participant sources, a multi-track timeline (floor, overlap, shots), an inspector, and manual override all fit a workspace-owned layout with a horizontal split (preview over timeline) and a right inspector. Blocking factors are the same as Transcript: fixed global columns (UX-I1) and a blocking transport (UX-B2). Track and participant colors need token slots (UX-I5). The domain already has an optional participant color.

## 8. Future Reels workspace (shell requirements only)

Candidate list, preview, scores, approve and reject, and export fit one workspace with a left list, center preview, and right inspector. Approve and reject are candidate states shown in the list, not separate destinations. Rendering reports into the shared activity list. Nothing here requires the main navigation to grow.

## 9. Density

Current values in `styles.css`:

| Token or rule | Value | Assessment |
|---|---|---|
| Base font | 14px | Good for editor chrome. |
| Button | `padding: 8px 14px`, about 34px tall | Form-sized. Toolbars and track headers need a compact control around 24–28px. |
| Radius | 8px on buttons, cards, and inputs | Reads as SaaS. Editors typically use 2–4px on controls. |
| `.workspace` padding | 24px | Document padding. Editor panels usually run edge to edge with 4–8px internal padding. |
| `h1` in workspace | 28px | Oversized for a panel title. |
| Job rows | Card per job, 12px padding, meter, two buttons, about 110px tall | About eight jobs fill the inspector. |
| Top bar / status bar | 52px / 36px | Top bar slightly tall. Acceptable. |

The start screen and gate cards are fine as they are. They are empty states, and generous space is correct there. The concern is carrying card and form sizing into editor panels. See UX-I5.

## 10. Typography

- `font-family: "Segoe UI", system-ui, sans-serif` has no remote fonts. On macOS, Segoe UI is absent and `system-ui` resolves to San Francisco. That is fine for Latin chrome.
- For Persian content, Windows Segoe UI covers Arabic script. macOS falls back from `system-ui` to its Arabic system face. This is workable, but rendering will differ by OS and is not chosen deliberately.
- Missing: a numeric style for timecodes and counts (`font-variant-numeric: tabular-nums`), a monospace token for technical metadata, and a separate content font stack for transcript text.

If system Persian fallback proves poor, bundling an open-licensed Persian face locally is allowed by the no-remote-assets rule. Decide after seeing real transcripts. See UX-L2.

## 11. RTL

The chrome should stay LTR. The content should be direction-aware per element. Recommended strategy, not to implement now:

- `<html lang="en" dir="ltr">` stays as the chrome direction. Do not flip the application to RTL.
- Transcript containers set `lang` and `dir` from the transcript's language (`Transcript.language` exists in the domain), not from the UI locale. Use `dir="auto"` only where the language is unknown.
- Words and speaker names are isolated inline runs (`<bdi>` or `unicode-bidi: isolate`), so a Latin name in a Persian line does not reorder its neighbors.
- Timecodes and technical values are always `dir="ltr"`, isolated, and tabular, even inside an RTL line.
- Content components use CSS logical properties (`padding-inline-start`, `margin-inline-end`, `text-align: start`). Chrome may keep physical properties.
- Timelines stay left-to-right in time regardless of content language. Time is not text.

Nothing in Phase 5 prevents this. `nav button { text-align: left }` is chrome and correct as LTR.

## 12. Time display

No time formatting exists yet, which is correct. When it arrives:

- The engine owns canonical time arithmetic: snapping, ranges, turn building, frame conversion for render (`TIMELINE_MODEL.md`).
- The frontend owns display formatting only: microseconds to `HH:MM:SS.mmm`, and later to frames using the asset's `fps_num/fps_den` supplied by the engine.
- One pure module (for example `src/time/`) holds the formatters, with unit tests, in the same way `progressPercent` isolates basis points today. Components never divide microseconds themselves.
- The player boundary converts `us / 1e6` for the media element and writes edits back as integer microseconds, as `TIMELINE_MODEL.md` already states.
- JavaScript `Number` is exact for integer microseconds far beyond any media length (2^53 µs is about 285 years). No BigInt or time library is needed.

See UX-L3.

## 13. Keyboard workflow

No architectural blocker. Buttons are native, there is no global key handler yet, and nothing captures keys. Points to settle when the first shortcut lands:

- One shell-level key router that dispatches to the active workspace. Not per-component `window.addEventListener` calls.
- Shortcuts never fire while a text field is focused, and never during IME composition (`event.isComposing`). Persian input uses IMEs, so this is a correctness issue, not polish.
- Space conflicts with native button activation. When a button has focus, Space presses it. Editors usually make Space mean play/pause everywhere except text inputs. That policy must be explicit.
- Undo and redo operate on engine-backed edits. The shortcut layer only dispatches; it does not own the history.

See UX-L4.

## 14. Focus management

The shell already has an active workspace (`destination`). "Active panel" becomes necessary when a workspace has two keyboard-driven panels at once (transcript list and timeline both reacting to arrows). Defer it until the first such workspace. Then add the smallest possible model: the workspace tracks which of its panels owns arrow keys, with a visible focus state on that panel. Do not build a global interaction framework before then. See UX-L5.

## 15. Resizing

- Grid columns `minmax(160px, 200px) / 1fr / minmax(220px, 300px)` behave correctly down to the 960px minimum: the workspace keeps about 460px.
- Panels cannot be resized or collapsed (UX-I1).
- The default size of 1400×900 is not clamped to the monitor. The minimum height of 640 exceeds the usable logical height on some scaled laptops. For example, 1366×768 at 125% scaling is about 1093×614 logical before the taskbar. See UX-I6.
- CSS pixels scale correctly under Windows and macOS scaling. Future canvas-based waveform and timeline drawing must scale by `devicePixelRatio` (UX-L11).

## 16. Accessibility

Sound foundations: native `<button>` elements, `:focus-visible` outline in the accent color, `aria-current="page"` on the active destination, `role="alert"` on error banners, `aria-label` on nav and the jobs aside, and a real `<label>` on the name input. Contrast of primary and secondary text on panels is comfortably high.

Foundational gaps (UX-I7):

- `NameDialog` has no `role="dialog"`, `aria-modal`, or accessible name. Focus is not trapped, and it is not returned to the Create project button afterwards. Escape works only while the input has focus. This component will be copied for every future modal.
- Job status changes and the status bar are not announced (no polite live region).

## 17. Visual language

Neutral dark greys with one blue accent, a danger red, and a success green are a reasonable base for an editing application. Panel versus background distinction is subtle but present.

Generic SaaS patterns to avoid carrying forward (UX-I5):

- Accent used as a filled "primary" button for ordinary actions (Run project integrity check). In editors, accent usually marks selection, playhead, active state, and focus. Filled accent on every primary button competes with those.
- 8px radius everywhere, cards as the default container, and document-style headings inside panels.
- Missing semantic slots that editing needs soon: warning (missing media, interrupted jobs), selection background, hover, and a small set of track or participant colors.

The `success` token is defined but unused. That is fine.

## 18. Component strategy

- **Good:** all engine calls go through `src/api/client.ts`. Error mapping (`errors.ts`) and job predicates (`jobs.ts`) are pure and tested. There are no premature generic components.
- **Problem:** `App.tsx` is about 420 lines. It holds all state, both polling loops, every engine call, and every screen (engine gate, start screen, shell, jobs list, dialog). Network calls are made from inside the visual component. See UX-I4.
- Minor duplicated state: `folder` shadows the picked path next to `project`. That is intentional, because the engine does not return paths, and it is harmless. `busy` is one flag for several unrelated operations.

## 19. State architecture

Simple React state and context remain reasonable for the next one or two workspaces, once state is moved out of `App` into a project-session provider and a jobs hook.

Reconsider when any one of these becomes true. These are concrete thresholds, not "the product will be complex":

- **Playhead or other state that changes every animation frame.** This must never be React state in a context above large trees. When playback arrives, keep the playhead in a small external store read with `useSyncExternalStore` or refs. That need arrives with the first video preview, probably in Phase 6.
- **The same engine data shown by three or more panels with independent refresh and invalidation** (words, assignments, and shots). The first real need is likely a server-state cache, not Redux.
- **Undo and redo spanning several panels**, if the engine does not own the edit history.

## 20. Security and UX interaction

The UX recommendations here do not require exposing the token, adding wildcard or origin CORS, showing sensitive diagnostics, or giving the frontend SQLite access. Two future pressure points should be anticipated:

- **Video preview.** A `<video>` element needs a URL. The tempting shortcuts are allowing `media-src http://127.0.0.1:<port>` and putting the token in a query string, or opening Tauri's asset scope to the whole disk. The engine already refuses tokens in URLs. Preview media should be served by a Rust custom protocol or an asset scope limited to the open project's media and proxies. See UX-L6.
- **Engine diagnostics.** Showing Python stderr to help debug startup is useful in development. It must stay DEV-only, bounded, and redacted, like the existing `transport::redact`. See UX-L7.

`DESKTOP_ARCHITECTURE.md` still describes CORS restricted to the webview origin, a WebSocket or SSE progress channel, a Tauri-generated token, and a UI-sent shutdown. Phase 5 deliberately did none of those. A future agent reading only that document could "restore" CORS. See UX-L9.

## 21. Native desktop expectations

| Expectation | Classification | Note |
|---|---|---|
| Native menus (File: New/Open/Close; app menu: Settings) | NEEDED SOON | Separates project and app actions. On macOS, Tauri's default menu already supplies Edit (copy/paste) behavior; keep it when customizing. |
| Window title with project name | NEEDED SOON | Cheap. Helps the taskbar, Mission Control, and screen readers. |
| Keyboard shortcuts | NEEDED SOON | With the first editing workspace (section 13). |
| Exit protection while jobs are running | NEEDED SOON | Quitting during a long transcription silently turns it into INTERRUPTED. A confirm on close or exit when active jobs exist. |
| Recent projects | NEEDED SOON | Depends on the global application database. Do not fake it with localStorage (REJECTED-7). |
| Drag and drop | LATER | Media files onto Media belongs with ingest. Decide then between Tauri's native drop event (gives paths) and HTML5 drop, since Tauri intercepts drops by default. Project-folder drop is optional. |
| Context menus | LATER | For words, shots, and candidates. In release builds, suppress the webview default menu (it offers Reload; see UX-B1). |
| Unsaved-change protection | LATER | Depends on whether edits commit to the engine per action. If they do, only running-job protection is needed. |
| File associations | NOT NECESSARY | Projects are folders. Revisit only if a project package format is adopted. |

## 22. Scope

No timeline, waveform, transcript editor, multicam, or Reel layouts are proposed here beyond which panels the shell must be able to host.

---

## Findings

### UX-B1: The UI project session is not reconciled with the engine process

- **Severity:** BLOCKER
- **Affected:** `src/App.tsx` (engine status effect, `project` state), `src-tauri/src/engine.rs` (`Phase`, `request`, `begin_start`, `project_handle`), `src-tauri/src/lib.rs`
- **Current behavior:**
  - React polls `engine_status` only while STARTING or STOPPED. Once READY, it never looks again.
  - Rust sets READY once and never checks whether the child process is still alive. A dead engine surfaces only as the string "The engine did not respond." on each request.
  - `engine_retry` in Rust closes and forgets the old project handle. React keeps `project`, `jobs`, and `folder`.
  - A webview reload (F5, Ctrl+R, or the default context menu's Reload; also full reloads during development) resets React to the start screen. Rust and the engine still hold the project open and locked.
- **Problem:** Three parties hold session state (React, Rust, engine) and nothing re-synchronizes them after an unplanned transition.
- **Concrete future failure scenario:** In Phase 6 a Whisper or FFmpeg stage exhausts memory and the Python process dies mid-edit. The UI still shows READY and the open project. Every action fails with a generic message, and Retry engine is unreachable because the FAILED gate never renders. Alternatively, the user presses F5 by habit: AMIX returns to the start screen, and opening the same project returns `project_already_open` until the app is quit.
- **Minimum correction:**
  1. Rust detects child exit: check `try_wait` when a request fails, or run a small watcher thread, and move to FAILED with a plain message.
  2. React re-reads `engine_status` whenever a request fails at the transport level, and at a slow interval (a few seconds) while READY.
  3. Any transition out of READY clears the React project and job state and tells the user the project was closed.
  4. Add a non-secret `engine_session` query (current handle plus project info, never the token) that React calls on mount to restore after a reload. Alternatively, Rust closes the tracked project when the main webview reloads. In release builds, also disable reload shortcuts and the default webview context menu.
- **When:** Before the first editing workspace.

### UX-B2: Engine requests block the window's UI thread

- **Severity:** BLOCKER
- **Affected:** `src-tauri/src/engine.rs` (`engine_request`, `engine_retry`, `engine_status` are synchronous `#[tauri::command] pub fn`)
- **Current behavior:** Synchronous Tauri commands run inline in the IPC handler (`body_blocking` in `tauri-macros`), which on WebView2 and WKWebView is the UI thread. `engine_request` performs a blocking `ureq` call with a 15-second read timeout. Project close waits up to the engine's shutdown timeout (2 seconds by default) while jobs stop. The job poll makes a blocking call every second.
- **Problem:** Any slow engine response freezes the whole window: no repaint, no input, no close button. A hung engine can hold the window for up to 15 seconds per call.
- **Concrete future failure scenario:** The Transcript workspace loads 20,000 words for a two-hour episode, or opening a project runs a migration. The window freezes and Windows marks it "Not responding" while video preview and scrolling stop. Combined with UX-B1, a dead engine produces repeated freezes.
- **Minimum correction:** Make the engine commands `async`, or use `#[tauri::command(async)]`, and run the blocking `ureq` call on a blocking worker (`tauri::async_runtime::spawn_blocking`). No transport redesign, no new dependency, and no change to the allow-list or token handling.
- **When:** Before the first editing workspace.

### UX-I1: Shell regions are global and fixed; the inspector is hard-wired to jobs

- **Severity:** IMPORTANT
- **Affected:** `src/App.tsx` (`workspace-body`, `nav`, `inspector`), `src/styles.css` (`.workspace-body`, `.workspace`)
- **Current behavior:** Every workspace gets the same three columns: a 200px navigation column, a padded scrolling center, and a 300px inspector that always shows jobs. Nothing can be resized or collapsed.
- **Problem:** Editing workspaces need different panel sets and user-sized splits. A 200px column spent on six text buttons is space Media and Reels need for their lists. The inspector must show the current selection.
- **Concrete future failure scenario:** Transcript needs preview, transcript, and inspector side by side on a 1440px laptop. The developer either squeezes all three into the center column or rewrites the shell mid-feature, breaking the placeholder workspaces.
- **Minimum correction:** The shell owns the top bar with the workspace switcher (a compact tab strip or a thin icon rail, not a 200px column), the status bar, and one simple split-pane primitive (resize, collapse, minimum size). Each workspace owns its own body layout. Move jobs out of the inspector into the status bar summary and an activity panel (UX-I2). Store panel sizes as app-level UI preferences, not in the project database; `DOMAIN_MODEL.md` excludes UI layout pixels from the project.
- **When:** In the first editing-workspace pull request, before workspace-specific layout code is written.

### UX-I2: Job presentation will not scale and shows raw engine text

- **Severity:** IMPORTANT
- **Affected:** `src/App.tsx` (jobs list and poll effect), `src/api/jobs.ts`, `amix_engine/jobs/runner.py` (source of `error_message`, read only)
- **Current behavior:**
  - Jobs render oldest first (the engine orders by `created_at`), so the active job sits at the bottom of a growing list.
  - Status is shown as raw enum text (`CANCEL_REQUESTED`).
  - Every row has Cancel and Retry, mostly disabled.
  - `error_message` is displayed directly. For handler exceptions it is `str(exc)` from Python.
  - A poll error stops polling permanently until another action restarts it.
- **Problem:** Once transcription, alignment, and render jobs exist, the list becomes a long, undifferentiated history. Python exception text reaches normal users, contrary to the Phase 5 rule. After one transient poll failure, progress looks frozen.
- **Concrete future failure scenario:** A render fails with an FFmpeg or Python message such as `[Errno 2] No such file or directory: 'C:\\…'`, shown as-is in the job row. Meanwhile the running transcription is off-screen below twenty earlier integrity checks.
- **Minimum correction:** Sort active first. Map `status` to short human labels. Show only applicable actions. Show a mapped sentence from `error_code`, with `error_message` behind the existing Details disclosure. After a poll error, back off and retry instead of stopping. Keep one row per attempt.
- **When:** Next UI foundation pass, together with UX-I1.

### UX-I3: The project session is implicit booleans, and project health has no UI home

- **Severity:** IMPORTANT
- **Affected:** `src/App.tsx` (`project`, `busy`, `naming`, `notice`)
- **Current behavior:**
  - Session state is `project | null` plus one shared `busy` flag and `naming`.
  - `read_only` is never shown.
  - Close cancels running jobs without asking.
  - The integrity job's `result` (asset statuses, `problems`, active-run references) is ignored, so a check that found missing media looks identical to a clean one.
  - Errors appear in a banner inside the workspace, away from the action that caused them.
- **Problem:** Opening, open-with-problems, and closing will need distinct presentation once media and migrations exist. More booleans will produce impossible combinations.
- **Concrete future failure scenario:** A user relocates the media drive. The integrity check reports `SUCCEEDED`, the workspace renders as healthy, and the first render fails with a missing-file error.
- **Minimum correction:**
  - Move session state into a hook or provider with one explicit state: none, creating, opening, open, or closing, plus the project info.
  - Confirm before closing when active jobs exist.
  - Show a one-line project health summary from the latest integrity result (for example, "2 media files missing") in the top bar or status bar.
  - Show a read-only marker when `read_only` is true.
- **When:** Next UI foundation pass. Required before the Media workspace.

### UX-I4: `App.tsx` is a monolith that mixes network calls and views

- **Severity:** IMPORTANT
- **Affected:** `src/App.tsx`
- **Current behavior:** One component holds engine state, project state, job polling, every engine call, and five screens.
- **Problem:** Each new workspace would add state and effects to the same component, re-rendering the whole application on every job poll tick.
- **Concrete future failure scenario:** Adding the Transcript workspace puts a playhead, a word selection, and a word list into `App`. Every one-second job poll re-renders the transcript. Every playhead update re-renders the job list.
- **Minimum correction:** Split into `EngineGate`, `StartScreen`, `ProjectShell`, `ActivityPanel`, and `NameDialog`. Move state and engine calls into `useEngineStatus`, `useProjectSession`, and `useJobs`, all still calling `api/client.ts`. No state library.
- **When:** Before or with the first editing workspace. This is a refactor, not a redesign.

### UX-I5: Design tokens are sized for forms, not editor chrome

- **Severity:** IMPORTANT
- **Affected:** `src/styles.css`
- **Current behavior:** 34px buttons, 8px radius on everything, 24px workspace padding, 28px headings, card-per-job, and accent-filled primary buttons. No warning, selection, hover, numeric, monospace, or track and participant color tokens.
- **Problem:** Future toolbars, track headers, and dense lists will either override these tokens ad hoc or inherit sizes that waste space.
- **Concrete future failure scenario:** The timeline's track headers and transport controls are built from the shared button and inherit 34px height and 8px rounding. Four tracks and a toolbar consume a third of a 900px window.
- **Minimum correction:**
  - Add a compact control size and a smaller radius for controls.
  - Add tokens for warning, selection, hover, `tabular-nums` numeric text, monospace, and a small set of track or participant colors.
  - Reserve accent for selection, focus, and active state.
  - Keep the generous start screen as it is.
- **When:** Next UI foundation pass.

### UX-I6: Window size defaults do not adapt to small or scaled screens

- **Severity:** IMPORTANT
- **Affected:** `src-tauri/tauri.conf.json` (`width 1400`, `height 900`, `minWidth 960`, `minHeight 640`)
- **Current behavior:** A fixed 1400×900 initial size, and a 960×640 minimum enforced regardless of monitor.
- **Problem:** On a 1366×768 laptop at 125% scaling (about 1093×614 logical, less after the taskbar), the minimum height does not fit. The default size is larger than the screen on several common laptop configurations.
- **Concrete future failure scenario:** On first launch on a small laptop, the bottom status and activity bar sits below the screen edge and cannot be reached by resizing.
- **Minimum correction:** Lower the minimum height to about 560–600. At startup, clamp the initial size to the current monitor's work area, or maximize when the monitor is smaller than the default. Tauri window APIs support this; it is window plumbing, not business logic.
- **When:** Next UI foundation pass.

### UX-I7: The modal foundation and status announcements are not accessible

- **Severity:** IMPORTANT
- **Affected:** `src/App.tsx` (`NameDialog`, `statusbar`)
- **Current behavior:** The dialog has no dialog role, modal flag, accessible name, focus trap, or focus return. Escape works only inside the input. Status bar changes are not announced.
- **Problem:** Every future modal (relink, render settings, confirm close) will be copied from this one.
- **Concrete future failure scenario:** Keyboard users tab out of the confirm-close dialog into the shell behind it and trigger actions while the modal is open.
- **Minimum correction:** Use native `<dialog>` with `showModal()`, which provides modality, Escape, and focus containment, or add `role="dialog"`, `aria-modal`, `aria-labelledby`, and restore focus on close. Add a polite live region to the status bar for job completion and failure.
- **When:** Next UI foundation pass.

### UX-L1: Settings / Models is app-level, and the destination list waits for real use

- **Severity:** LATER
- **Affected:** Navigation (`DESTINATIONS`), start screen
- **Current behavior:** Six project destinations. No Settings.
- **Problem:** If Settings / Models is added to the project switcher, models cannot be installed before a project exists, and app state appears project-scoped.
- **Concrete future failure scenario:** A new user must create a throwaway project just to install a Whisper model.
- **Minimum correction:** Put Settings / Models in the app menu and on the start screen. Revisit merging Conversation into Transcript only after Transcript ships.
- **When:** When Settings / Models is implemented.

### UX-L2: Content direction and typography strategy for Persian

- **Severity:** LATER
- **Affected:** Future transcript, speaker, and metadata components; `styles.css` font stack
- **Current behavior:** LTR chrome with a Latin-first system stack. No `lang` or `dir` policy for content.
- **Problem:** Without a policy, the first transcript component will set `dir` ad hoc, or flip the whole app.
- **Concrete future failure scenario:** A Persian line containing an English name and a timecode renders with the timecode digits and punctuation reordered.
- **Minimum correction:** Adopt section 11 when the transcript component is written: per-element `lang` and `dir` from transcript language, isolated words and names, LTR tabular timecodes, and logical properties in content components. Evaluate system Persian rendering on both OSes before deciding on a locally bundled face.
- **When:** First Transcript implementation.

### UX-L3: A single display-only time formatting module

- **Severity:** LATER
- **Affected:** Future `src/time/`
- **Current behavior:** None. Correct for Phase 5.
- **Problem:** Formatting could be scattered across components that each divide microseconds.
- **Concrete future failure scenario:** The transcript and the timeline round milliseconds differently, and the same word shows two start times.
- **Minimum correction:** One tested module that formats microseconds for display, and frames when given the engine's rational frame rate. No canonical arithmetic in the UI.
- **When:** The first component that displays time.

### UX-L4: Keyboard routing policy

- **Severity:** LATER
- **Affected:** Future shell key handling
- **Current behavior:** No shortcuts. Correct.
- **Problem:** Ad hoc listeners will conflict with inputs, IMEs, and focused buttons.
- **Concrete future failure scenario:** Typing a Persian correction through an IME triggers J/K/L transport shortcuts.
- **Minimum correction:** One shell-level router scoped to the active workspace. Ignore events from editable targets and during `isComposing`. Define an explicit Space policy.
- **When:** The first shortcut.

### UX-L5: Active-panel focus model

- **Severity:** LATER
- **Affected:** Future workspace layouts
- **Current behavior:** Only the active workspace is tracked.
- **Problem:** Two keyboard-driven panels in one workspace will both react to arrow keys.
- **Concrete future failure scenario:** The Down arrow moves both the transcript selection and the timeline cursor.
- **Minimum correction:** The workspace tracks which panel owns arrows, with a visible active-panel indicator. No global framework.
- **When:** The first workspace with two keyboard-driven panels.

### UX-L6: Media preview URL boundary

- **Severity:** LATER
- **Affected:** Future preview player, CSP, Rust protocol handling
- **Current behavior:** No media playback. The CSP allows no engine origin.
- **Problem:** Preview needs a URL the webview can load. The shortcuts (engine port in `media-src`, token in a query string, a broad asset scope) weaken the Phase 5 boundary.
- **Concrete future failure scenario:** To make `<video>` work, a developer adds `http://127.0.0.1:*` to `media-src` and appends `?token=` to media URLs. The token then appears in webview history and logs.
- **Minimum correction:** Serve preview bytes, with range requests, through a Rust custom protocol or an asset scope limited to the open project's media and proxies. The engine stays unreachable from the webview.
- **When:** The first video preview.

### UX-L7: Engine failure messaging for packaged builds and a development stderr tail

- **Severity:** LATER
- **Affected:** `src-tauri/src/launch.rs`, `engine.rs` messages, `Diagnostics`
- **Current behavior:** Failure messages mention `amix/.venv`. Python stderr goes only to the Rust process's stderr.
- **Problem:** Packaged users would see developer paths. Developers cannot see why Python failed to start without a terminal.
- **Concrete future failure scenario:** A packaged build shows "not found in amix/.venv" to an end user.
- **Minimum correction:** Separate user messages from development detail. In DEV only, keep a bounded, redacted tail of stderr for the diagnostics block.
- **When:** With the packaged-sidecar phase, and the stderr tail whenever it is first needed.

### UX-L8: Migration consent, newer-schema messaging, read-only mode

- **Severity:** LATER
- **Affected:** Open flow, `errors.ts` mapping for `schema_mismatch`
- **Current behavior:** Writable open migrates silently. A too-new project maps to a generic "cannot be opened in the requested mode". Read-only open is not offered.
- **Problem:** After the first user-visible schema change, older AMIX builds cannot reopen a migrated project, and the user was not told.
- **Concrete future failure scenario:** A user opens a shared project in a newer AMIX. A collaborator on the older build can no longer open it.
- **Minimum correction:** When the engine can report "migration pending", show a confirm dialog. Map the newer-schema case to "created by a newer version of AMIX".
- **When:** The first schema revision after 0002 that users will meet.

### UX-L9: `DESKTOP_ARCHITECTURE.md` describes a different transport than Phase 5

- **Severity:** LATER
- **Affected:** `docs/architecture/DESKTOP_ARCHITECTURE.md` (not modified by this review)
- **Current behavior:** The document describes CORS restricted to the webview origin, WebSocket or SSE progress, a Tauri-generated token, and a UI-sent shutdown.
- **Problem:** A future agent could treat that document as the target and add CORS or direct webview fetches.
- **Concrete future failure scenario:** A developer adds `CORSMiddleware` with the Tauri origin "per the architecture doc" and moves requests into React `fetch`.
- **Minimum correction:** A documentation pass aligning that section with `amix/docs/DESKTOP_FOUNDATION.md`: Rust bridge, no CORS, polling.
- **When:** The next documentation pass.

### UX-L10: Engine-initiated jobs and idle polling

- **Severity:** LATER
- **Affected:** `src/App.tsx` poll effect
- **Current behavior:** Polling starts after a UI action and stops when all known jobs are terminal.
- **Problem:** When pipeline stages enqueue follow-on jobs themselves (transcribe, then align), the UI will not see them.
- **Concrete future failure scenario:** Transcription finishes, the engine queues alignment, and the activity panel shows nothing running.
- **Minimum correction:** While a project is open, keep a slow idle poll (several seconds) in addition to the fast poll during active jobs. Still no WebSocket or SSE.
- **When:** The first engine-chained job.

### UX-L11: High-DPI canvas rendering

- **Severity:** LATER
- **Affected:** Future waveform and timeline
- **Current behavior:** No canvas.
- **Problem:** Canvas drawn at CSS-pixel resolution is blurry on scaled displays.
- **Concrete future failure scenario:** A blurry waveform on Retina and 150%-scaled Windows displays.
- **Minimum correction:** Size canvases by `devicePixelRatio` and redraw when it changes.
- **When:** The first canvas component.

### UX-L12: Where panel layout preferences live

- **Severity:** LATER
- **Affected:** Future split panes
- **Current behavior:** None.
- **Problem:** Panel sizes could end up in `project.sqlite`, or be mistaken for the kind of localStorage authority that `DESKTOP_ARCHITECTURE.md` forbids.
- **Concrete future failure scenario:** Panel sizes stored per project conflict when a project moves between a laptop and a desktop monitor.
- **Minimum correction:** Keep layout preferences app-level and non-authoritative: localStorage is acceptable for pure UI layout, or the global application database once it exists. Never store tokens or project authority there.
- **When:** With the first resizable panel.

---

## Rejected concerns

| ID | Tempting change | Why not now |
|---|---|---|
| REJECTED-1 | Replace polling with WebSocket or SSE | Polling at about 1s is adequate for job progress, and the engine was built so a later transport can read the same rows. Adding streaming now adds a second lifecycle to reconcile (see UX-B1). |
| REJECTED-2 | Adopt Redux, Zustand, or similar | No shared-cache, undo, or high-frequency state exists yet. Thresholds are in section 19. |
| REJECTED-3 | Adopt a UI kit or Tailwind for a "professional look" | Professional here means density, hierarchy, and predictable behavior. A small token set does that. |
| REJECTED-4 | A docking-window framework (floating, tabbed, rearrangeable panels) | Workspace-owned splits with resize and collapse cover every workspace described. Docking can wait for proven demand. |
| REJECTED-5 | Flip the application chrome to RTL or localize the chrome now | Content direction is per element. The chrome stays LTR. |
| REJECTED-6 | Call the engine with `fetch` from the webview and allow the Tauri origin in CORS | It would move the token into JavaScript and widen the engine boundary. The Rust bridge already works. |
| REJECTED-7 | Recent projects via localStorage | It would create a second, unauthoritative project registry ahead of the global application database. |
| REJECTED-8 | A global shortcut and command framework now | There are no shortcuts yet. Section 13 lists the only constraints to respect. |
| REJECTED-9 | A frontend time library or float-seconds model | Integer microseconds with a display-only formatter is enough. `Number` is exact at these magnitudes. |
| REJECTED-10 | Merge Multicam and Reels into one generic edit workspace or graph | `PRODUCT_ARCHITECTURE.md` already rejects a unified edit graph for V1. The two workspaces share time, words, and turns, not UI. |

---

## Things AMIX Should Not Redesign

Confirmed sound in the Phase 5 code:

- **Rust owns the engine lifecycle.** Launch, ready-record parsing, and shutdown sit in `launch.rs` and `engine.rs`. Only `launch.rs` knows about the development interpreter, so a packaged `amix-engine` can replace it.
- **Strict ready-record parsing.** The first non-empty stdout line must be the ready event. A log line before it is a failure, not something to scan past. This is tested.
- **No browser CORS workaround.** The engine has no CORS middleware. The webview reaches it only through `engine_request`, which allows `GET` and `POST` on `/v1/...` of the ready port, with no query, fragment, or `..`.
- **Memory-only token that never reaches JavaScript.** `EngineStatus` has no token field (tested), `ReadyRecord`'s debug output redacts it, and stderr is redacted.
- **One typed, centralized EngineClient.** All calls go through `src/api/client.ts`, with types matching the FastAPI schemas.
- **Stable error codes mapped to sentences.** `errors.ts` accepts only snake-case codes and shows a generic sentence otherwise. Details show the code, not raw JSON.
- **Progress in basis points until display.** `progressPercent` is pure and tested. Persisted semantics are untouched.
- **Retry as a new visible row.** History is preserved.
- **Polling before streaming.** It is modest, scoped to an open project, and stops when idle.
- **Simple React state before proven complexity.** It should be reorganized (UX-I4), not replaced.
- **Native folder dialogs, with path joining in Rust.** `paths.rs` rejects blank names and path separators.
- **No remote assets and a restrictive CSP.** System fonts, self-only scripts.
- **Development diagnostics behind `import.meta.env.DEV`.** They show state, version, host, and port only.
- **No fake data.** Future workspaces say "Not implemented yet". There is no fake recent-project list.

---

## Phase 6 UX Readiness

**READY WITH SMALL CORRECTIONS**

Required before implementing the first real editing workspace:

1. **UX-B1:** Reconcile the session. Rust detects engine exit and reports FAILED. React re-checks status on transport failure and periodically while READY, and clears project state on any exit from READY. Add a non-secret session query so a webview reload restores or cleanly closes the open project. Disable reload and the default context menu in release.
2. **UX-B2:** Make the engine commands async so HTTP calls do not run on the UI thread.

Do in the same pull request as the first workspace, before workspace layout code is written:

3. **UX-I1:** The shell owns the switcher, status bar, and a split-pane primitive. Workspaces own their body layout. Jobs leave the inspector.
4. **UX-I4:** Split `App.tsx` into screens and hooks around the existing `api/client.ts`.

The remaining IMPORTANT items (UX-I2, UX-I3, UX-I5, UX-I6, UX-I7) belong to the next UI foundation pass. UX-I3 is needed before the Media workspace.
