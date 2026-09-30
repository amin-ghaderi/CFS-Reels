# Media runtime

Phase 7 probes linked media and builds one preview proxy. It does not play video, transcribe, or bundle FFmpeg.

## Tool boundary

`amix_engine/adapters/media/` is the only place that discovers ffmpeg and ffprobe, builds their argument lists, and runs them. Commands are subprocess argument arrays. `shell=True` is not used. Paths with spaces or Persian characters stay one argument.

Callers receive metadata and a proxy file. They do not assemble FFmpeg command strings.

A later packaged build can replace discovery with sidecar paths. Job and storage code should not call `shutil.which` itself.

## Development discovery

Nothing is downloaded, including when the tools are missing. The search is:

1. `AMIX_FFMPEG` and `AMIX_FFPROBE`. If either variable is set, that path must exist. The unset partner is the matching name in the same directory. A wrong explicit path is `media_tool_missing`. It does not continue to PATH.
2. `amix/tools/ffmpeg` and `amix/tools/ffprobe` (`.exe` on Windows) when both files are present. That directory is gitignored. Do not commit binaries.
3. `ffmpeg` and `ffprobe` on `PATH`.

The first line of each tool's `-version` output is stored on the probe or the proxy. The desktop says "FFmpeg tools are not available." It does not open a browser or a terminal.

## ffprobe

The probe asks for JSON format and stream data. AMIX keeps a summary on the same `MediaAsset`: container name, durations, start times, bit rate, video codec, display width and height, pixel format, average and real frame-rate rationals, time base, rotation, and audio codec, sample rate, channels, and layout.

The raw ffprobe document is not the domain model.

Duration policy, with no averaging:

1. Video stream duration when the file has video and that duration is present.
2. Otherwise the container duration.
3. Otherwise the audio stream duration.

`duration_us` is that choice. `video_duration_us` and `audio_duration_us` are stored beside it when the streams reported them. `duration_source` records which rule won.

Frame rate stays `fps_num` / `fps_den` from `avg_frame_rate`, or from `r_frame_rate` when the average is missing. `30000/1001` is not stored as a float. `r_fps_num` / `r_fps_den` keep the real rate. AMIX does not label the file CFR or VFR from this.

Times are integer microseconds. ffprobe decimal-second text is parsed with `Decimal` and rounded half away from zero to the nearest microsecond. A non-zero container or stream start is stored. It is not subtracted from duration and it does not move existing analysis times.

Display width and height swap when the rotation is 90 or 270 degrees off upright. Rotation itself is stored.

Probe also stores file size and modification time. That is a lightweight identity, not a hash. Re-probe updates the same asset. If the file is present and its size or modification time no longer matches the probed identity, the stored metadata may be stale. Multi-gigabyte files are not hashed.

The job kind is `media_probe`. A missing file fails as `media_missing`. A missing tool fails as `media_tool_missing`.

## V1 proxy

Profile id: `amix.proxy.v1`.

- Container: MP4
- Video: H.264, `libx264`, preset `veryfast`, CRF 23, pixel format `yuv420p`
- Audio: AAC at 128 kbps when the source has an audio stream. Video-only sources do not gain a silent stream.
- Picture: fit inside 1280×720, aspect preserved, never upscaled. Even dimensions only when a scale is required. A 320×240 source stays 320×240. A 1920×1080 source becomes 1280×720. A 1080×1920 source becomes 404×720.
- Keyframe at least every 2 seconds.
- FFmpeg's default display rotation stays on, so a phone rotation is baked into upright pixels. The scale uses the probed display size.

The file is `proxy/{source asset id}.mp4` inside the project. It is not written next to the external master. Encoding writes `proxy/.tmp/{job id}.mp4` and replaces the final file only after the encode exits cleanly and ffprobe can read the result. The database row is written after that. Cancel deletes the temporary file and does not publish a proxy asset.

One proxy row points at its source through `source_media_asset_id`. The role is `proxy`. A later generation updates that same row. The filename is not the authority.

The job kind is `generate_proxy`. The only accepted spec field is `profile`, and the only profile is `amix.proxy.v1`. The client cannot pass an executable or an argument list. The source role must be `master`.

### Timestamp policy

Policy id: `container_normalized_v1`.

The encode does not seek and does not trim. `-copyts` and zero mux delay ask FFmpeg to keep source timestamps. MP4 may still start at container time 0. AMIX does not change the source asset's times or any existing analysis.

When playback exists, proxy time maps with:

`canonical_source_us = proxy_time_us - proxy_container_start_us + source_container_start_us`

A missing start counts as 0 in that formula. Both starts are the probed values on their own assets.

### Progress and cancellation

FFmpeg progress is read from `-progress pipe:1`, not from human stderr. `out_time_us` becomes job basis points `0..9999` against the known duration, and the value never moves backward. `10000` is written only when the job succeeds. If the duration is unknown, progress stays at 0 and the activity line says the job is working. It does not invent a percent.

Stderr is kept to a short tail in the engine log. The job error shown in the desktop is a stable code such as `media_proxy_failed`.

Cancel sets the job token, then the process helper stops the FFmpeg process tree. The child is registered in the same transition that creates it. A cancel that arrives during that transition still terminates the new process; it is not left running until the next poll. Windows uses `taskkill /T`, then `/F` if it is still alive. Other platforms signal the process group, then kill it. A second cancel or shutdown may notice the same process; stopping it again is a no-op once it has exited.

Engine shutdown cancels active jobs, waits until any in-progress spawn has registered or been abandoned, then stops every owned child before the project lock is released. A cancelled or crashed encode does not become the proxy row. The proxy file is published with a replace from `proxy/.tmp` only after the encode succeeds. The next proxy job deletes leftover files in `proxy/.tmp`. An interrupted job stays interrupted until the user retries, which creates a new job. Diagnostic pid markers, when a test or worker writes one, are replaced into place only after the pid text is flushed. An empty file is not a ready process.

### Stale proxy

The proxy row records the source size and modification time it was built from. If the source file is still present and either value differs, the state is Stale. AMIX does not regenerate it automatically.

## Desktop

Analyze media and Generate proxy start the existing job API. Progress stays in the Activity panel. After the job status changes, the media list reloads. Generated proxies are not listed as source media.

## Licensing

This phase runs FFmpeg and ffprobe as external programs supplied by the developer. It does not choose a build, a configure line, or a distribution license. The binary on a developer machine is not cleared here for commercial redistribution. Packaging has to make that choice later.

## Not in this phase

Playback, waveforms, the timeline, Whisper, transcription, OpenCV, YuNet, diarization, multicam, reels, and a bundled FFmpeg.
