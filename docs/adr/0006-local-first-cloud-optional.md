# ADR 0006: Local-first, cloud optional

## Context

Core value is processing the user’s masters on their machine. Cloud models can improve wording and editorial choices. They must not become a hidden dependency.

## Decision

Probe, proxy, transcribe, diarize, align, turns, overlap, shot planning, and render are local. Modes are private/offline, hybrid, best quality, and custom. Cloud runs only for semantic tasks whose mode and task policy allow it.

Offline mode is a hard no-network guarantee, enforced by the engine, not by a label on a provider. A missing local model or runtime file (including weights the legacy stack downloaded on first use, such as Whisper and YuNet) ends the job as a missing resource. Offline mode does not start a download and does not substitute a cloud call.

## Consequences

- The app is usable with no API key, once the local weights it needs are already present.
- Semantic features degrade explicitly (`skipped_no_provider` or heuristic fallback).
- Privacy of the master file does not depend on a cloud account.

## Status

Accepted
