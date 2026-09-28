# Playback

Phase 8 plays the project preview proxy and keeps the transcript on the same canonical clock. It does not play source-camera files, and it does not transcribe.

## Proxy-only preview

The playable file is a valid AMIX V1 proxy (`amix.proxy.v1`, timestamp policy `container_normalized_v1`). The desktop does not fall back to the linked source. Source codecs are not a preview format, and a direct source play would not behave the same way in the Windows and macOS webviews.

The engine decides which proxy belongs to the selected source. It uses the stored `source_media_asset_id` relation from Phase 7. It does not pick a file by name.

| Proxy state | Preview |
| --- | --- |
| Not generated | "Generate a proxy to preview this media." |
| Queued or generating | That state in the player. The existing Activity job is the only progress. |
| Stale, missing, or failed | That state, with Generate or Regenerate when the source file is present. |
| Ready V1 proxy | HTML video of that proxy. |

A proxy row with another profile or timestamp policy is not playable.

## Source missing, proxy present

If the proxy file exists, its provenance is the V1 policy, and it was not already known to be stale, preview still works after the external source disappears. The player warns: "Original media is currently unavailable. Preview is using the project proxy."

Stale is known when a live stat of the source disagrees with the proxy, or, if the source can no longer be stat'd, when the source asset's stored size or modification time already disagrees with the proxy's recorded source identity. Phase 7 does not keep a separate stale flag. A proxy is not treated as stale merely because the source path is gone.

Preview does not mean export or media-dependent analysis can run without the original.

## canonical_origin_us

`canonical_origin_us` is the integer AMIX source timestamp where `HTMLMediaElement.currentTime` is 0. The engine computes it. React does not rebuild it from database fields.

For `container_normalized_v1`:

```
canonical_source_us = proxy_time_us - proxy_container_start_us + source_container_start_us
```

Missing container starts count as 0. At proxy time 0:

```
canonical_origin_us = source_container_start_us - proxy_container_start_us
```

Analysis times stay integer microseconds. Browser `currentTime` is a float and is converted once at the player boundary:

- reported `currentTime` → nearest playback microseconds → `canonical_origin_us + playback_us`
- a requested canonical microsecond → subtract `canonical_origin_us` → one division into seconds → `currentTime`, clamped to the proxy duration

The float is not stored as canonical time. A seek keeps the requested integer (`word.start_us` for a word click). After `seeked`, the playhead may follow the time the decoder actually landed on. Word and analysis times are not rewritten to match that landing. The V1 proxy already has a two-second keyframe interval. This phase does not regenerate proxies to chase frame-accurate seeks.

## Transcript sync

The Media and Transcript workspaces share one playback session and one video element for the selected source. Switching workspace mounts that player again and seeks it back to the canonical playhead.

A word click selects the word and, when a proxy is playable, seeks to that word's integer `start_us`. Without a proxy, the word still selects and the transcript stays usable.

Highlight uses the loaded page only. A word is current when `start_us <= playhead < end_us`. Silence has no current word. Manual text corrections do not move the highlight; identity and time do.

Long transcripts stay paged. The page size (80) is a frontend setting. While the playhead is inside the loaded page's `[first.start_us, last.end_us)`, lookup is local. When a seek or playback leaves that range, the desktop calls `GET /v1/projects/{handle}/media/{asset_id}/transcript/word-at/{time_us}` once. The response is the containing word's id, sequence, and range, or `found: false`. The next page offset is `floor(sequence / pageSize) * pageSize`. A miss, or a sequence that is already on this page, does not ask again until the playhead re-enters the page or the user seeks.

## Tauri asset protocol

Playback uses Tauri's built-in asset protocol. There is no second HTTP server, no FastAPI video stream, and no `file://` URL. The configured asset scope is empty. Nothing broad (`$HOME/**`, a drive root, `/**`) is allowed.

`prepare_playback` takes a source media-asset id and a request id. It does not take a path. Rust checks the live engine generation and open project, asks the engine for the descriptor, checks that the resolved file is a real file inside that project's `proxy/` directory, then hard-links it to `proxy/.playback/{request}-{time}.mp4`. Only that hard link is passed to `allow_file`. The original proxy and any sibling file stay out of the scope. The command result given to React is an asset URL plus the integer mapping. It does not include a filesystem path, and the desktop does not put one in `localStorage`.

The URL is built the same way as Tauri's `convertFileSrc`:

- Windows: `http://asset.localhost/...`
- other platforms: `asset://localhost/...`

CSP adds `media-src 'self' asset: http://asset.localhost` and leaves `script-src`, `connect-src`, and `default-src` as they were. CSP is not disabled.

Tauri's asset handler answers HTTP Range requests and reads only the requested slice (capped inside Tauri, currently 1 MB per range). AMIX does not read a proxy into a JavaScript or Rust buffer.

macOS has not been run. The hard link and the `asset://localhost/` URL form need a Mac pass before that platform is called verified. `forbid_file` in Tauri 2.12 is permanent for a path, which is why each preview uses a new hard link instead of forbidding the real proxy path.

## Scope lifetime

The in-memory book is the list of hard links currently exposed. A later request id replaces an earlier one, so a slow prepare for media A cannot install after media B. Releasing a request forbids and deletes that request's hard link.

The book is cleared, and those hard links are forbidden and deleted, when:

- the project closes or another project is opened
- the engine restarts (generation changes)
- the engine process exits unexpectedly
- the desktop shuts down

An empty prepare (no proxy, stale, generating) also drops the previous hard link so the old player cannot keep playing.

After a proxy job succeeds, the media list refresh changes proxy state. The player releases the old session and prepares the current proxy. It does not swap bytes under a live element. If the file identity changed, the old URL is gone and the new hard link is a new URL.

## Not in this phase

Whisper, transcription jobs, waveforms, the timeline editor, frame stepping, J/K/L, mark in/out, shuttle, multicam, reels, source-camera playback, final render, Model Manager, and packaging.
