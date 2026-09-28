# ADR 0010: Per-project provenance

## Context

Legacy outputs are chosen by filename (`v2`, `v3`, `final`, `resolved`). A later user cannot tell which model, config, or parent run is active, or whether a human edited the result.

## Decision

Every derived result belongs to an `AnalysisRun` recording source asset, input artifacts, algorithm version, config hash, local versus cloud, provider and model when used, time, and output hash. The project row stores the active run id per kind. Manual edits are successor revisions with `manual_modification`. Filenames are not authority.

## Consequences

- Old runs remain readable after a newer run is activated.
- Cache keys include config and version, so a retuned overlap detector does not reuse stale regions.
- The UI must show which run is active instead of implying “the file we found”.

## Status

Accepted
