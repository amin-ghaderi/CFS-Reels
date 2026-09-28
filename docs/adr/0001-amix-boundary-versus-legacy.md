# ADR 0001: AMIX product boundary versus legacy

## Context

The repository contains a working CFS/Reels R&D system and a new product scaffold. The R&D system encodes real media behavior and also one-off scripts, superseded speaker stacks, and Cursor-specific calls.

## Decision

`legacy/` stays the historical reference and is not the product. AMIX development happens only in `amix/`. Capabilities move one at a time according to [MIGRATION_MAP.md](../architecture/MIGRATION_MAP.md). Legacy identifiers (CFS03, CFS-Reels, existing artifact names) stay in legacy.

## Consequences

- No wholesale copy of `reels_factory` into the engine.
- Proven 16:9 behavior is specified, then reimplemented or adapted against golden tests.
- Superseded speaker code and visual-hook experiments are not ported as product structure.

## Status

Accepted
