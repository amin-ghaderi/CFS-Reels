# Local engine service

The engine process is the local IPC boundary for a future desktop shell. This
phase has no Tauri process and no React UI.

Security assumption: the service binds only to `127.0.0.1`, every state-changing
route requires an unguessable session token, and the only client is the
controlled desktop shell. CORS is not enabled. The token is not a user account
and it is not written to the project database.

Synced multi-machine editing stays unsupported.

## Startup

From the repository root, using the AMIX environment:

```
amix/.venv/Scripts/python -m amix.amix_engine.service
```

The process binds an ephemeral port on `127.0.0.1` unless `--port` or
`AMIX_PORT` is set. The first stdout line is the only startup record. Logs go
to stderr and are not written before that line.

```json
{"event":"amix.engine.ready","host":"127.0.0.1","port":54321,"token":"<session-token>"}
```

A parent process can pass `--token` or `AMIX_SESSION_TOKEN`. Otherwise the
process generates a token with `secrets.token_urlsafe`. The token lives in
memory and ends when the process exits. It is not stored in `project.sqlite`
and it is not a preference. Authenticated calls send:

```
Authorization: Bearer <session-token>
```

The token is not placed in URLs. `/v1/health` does not require it and does not
return it. Health also omits project content and filesystem paths.

Other small settings: `--shutdown-timeout`, `--workers`, `--log-level`, and the
matching `AMIX_SHUTDOWN_TIMEOUT`, `AMIX_WORKERS`, and `AMIX_LOG_LEVEL` variables.
`--host` must stay `127.0.0.1`.

## Projects

`POST /v1/projects/create`, `POST /v1/projects/open`, `GET /v1/projects/{handle}`,
and `POST /v1/projects/{handle}/close`.

The handle is an opaque id for this process. It is not the persistent project
id and it is not the filesystem path. A second open of the same project path in
this process returns `project_already_open` and does not create another writer.
A writable open holds the Phase 3 project lock. Close releases the store and
the lock after the project's jobs stop.

Writable open applies pending Alembic migrations. Read-only open does not
migrate and cannot start jobs. A read-only open of a database that is not at
the current revision returns `schema_mismatch`.

## Jobs

Jobs are rows in `processing_job` (Alembic `0002_processing_job`). The HTTP API
polls them. There is no WebSocket or server-sent event stream. The job manager
does not depend on that polling, so a later transport can read the same records.

Production kind in this phase:

- `project_integrity_check` reads media presence and active-run references. It
  does not change analysis rows.

An HTTP body cannot name an arbitrary Python callable. Unknown kinds return
`unsupported_job_kind`. Spec fields named like secrets (`token`, `password`,
`api_key`, and similar) are rejected and are not stored.

### States

`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCEL_REQUESTED`, `CANCELLED`,
`INTERRUPTED`.

A succeeded job does not return to running. A cancelled job does not become
succeeded. Terminal rows stay as history. Retry inserts a new id.

### Progress

`progress_bp` is an integer from 0 to 10000. 10000 is 100 percent. It is not a
media timestamp and it does not decrease during one attempt.

### Cancellation

A queued job becomes `CANCELLED` immediately. A running job is marked
`CANCEL_REQUESTED` and the handler is asked to stop at its next check. The
thread is not killed. When the handler stops, the status becomes `CANCELLED`.

### Retry

There are no checkpointed Whisper or FFmpeg stages in this phase. Retry does
not resume an in-memory point. It creates a new job from the stored spec, sets
`resumed_from_job_id` to the previous job, and increments `attempt`. The old
row is unchanged.

### Crash recovery

On a writable open, jobs still `QUEUED`, `RUNNING`, or `CANCEL_REQUESTED` from
an earlier process become `INTERRUPTED` with reason
`previous_engine_session_ended`. They are not started automatically. Read-only
open does not rewrite those rows.

### Close and shutdown

Closing a project cancels its queued and running jobs and waits up to the
shutdown timeout. If a job is still active at the deadline, close returns
`project_close_timeout` and the write lock stays held. Service shutdown uses
the same wait, then closes stores and releases locks. It does not wait forever.

Worker threads only orchestrate. Later heavy media and model stages are
expected to run as subprocesses or specialized workers, not as GIL-bound
inference on this pool.

## Media and transcript reads

Authenticated project routes list media, link or relink an external file, report
present or missing, and read the active transcript in pages. Word text corrections
are an overlay. Details are in
[MEDIA_TRANSCRIPT_WORKSPACE.md](MEDIA_TRANSCRIPT_WORKSPACE.md). These routes do
not probe, copy, or transcribe media.

## Not implemented

Whisper, FFmpeg rendering, video decode, LLM
providers, model manager, reels, conversation mapping, cloud sync, WebSockets,
and distributed workers.
