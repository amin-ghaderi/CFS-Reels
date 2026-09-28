# ADR 0012: Large media outside the database

## Context

Masters, proxies, audio extracts, and renders are gigabytes. SQLite is the right store for words, shots, and run metadata. Putting video blobs in SQLite would break portability and backup.

## Decision

Video, audio, proxies, and other large artifacts live on the filesystem. The project database stores paths, hashes, sizes, and foreign keys. External masters are allowed and become `missing` if the path or hash fails. Relink updates the path only.

## Consequences

- A project folder can move without rewriting times.
- Backup is “copy the project directory plus any external masters”.
- The engine does not offer a blob column for picture.

## Status

Accepted
