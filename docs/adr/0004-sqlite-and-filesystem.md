# ADR 0004: SQLite and filesystem

## Context

AMIX needs durable project state, global settings, and large media. A server database is unnecessary for a single-user local app.

## Decision

SQLite stores structured data: one global application database and one database per project. Files hold media, proxies, caches, and large artifacts. Alembic migrates schema when implementation starts. SQLAlchemy is the intended access layer. Neither is initialized in the architecture phase.

## Consequences

- Projects are copyable directories.
- There is no V1 multi-user database server.
- Schema version is explicit in `manifest.json` and the database.

## Status

Accepted
