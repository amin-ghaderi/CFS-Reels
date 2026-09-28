# AMIX

AMIX is a local-first, cross-platform intelligent video editing platform for
long-form conversational video.

Current status: Phase 6 media and transcript workspace, on top of the Phase 5
desktop shell, the Phase 4 local engine service, the Phase 3 project store,
and the Phase 2 deterministic engine.

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

## Tests

From the repository root:

```
amix/.venv/Scripts/python -m unittest discover -s amix/tests -p "test_*.py" -t .
```

Creating or opening a project applies Alembic migrations. There is no
separate migration step for tests.

The suite does not use the network, the source video, FFmpeg, Whisper, or OpenCV.

## Not implemented yet

Rendering, transcription, diarization from audio, face detection,
cloud or local LLM providers, Reel editing, conversation maps, and the global
application database.
