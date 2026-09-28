# ADR 0003: Python local engine

## Context

Proven media code is Python (faster-whisper, OpenCV, FFmpeg orchestration). Rewriting that stack in Rust or TypeScript during the architecture phase would throw away the reference behavior.

## Decision

The local engine is Python 3.12. FastAPI on loopback is the IPC boundary to the UI. Pydantic is the schema layer when implementation starts. Domain rules, pipeline stages, and SQLite access live in this process.

## Consequences

- The installer bundles a Python runtime. Users do not install Python.
- The engine is a sidecar the shell starts and stops.
- FastAPI is an in-app boundary, not a public service.

## Status

Accepted
