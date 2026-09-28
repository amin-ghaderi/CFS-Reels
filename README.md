# CFS-Reels repository

This repository has two deliberately separate application areas:

- `legacy/` — historical working CFS/Reels R&D system. Used as migration reference.
- `amix/` — the new production application: **AMIX**.
- `docs/` — shared AMIX architecture and legacy migration documentation.

New product development happens in `amix/`. Do not add new product features to `legacy/`. Legacy capabilities should be understood and migrated individually; the legacy application must not be copied wholesale into AMIX.
