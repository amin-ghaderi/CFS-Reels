# ADR 0006: Local-first, cloud optional

## Context

Core value is processing the user’s masters on their machine. Cloud models can improve wording and editorial choices. They must not become a hidden dependency.

## Decision

Probe, proxy, transcribe, diarize, align, turns, overlap, shot planning, and render are local. Modes are private/offline, hybrid, best quality, and custom. Cloud runs only for semantic tasks whose mode and task policy allow it. Offline mode never falls through to a network call.

## Consequences

- The app is usable with no API key.
- Semantic features degrade explicitly (`skipped_no_provider` or heuristic fallback).
- Privacy of the master file does not depend on a cloud account.

## Status

Accepted
