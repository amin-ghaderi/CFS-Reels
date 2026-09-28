# Storage architecture

## Split

| Store | Holds | Does not hold |
|---|---|---|
| Global application database (SQLite) | Settings, recent projects, provider registry, model catalog, UI preferences that are not project editorial state | Project words, shots, media bytes, API keys |
| OS credential store | Provider secrets | Anything queryable as project data |
| Per-project SQLite | Structured project state in [DOMAIN_MODEL.md](DOMAIN_MODEL.md) | Video, WAV, proxies, large intermediate matrices |
| Project filesystem | Masters (or links), proxies, cache, extracts, large JSON/NPY artifacts, exports, job logs | A second copy of authority that contradicts SQLite |

ADR: [0004-sqlite-and-filesystem.md](../adr/0004-sqlite-and-filesystem.md), [0012-large-media-outside-database.md](../adr/0012-large-media-outside-database.md).

## Locations

Application data (not the git repo):

- Windows: `%APPDATA%/AMIX/app.sqlite` and `%APPDATA%/AMIX/models/`
- macOS: `~/Library/Application Support/AMIX/app.sqlite` and `models/`

Exact company-relative path prefixes stay unset until a bundle identifier exists. The architecture only requires a per-user writable app support directory.

A project is a directory:

```
<ProjectName>.amix/
  project.sqlite
  manifest.json          # schema version, project_id, created by app version
  media/                 # optional local copies
  proxy/
  cache/
  artifacts/             # large stage outputs, content-addressed where practical
  exports/
  logs/
```

The user may keep the master **outside** this folder. `MediaAsset.path` is then relative to the project if the file lives inside it, or an external path plus hash if it does not.

## Relative paths and relocation

Inside the project directory, store POSIX-style relative paths (`proxy/master_720.mp4`). Resolve them against the project root at runtime so a moved folder still works.

External media stores:

- absolute path last known
- content hash (SHA-256 of the file, or a fast hash plus size if full hashing is too slow — the choice is recorded on the asset)
- byte size, duration, container

On open, if the path is missing or the hash mismatches, the asset state is `missing` or `changed`. The project still opens. Stages that need the file refuse to run until the user relinks. Relink updates the path and re-verifies the hash. It does not rewrite word times.

Copying a project folder to another disk is the portable unit. External masters are not inside that copy unless the user chose “copy media into project”. The destination shows missing media until relink. That is the backup story for V1: copy the `.amix` directory, and copy external media separately. There is no cloud backup protocol in V1.

## Project versioning

`manifest.json` carries `project_schema_version`. Alembic migrates `project.sqlite` forward. The app does not silently open a newer schema than it knows.

Editorial history is analysis runs and revisions, not git inside the project. A user-visible “duplicate project” copies the folder. V1 does not implement branching timelines.

Active pointers in `project.sqlite` are the only authority. Artifact files are payloads addressed by hash and run id.

## Large artifacts

Diarization features, lip-activity series, and full render intermediates stay as files under `cache/` or `artifacts/`. The database stores the path, hash, byte size, and `analysis_run_id`.

SQLite may store word rows and shot rows. Those are structured and small next to picture. A multi-hour word table is acceptable. A multi-hour video is not.

## Cache keys

A stage cache key is a hash of:

- input artifact hashes
- algorithm id and version
- config snapshot
- model id and version when a model is an input

A hit reuses the output hash and marks the job `cache_hit`. Changing a threshold does not reuse the old overlap file.

## Secrets

`ProviderConfiguration.credential_ref` is an opaque key.

- Windows: Credential Manager (or the current user credential vault Tauri can access).
- macOS: Keychain.

The Python engine receives a secret only in memory for the duration of a cloud call, supplied by the shell or by a small local unlock. It does not write the secret into `project.sqlite`, `app.sqlite`, logs, or prompts saved on disk.

Projects are safe to zip and send without exporting the user’s API keys.

## Global versus project models

Installed model files live under application support (or a user-chosen models directory in settings). Projects reference `model_id` and version. Deleting a project does not delete a shared model. Deleting a model marks runs that used it as still readable; it does not rewrite history.

## What backup must include

To reproduce a result: `project.sqlite`, `manifest.json`, artifact files referenced by active runs, and the master bytes (inside `media/` or relinked). Application models must match the recorded version if a stage is re-run. Existing outputs remain valid without the model if their hashes are intact.
