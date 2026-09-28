# Model distribution

The application installer and the large models are different artifacts.

## Installer contains

- Tauri desktop binary and web UI
- Python 3.12 runtime and the AMIX engine (sidecar)
- FFmpeg and ffprobe builds approved for redistribution
- Small non-ML assets required to boot (YuNet ONNX only if its license allows bundling; otherwise it is a first-run download like other models)

The installer does not contain Whisper weights, LLM weights, or the user’s media.

The user does not install Python, FFmpeg, Node, Rust, or a CUDA toolkit as a separate product step. GPU use, when available, uses libraries bundled with the sidecar or a documented optional accelerator pack. CPU execution must work for transcription on a modest machine, even if it is slow. V1 does not promise real-time on every CPU.

## Model manager

A global catalog in the application database. Files live under the app models directory or a user-chosen directory.

Metadata for each definition:

| Field | Role |
|---|---|
| `id` | Stable id, not a filename |
| `display_name` | UI |
| `provider` | `local` or a cloud provider id |
| `runtime` | `faster-whisper` / `ctranslate2`, `llama.cpp`, `remote-api`, … |
| `license` | SPDX id or a short license name the UI can show |
| `version` | Model version |
| `size_bytes` | Expected size |
| `hash` | Expected file hash |
| `download_source` | URL or catalog key. Not embedded in project files as a secret |
| `local_path` | Relative to the models root once installed |
| `capabilities` | From the AI capability list, plus `TRANSCRIBE` for ASR models |
| `hardware_requirements` | Minimum RAM, notes on GPU. Advisory |
| `redistributable` | Whether AMIX may ship the bytes in an installer |
| `bundled` | True only if this build actually includes the bytes |
| `download_on_demand` | True for large weights |

Cloud models have `local_path` empty, `download_on_demand` false, and `size_bytes` null. They still have id, version, and capabilities so a run can record what was called.

## Download behavior

- User action or a task that needs a missing local model opens the manager. No background download of multi-gigabyte files on first launch without a prompt.
- Verify hash before the model is marked installed.
- Jobs that need a missing model fail with `model_missing`, not a cloud substitute, unless the active mode and task fallback already allow a different provider.

## What is not selected here

Final Whisper size, the default local LLM, and which cloud models appear in the catalog. Those choices wait for licensing, size, and quality checks. The schema above is enough to add them without a storage redesign.

## Packaging by OS

### Windows

- Installer (exact format later: MSI or per-user installer) places the app under a per-user or per-machine directory.
- Sidecar and FFmpeg sit beside the app or in a versioned resources directory.
- Code signing of the installer and binaries is required before public release. Certificate vendor is not chosen in this document.
- Auto-update replaces the app bundle and sidecar. It does not delete `%APPDATA%/AMIX/models` or project directories.

### macOS

- Signed `.app` in a signed disk image or notarized installer.
- Notarization required for distribution outside a developer machine.
- Sidecar and FFmpeg live inside the app bundle so Gatekeeper sees one signed tree. Hardened runtime entitlements must allow the sidecar to execute and to read the user-selected project directory.
- Keychain access for credentials is requested by the signed app.
- Auto-update replaces the `.app`. Models stay in Application Support.

## Auto-update

Update the application and engine together so schema migrations and the sidecar match. Model files update only when the user installs a new model version. An app update that needs a newer algorithm records that old cached artifacts remain valid to **read** and invalid to **reuse** when `algorithm_version` changes.

## License display

The settings workspace can list third-party licenses (FFmpeg build flags, Whisper weights, YuNet, llama.cpp). This document does not choose a build of FFmpeg (GPL versus LGPL). That choice is a release decision because it changes redistribution obligations. The architecture only requires the chosen build to be invocable as `ffmpeg`/`ffprobe` by the sidecar via a bundled path, not via `PATH`.
