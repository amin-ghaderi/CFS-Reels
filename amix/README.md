# AMIX

AMIX is a local-first, cross-platform intelligent video editing platform for
long-form conversational video.

Current status: Phase 9 local transcription, on top of the Phase 8 proxy
playback and transcript sync, the Phase 7 media runtime, the Phase 6 media and
transcript workspace, the Phase 5 desktop shell, the Phase 4 local engine
service, the Phase 3 project store, and the Phase 2 deterministic engine.

`amix_engine` imports the CFS03 49–59 minute fixture and recomputes word
assignments, speaking turns, overlap regions (from saved lip activity, not
from video), and an automatic 16:9 shot plan. Time is integer microseconds
on the source timeline.

The same engine can create a project directory, migrate `project.sqlite`
with Alembic, and store media metadata, participants, layout bindings,
transcripts, immutable analysis runs, and the active result for each media
asset. Human word-text corrections are an overlay. Media files stay outside
the database. See [docs/STORAGE.md](docs/STORAGE.md).

A local FastAPI service on `127.0.0.1` opens those projects and runs in-process
jobs. See [docs/ENGINE_SERVICE.md](docs/ENGINE_SERVICE.md). The desktop shell
in `apps/desktop` starts that service. See [docs/DESKTOP_FOUNDATION.md](docs/DESKTOP_FOUNDATION.md).
The Media and Transcript workspaces are described in
[docs/MEDIA_TRANSCRIPT_WORKSPACE.md](docs/MEDIA_TRANSCRIPT_WORKSPACE.md).
Probe and preview proxies are described in
[docs/MEDIA_RUNTIME.md](docs/MEDIA_RUNTIME.md).
Proxy playback and transcript sync are described in
[docs/PLAYBACK.md](docs/PLAYBACK.md).
Local transcription is described in
[docs/TRANSCRIPTION_RUNTIME.md](docs/TRANSCRIPTION_RUNTIME.md).

```
amix/.venv/Scripts/python -m amix.amix_engine.service
```

## Desktop development

From `amix/apps/desktop`, after the Python environment above exists:

```
npm install
npm test
npm run tauri dev
```

`npm run build` typechecks and builds the frontend. Rust tests are `cargo test` in `amix/apps/desktop/src-tauri`. The desktop looks for `amix/.venv` and does not use another Python.

## Development environment

The repository root `.venv` is the legacy environment. Do not install AMIX
packages into it.

From the repository root, with Python 3.12:

```
py -3.12 -m venv amix/.venv
amix/.venv/Scripts/python -m pip install -e "amix[test]"
```

On macOS or Linux, use `amix/.venv/bin/python` instead of
`amix/.venv/Scripts/python`.

`amix/.venv/` is gitignored.

FFmpeg and ffprobe are external development tools. AMIX does not download or
bundle them. Set `AMIX_FFMPEG` and `AMIX_FFPROBE`, or place both binaries in
`amix/tools/`, or have them on `PATH`. See
[docs/MEDIA_RUNTIME.md](docs/MEDIA_RUNTIME.md). `amix/tools/` is gitignored.

Speech models are not downloaded by AMIX and are not stored in this repository.
For local transcription during development, set `AMIX_STT_MODEL_PATH` to an
existing CTranslate2 / faster-whisper directory that already contains
`model.bin`. Optional settings are `AMIX_STT_MODEL_ID`,
`AMIX_STT_MODEL_VERSION`, `AMIX_STT_DEVICE` (`cpu` by default; `cuda` only
when set), and `AMIX_STT_COMPUTE_TYPE` (`int8` by default). A missing or
invalid path fails the job. It does not fall back to a remote model. See
[docs/TRANSCRIPTION_RUNTIME.md](docs/TRANSCRIPTION_RUNTIME.md).

## Tests

From the repository root:

```
amix/.venv/Scripts/python -m unittest discover -s amix/tests -p "test_*.py" -t .
```

Creating or opening a project applies Alembic migrations. There is no
separate migration step for tests.

The core suite does not use the network, the source video, FFmpeg, a speech
model, or OpenCV. It does not download weights. A real-model transcription
check runs only when `AMIX_STT_MODEL_PATH` already points at a local model
directory.

## Not implemented yet

Rendering, diarization from audio, face detection,
cloud or local LLM providers, Reel editing, conversation maps, and the global
application database.
