# Settings and resources

Resource, model, and provider configuration is global application state. It is not stored in `project.sqlite`. A project stays portable: it does not embed a machine path or an API secret. Copied to another machine, it can report resources unavailable until that machine has its own global resources.

## App data

The desktop resolves the OS application-data directory through Tauri (`app_data_dir` for the current bundle identifier) and passes it to the engine as `--app-data`. Python does not guess that path. Tests pass an explicit directory. There is no hardcoded user-profile path.

Under that directory:

- `app.sqlite` — non-secret global state
- `models/` — AMIX-owned installs
- `resources/`
- `logs/`

## Global database

A separate Alembic environment, `amix/alembic_app.ini`, owns this database. The project migration chain is not used. Revision `0001_app_state` creates the tables. Revision `0002_local_semantic` adds the managed-local columns.

- `app_setting` — one row: network policy, selected speech, vision, llama.cpp runtime, and GGUF model, semantic source, local context and threads, selected provider, speech device and compute type, FFmpeg directory
- `resource_installation` — registered or managed resources, including optional architecture and semantic compatibility
- `provider_configuration` — provider rows and a non-secret `credential_ref`
- `resource_job` — install/download jobs that must run when no project is open

No column stores an API key, token, or password. Existing projects do not need a project migration because of this database.

`resource_job` reuses the project job status words and cancellation rules. It is not a second editorial job system. The project `JobManager` requires an open project, so a global install cannot use it.

## Settings

Settings is reachable from the start screen and from an open project. It does not require a project. Sections are General / Privacy, Speech, Vision, Semantic AI, and Media tools.

Speech, vision, provider, network, and FFmpeg settings are read on each resolve. They apply to the next job without an engine restart. The status field `restart_required` is false for these settings. A future setting that needs a restart must say so and must not reuse a project handle after the engine generation changes.

## Resource status

Product status values are `NOT_CONFIGURED`, `VALIDATING`, `READY`, `INVALID`, `MISSING`, `VERSION_UNSUPPORTED`, `INSTALLING`, and `FAILED`. The desktop uses those sentences. It does not show a stack trace as the normal state.

A resource row has an id, kind, display name, version when known, managed or registered ownership, origin, license name and URL when supplied, a lightweight identity, runtime, and status. The filename is not the identity. Runtime status omits filesystem paths.

## Speech

Import Local Speech Model uses the native folder picker. The folder must contain `model.bin` and at least one of `config.json`, `tokenizer.json`, `vocabulary.txt`, or `preprocessor_config.json`.

V1 import is register-in-place. AMIX does not copy the folder. Remove unregisters it and does not delete the user's files. One selected compatible model is the default. The screen shows name, runtime, identity or version when present, device, and compute type. The saved default is CPU and int8. There is no GPU auto-detection.

Resolution order:

1. `AMIX_STT_MODEL_PATH` when set and not blank. Invalid does not fall through.
2. The selected global speech resource.
3. Unavailable.

Transcription jobs still receive a `SpeechModelDescriptor`. They do not open `app.sqlite`.

## Vision

Import YuNet Model uses the native file picker. Import initializes OpenCV `FaceDetectorYN` on the file. The selected file is the vision resource. Resolve builds the existing `VisionModelDescriptor`, including the existing file identity. Overlap thresholds are unchanged.

Resolution order:

1. `AMIX_YUNET_MODEL_PATH` when set and not blank. Invalid does not fall through.
2. The selected global vision resource.
3. Unavailable.

## Semantic providers

Settings separates three sources:

- Managed local model. AMIX imports a llama.cpp server program and a GGUF file, then starts that server itself.
- External local provider. A loopback OpenAI-compatible server the user already runs (llama.cpp, LM Studio, or another compatible server).
- Remote provider. A saved remote OpenAI-compatible endpoint and its OS credential.

A local provider must be loopback (`127.0.0.1`, `localhost`, or `::1`). A LAN address is remote. Saving a remote URL does not switch the network policy. Managed local settings are not API keys.

Test Connection for an external or remote provider uses `GET {base}/models`. It does not send a project transcript. Start / Test on the managed local model starts the local server and waits until it is ready. AMIX does not poll remote providers.

Resolution order:

1. `AMIX_AI_BASE_URL` and `AMIX_AI_MODEL` when either is set. Both are required. An incomplete or invalid override does not fall through. The development key is `AMIX_AI_API_KEY` only.
2. The managed local model, when that source is selected. A failed start does not fall through to a saved provider.
3. The selected saved provider. Its secret, if any, comes from engine memory filled by the desktop.
4. Unavailable.

## Managed local model

Import llama.cpp program, or a folder that contains `llama-server` / `llama-server.exe`. AMIX runs `--version` (then help if needed) with `shell=False`, a short timeout, and bounded output. A filename is not enough.

