# Desktop architecture

## Processes

| Process | Owns | Does not own |
|---|---|---|
| Tauri (Rust) | Window, menus, file dialogs, opening the project folder, starting and stopping the Python sidecar, OS credential prompts, single-instance lock | Timeline math, diarization, prompts, SQL domain rules |
| WebView (React/TypeScript) | Workspaces, playback chrome, forms, progress display | FFmpeg, Whisper, direct SQLite writes |
| Python engine | Domain, pipeline, SQLite, files, FFmpeg, local ML, provider calls | Windowing, native menus, Keychain implementation details |

One engine process per app instance. Jobs run on worker threads or short-lived child processes **inside** that engine (FFmpeg, Whisper). They are not a second distributed system.

## Lifecycle

1. User launches AMIX. Tauri starts.
2. Tauri picks `127.0.0.1` and port `0` (ephemeral), generates a session token (random, memory only).
3. Tauri spawns the bundled Python sidecar with the port, token, and paths to app support and the optional project. The sidecar binds only that loopback address.
4. UI loads and calls `/health` with the token. Until health succeeds, workspaces show “engine starting”.
5. Opening a project tells the engine the project root. The engine opens `project.sqlite`.
6. Quit: UI sends shutdown, engine cancels jobs, marks `running` jobs `interrupted`, closes SQLite, exits. Tauri waits with a timeout, then kills the sidecar.
7. Crash: next start sees `running` jobs and marks them `interrupted`. Completed stages stay cached. The user can resume.

The sidecar is not left running after the shell exits.

## Local API

HTTP on loopback plus the session token (header). CORS origin restricted to the Tauri webview origin.

This is a local IPC boundary, not a public API. It is not bound to `0.0.0.0`. It is not authenticated as a user account. Anyone who can see the token on the machine can call it; the token is not written to the project.

WebSocket or server-sent events carry job progress: `job_id`, stage, fraction, message. Cancel is `POST /jobs/{id}/cancel`.

Large media is not streamed through JSON. The UI plays files via URLs the shell can serve (custom protocol or engine range-request to a file path the engine allows). The allow-list is the current project’s assets and exports. No arbitrary path read.

## What the UI may request

- List/create/open projects (the shell still performs the native dialog; it passes the path).
- Read domain objects for the workspaces in [PRODUCT_ARCHITECTURE.md](PRODUCT_ARCHITECTURE.md).
- Edit participants, layout bindings, protected regions, text revisions, manual shot overrides.
- Start, cancel, and resume jobs.
- Set provider **references** and task routing. Secrets are written by the shell into the OS store; the UI never receives the secret back, only “configured”.

## What the UI must not do

- Compute speaker alignment, turns, or crops.
- Persist authority in localStorage that overrides `project.sqlite`.
- Call OpenAI or any provider directly. Provider calls go through the engine so provenance and mode policy stay in one place.

## Settings workspace data

Global: mode, provider configs (no secrets), model install state, default encoder preferences.

Project: language hint, active runs, participant list, layout confirmation status.

## Packaging boundary

The shell binary, the web assets, the Python runtime, and FFmpeg ship together. Models do not. See [MODEL_DISTRIBUTION.md](MODEL_DISTRIBUTION.md).

## Security notes that are in scope

- Loopback plus token.
- No secrets in project files.
- Engine file access confined to app support, the open project, and user-selected paths passed in by the shell.
- Logs redact credential headers and provider request bodies that might echo keys.

Cloud account login, license servers, and multi-user auth are out of scope.
