# CFS-Reels repository

This repository has two deliberately separate application areas:

- `legacy/` — the existing working CFS/Reels R&D implementation. Preserve its behavior and use it as reference material for capability-by-capability migration.
- `studio/` — the new production-grade CFS Studio product area. All new product development belongs here.
- `docs/` — shared architecture and migration documentation.

Do not add new product features inside `legacy/`. Legacy capabilities should be understood and migrated individually; the legacy application must not be copied wholesale into Studio.