Import local GGUF model registers the file in place. AMIX checks that it is a regular file with a GGUF header. It records size, GGUF version when the header parses, and architecture when that metadata key parses. It does not guess parameter count, quantization, license, or context length from the filename. License stays unknown unless the import supplies one AMIX can store as given. Semantic compatibility starts as `unknown`. It becomes `validated` or `incompatible` only from a later explicit result, not from the model name.

The selected runtime, selected model, optional context size (256–131072), and optional thread count (1–64) are saved in `app.sqlite`. A blank context uses 16384. That is large enough for one AMIX semantic chunk and small enough that a model whose own context is very large does not allocate that cache on a normal computer. A blank thread count leaves the runtime's CPU default. There is no free-form argument field and no GPU-layer control in this phase.

Start / Test, or the first Conversation Map or Reel Discovery that needs the model, starts `llama-server` on `127.0.0.1` and an application-chosen free port. The port is not saved and is not the model identity. Readiness is `GET /v1/models`. States are STARTING, LOADING, READY, FAILED, and STOPPED. They are runtime status, not project jobs. Load timeout is 180 seconds. Stop Local AI stops the process. Engine shutdown stops it as well. Quit and restart keeps the registered files and the selection; the server is not left running.

The managed server is an owned child: spawn and registration happen together, stop ends the process tree, and a second start uses a new process and a new port. Conversation Mapping and Reel Discovery still request `GENERATE_STRUCTURED` through the existing provider. They do not receive an executable path or a GGUF path.

Managed local inference is offline-safe. It does not download a model, look up a license, send telemetry, or fall back to a remote provider.

Application tasks still consume a provider descriptor. They do not persist a provider per project. AnalysisRun provenance records the non-secret descriptor used for that run.

## Network policy

Settings offers Offline and Network enabled. Offline is the default. Offline refuses a non-loopback provider before a request is sent. Network enabled is an explicit saved choice. It permits a configured remote provider. `AMIX_AI_NETWORK=development` remains a development alias that permits remote use. A set value outside `offline`, `network_enabled`, and `development` is invalid and does not fall through.

## Credentials

The desktop writes secrets with the OS credential store (Windows Credential Manager, macOS Keychain) through the Rust `keyring` boundary. The global row stores `credential_ref` only. React shows "API key configured" or "No API key". It cannot read the secret. Generic engine requests have secret-shaped fields removed and cannot set the credential-write header. The desktop pushes a stored secret into engine memory after the engine is ready and when the user saves or replaces a key. Engine memory is not written to jobs, provenance, or logs. Remove credential deletes the OS entry and the memory copy.

Tests use an in-memory vault. They do not require Credential Manager or Keychain.

## Media tools

Media tools show FFmpeg and FFprobe as READY, MISSING, or INVALID, with a version when the tool answers. Choose FFmpeg Folder validates both programs in that directory and saves the directory. Jobs do not accept an executable path from the desktop UI.

Resolution order:

1. `AMIX_FFMPEG` / `AMIX_FFPROBE` when set. Invalid does not fall through.
2. The saved directory when configured. Both binaries are required. Invalid does not fall through.
3. `amix/tools/` when both binaries are present.
4. PATH.

Configuring a user-supplied FFmpeg does not choose a production redistribution build or license. AMIX does not bundle FFmpeg in this phase.

## Local import and managed download

Local import works with no network. Register-in-place resources are not copied.

Managed download is manifest-only. The catalog is application-defined. React cannot submit a URL. A catalog entry has a resource id, kind, display name, version, download source, SHA-256 checksum, optional size, license metadata, and runtime compatibility. The current catalog is empty because no source, license, checksum, and format were already established together. An empty catalog is intentional.

A download, when a catalog entry exists, is a global background job. Bytes land in an app-owned temporary directory. They are installed only after the download completes, the SHA-256 matches, and resource validation succeeds. Cancellation stops the transfer, deletes the partial files, and does not register a resource. Automated tests use a local test server, not the public network.

## Removal

Remove of a register-in-place resource unregisters it and leaves the user's files. Remove of an AMIX-owned resource deletes those bytes only after confirmation, and only when the path is inside the app-data directory. The selected speech resource cannot be removed while a transcribe job is queued, running, or cancel-requested. The selected vision resource cannot be removed while overlap detection is in those states. A llama.cpp runtime or GGUF model cannot be removed while local AI is starting, loading, or ready.

## Portability

Projects do not move with global resources. Another machine configures its own speech model, YuNet file, llama.cpp runtime, GGUF model, provider, and FFmpeg folder. Development environment variables remain supported and stay higher priority than saved settings. They are not the normal product path.
