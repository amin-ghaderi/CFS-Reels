# Project storage

Phase 3 persists one project in a folder. The Python engine is the only writer.
There is no UI in this phase, and the future React shell does not open
`project.sqlite` itself.

## Layout

```
<Project>/
  project.sqlite
  manifest.json
  project.lock          # OS write lock, one byte
  project.lock.json     # pid, hostname, opened_at — not the lock
  media/
  proxy/
  cache/
  artifacts/
  exports/
  logs/
```

`proxy/` matches the architecture tree. Media bytes stay in those directories
or outside the project. SQLite has no binary column for picture or audio.

## Schema

Alembic revision `0001_project` is the schema. `create_all()` is not used.

`manifest.json` carries `project_schema_version` (currently `1`) because the
architecture requires a project format marker. That integer is a compatibility
gate. It is not a second migration counter and it does not upgrade tables.

The global application database (`app.sqlite`) is not created yet.

## Identities

Project, media, and analysis-run ids are UUID strings. Participant ids and
word ids are supplied by the caller so a fixture or a later export can keep
them. Display names are not part of an id.

## Time

Media and editorial times are integer microseconds. `created_at` is a UTC
wall-clock string and is not a media time.

## SQLite pragmas

| Pragma | Value | Why |
|---|---|---|
| `foreign_keys` | `ON` | SQLite leaves foreign keys off unless every connection enables them. |
| `busy_timeout` | `5000` | A short wait if the file is briefly busy. |
| `journal_mode` | `DELETE` | One writer. WAL's `-wal` and `-shm` files are a poor fit for a project folder that may sit in a synced directory. |
| `synchronous` | `FULL` | A commit is durable for that single writer after a crash. |
| `query_only` | `ON` when read-only | A read-only open does not take the project write lock and does not migrate. |

Synced multi-machine editing of one project is not supported. This engine does
not detect OneDrive, iCloud, or Dropbox, and it does not copy the database
before a migration.

## Write lock

`project.lock` is locked with `msvcrt.locking` on Windows and `flock` on
macOS. The lock is the open handle. `project.lock.json` is only a note. After
the process exits, a leftover note does not block the next open.

A second writable open on the same machine fails with `ProjectAlreadyLocked`.
A read-only open does not take that lock. Two machines writing one synced
folder is still unsafe and is not detected here.

## Active results and corrections

An active pointer is `(media_asset_id, analysis_kind) → analysis_run`. It is
not a field on the project. Changing it does not delete the previous run.
The stored kind for word-to-participant assignment is `participant_assignment`.
The domain object remains `SpeakerAssignment`.
The foreign key requires the run to belong to that asset and kind.

Generated rows are inserted for a new run. A rerun does not update the old
run. Manual word text and speaker overrides live in `manual_correction`.
They do not change `word.text` or `participant_assignment`. A correction whose
word is absent from a transcript is reported as inapplicable. This phase does
not guess a new target.

## Cascades

Foreign keys are `ON DELETE RESTRICT`. A normal rerun is an insert plus an
active-pointer update, not a delete.
