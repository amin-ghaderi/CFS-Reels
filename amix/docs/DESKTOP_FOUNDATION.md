# AMIX desktop foundation

Phase 5 is the first desktop shell. It launches the Phase 4 engine, opens a project, and runs the existing project integrity job. It does not edit media.

## Stack

- Tauri 2
- React 19
- TypeScript
- Vite 6

The application lives in `amix/apps/desktop/`. Python stays in `amix/amix_engine/`. There is no Electron app and no frontend web server in production. Vite is only the development bundler.

The window identifier `local.amix.desktop.dev` in `src-tauri/tauri.conf.json` is provisional. It is not a published bundle id.

## Prerequisites

From the repository root, the Phase 4 environment must already exist:

```
py -3.12 -m venv amix/.venv
amix/.venv/Scripts/python -m pip install -e "amix[test]"
```

On macOS or Linux the interpreter is `amix/.venv/bin/python`.

Also install a current Node.js, npm, and a Rust toolchain that can build Tauri 2.

## Commands

From `amix/apps/desktop`:

```
npm install
npm test
npm run build
```

`npm test` runs Vitest on the frontend helpers. `npm run build` typechecks and writes the production bundle to `dist/`.

Tauri, from `amix/apps/desktop`:

```
npm run tauri dev
npm run tauri build
```

`tauri dev` starts Vite on `127.0.0.1:1420` and opens the window. `tauri build` is not a release installer in this phase: bundling is disabled.

Rust checks, from `amix/apps/desktop/src-tauri`:

```
cargo test
cargo check
```

## Engine launch

The desktop process owns the engine. On startup, Rust starts the development interpreter and reads the first non-empty stdout line. That line must be the Phase 4 ready record:

```
{"event":"amix.engine.ready","host":"127.0.0.1","port":54321,"token":"..."}
```

A log line before that record is a failed start. Engine logs stay on stderr. The desktop does not scrape them for the port or the token.

The development command is resolved in one module, `src-tauri/src/launch.rs`:

- walk upward from the working directory and the executable until `amix/pyproject.toml` and `amix/amix_engine/service/__main__.py` are both present
- Windows interpreter: `amix/.venv/Scripts/python.exe`
- macOS and Linux interpreter: `amix/.venv/bin/python`
- arguments: `-m amix.amix_engine.service`
- `AMIX_HOST=127.0.0.1`, `AMIX_PORT=0`, and any inherited `AMIX_SESSION_TOKEN` removed

If that interpreter is missing, the window shows Engine unavailable and Retry engine. AMIX does not fall back to another Python.

Connection states are `STARTING`, `READY`, `FAILED`, and `STOPPED`. Project actions stay hidden until `READY`.

## Desktop session

Rust is authoritative for the process-lifetime engine and project session. That state stays in memory. It is not written to disk, `localStorage`, or `project.sqlite`.

Each Python process that reaches ready is one engine generation. A project handle belongs to that generation only. The snapshot (`desktop_session_snapshot`, and the `amix-session` event) carries the generation, engine phase, and the open project if there is one. It never carries the session token.

On launch, and after a WebView reload, React hydrates from that snapshot. If this desktop process already has a project open, the screen restores it. React does not call project-open again.

If the owned Python process exits unexpectedly, Rust marks the engine failed, drops the project session for that generation, and emits the snapshot. The old handle is not sent to the next process. Retry Engine starts a new generation and asks the user to reopen the project. A normal application exit increments the generation before the process is stopped, so that stop is not reported as a crash.

A project close that returns `project_close_timeout` leaves the Rust project session in place. The engine still holds the lock.

## Engine requests

`engine_request` is an async Tauri command. The blocking `ureq` call runs on a worker, so a slow engine response does not freeze the window. Connect timeout is 3 seconds. Health reads use 5 seconds, ordinary reads 15 seconds, and project close 8 seconds.

Job progress still uses REST polling. The session event is only for engine and project lifetime, not for job progress.

## Shutdown

On exit the shell closes the current project through `POST /v1/projects/{handle}/close` when it still has a handle, then terminates the engine process. The close call has a few seconds to finish. The process is then stopped so the operating-system project lock is released. A new engine start also stops the previous process first.

On Windows the virtualenv `python.exe` is a redirector that starts the base interpreter as a child process. Shutdown kills that process tree, so both processes exit. On macOS and Linux the engine is started in its own process group and stopped with that group.

## Security boundary

The Phase 4 engine does not enable CORS. The webview does not call it with `fetch`.

React asks Rust to perform the request (`engine_request`). Rust allows only `GET` and `POST` to `http://127.0.0.1:<ready-port>/v1/...`, with no query string, fragment, or `..`. The session token stays in the Rust process. It is attached as `Authorization: Bearer` there. It is not stored in `localStorage`, IndexedDB, project files, or the status UI. Development diagnostics may show host, port, version, and connection state. They are omitted from the production bundle and never show the token.

The content security policy allows local scripts and the Vite development socket. It does not load remote JavaScript, fonts, or stylesheets. The interface uses system fonts.

Rust does not own editorial rules, speakers, timelines, reels, or the project database.

## Project and job UI

With no project open, the start screen offers Create project and Open project. Both use the native folder dialog. Create asks for a name, joins it to the selected parent with the OS path API, and calls `POST /v1/projects/create`. Open calls `POST /v1/projects/open`. Close calls the engine close route and returns to the start screen. There is no recent-project list.

The shell has a header, workspace navigation, an empty workspace, a job inspector, and a status bar. Media, Transcript, Conversation, Multicam, Reels, and Export are labeled "Not implemented yet".

The only job action is `project_integrity_check`. Progress stays in basis points in the engine. The UI displays `progress_bp / 100` as a percent. Jobs are polled about once a second while a project is open and at least one job is non-terminal. Retry adds a new job row.

Stable engine error codes are mapped to short sentences. Job rows show that sentence. A development build can also show the raw engine text inside the job's details. The alert details show the stable code.

## Tests

- Rust: ready-record parsing, path joins, the loopback URL allowlist, session generation and crash recovery, a non-blocking request check, and a development lifecycle test that creates a project, runs the integrity job, closes it, stops the process, and checks that the project lock can be taken again.
- Vitest: error-code mapping and progress/cancel/retry helpers.

The Python suite is unchanged.

## Not in this phase

Transcript editing, timeline, waveform, multicam, reels, semantic models, Whisper, playback, FFmpeg, model management, ingest, export, cloud sync, installers, code signing, notarization, and auto-update.

## Later packaged engine

`launch.rs` is the only place that knows about `amix/.venv`. A later phase can replace that development command with a packaged `amix-engine` executable. The ready-record parser, the loopback request allowlist, and the webview stay the same. This phase does not run PyInstaller or Nuitka.
