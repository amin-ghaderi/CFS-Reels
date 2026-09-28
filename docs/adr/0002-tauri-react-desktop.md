# ADR 0002: Tauri and React desktop

## Context

AMIX must be an installable Windows and macOS application. The editorial UI is a separate concern from media processing.

## Decision

The shell is Tauri 2. The UI is React and TypeScript. Rust does not implement transcription, directing, or AI calls. The UI does not call FFmpeg or providers itself.

## Consequences

- Native dialogs, sidecar lifecycle, and OS credential access sit in the shell.
- A web-only build is not a V1 target.
- Packaging must ship the sidecar beside the shell (see ADR 0003 and model distribution).

## Status

Accepted
