# ADR 0011: Local model manager

## Context

Whisper weights and future local LLMs are large, licensed separately from the app, and change on a different schedule from the installer. End users must not install a Python ML stack by hand.

## Decision

The installer ships the desktop shell, Python sidecar, and FFmpeg. A global model catalog stores id, display name, provider, runtime, license, version, size, hash, download source, local path, capabilities, hardware notes, and whether the model is redistributable, bundled, or downloaded on demand. Downloads are user-visible and hash-checked. Cloud models are catalog entries without local files.

## Consequences

- First launch does not silently fetch multi-gigabyte weights.
- Projects record the model id they used; deleting a project does not delete shared weights.
- Final model choices are not made in this ADR.

## Status

Accepted
