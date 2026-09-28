import { useEffect, useState } from "react";

import { createJob } from "../api/client";
import { asFailure } from "../api/errors";
import type { ProjectInfo } from "../api/types";
import { useProjectData } from "../project/ProjectData";
import { formatMicroseconds } from "../time/format";
import { usePlayback } from "./PlaybackSession";
import { canonicalToCurrentTime } from "./time";

const GENERATABLE = new Set(["not_generated", "failed", "stale", "missing"]);

export function PreviewPlayer({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const playback = usePlayback();
  const selected = data.selected;
  const view = playback.view;
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const playable = Boolean(view?.playable && view.asset_url) && !playback.mediaFailed;
  const origin = view?.canonical_origin_us ?? 0;
  const duration = view?.playback_duration_us ?? 0;
  const position = Math.min(duration, Math.max(0, playback.playheadUs - origin));

  useEffect(() => {
    const video = playback.videoRef.current;
    if (!video) {
      return;
    }
    const url = playable ? view?.asset_url : null;
    if (!url) {
      video.pause();
      video.removeAttribute("src");
      video.load();
      return;
    }
    if (video.getAttribute("src") !== url) {
      video.src = url;
    }
    video.muted = muted;
    video.volume = volume;
  }, [playable, view?.asset_url, muted, volume, playback.videoRef]);

  async function generate() {
    if (!selected) {
      return;
    }
    data.setNotice(null);
    data.setBusy(true);
    try {
      await createJob(project.handle, "generate_proxy", {
        mediaAssetId: selected.asset_id,
        spec: { profile: "amix.proxy.v1" },
      });
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  const status = playback.mediaFailed ? "unsupported" : view?.status;
  const notice = statusMessage(status, playback.failure);
  const canGenerate =
    selected?.role === "master" &&
    selected.status === "present" &&
    !project.read_only &&
    status != null &&
    GENERATABLE.has(status);

  return (
    <section className="preview" aria-label="Preview">
      <video
        ref={playback.videoRef}
        className={playable ? undefined : "hidden"}
        playsInline
        preload="metadata"
        onLoadedMetadata={(event) => {
          const current = playback.view;
          if (!current?.playable) {
            return;
          }
          event.currentTarget.currentTime = canonicalToCurrentTime(
            current.canonical_origin_us,
            playback.playheadUs,
            current.playback_duration_us,
          );
        }}
        onTimeUpdate={(event) => playback.reportTime(event.currentTarget.currentTime)}
        onSeeked={(event) => playback.reportTime(event.currentTarget.currentTime)}
        onPlay={() => playback.setPlaying(true)}
        onPause={() => playback.setPlaying(false)}
        onError={() => playback.failMedia()}
      />
      {view?.warning ? <p className="warning">{view.warning}</p> : null}
      {!playable ? <p className="muted">{notice ?? (selected ? "Preparing preview." : "Select a media file to preview.")}</p> : null}
      <div className="transport">
        <button type="button" aria-label={playback.playing ? "Pause" : "Play"} aria-pressed={playback.playing} disabled={!playable} onClick={playback.toggle}>
          {playback.playing ? "Pause" : "Play"}
        </button>
        <span className="numeric" dir="ltr">
          {formatMicroseconds(playable ? playback.playheadUs : 0)}
        </span>
        <input
          type="range"
          aria-label="Seek"
          min={0}
          max={duration}
          step={1}
          value={position}
          disabled={!playable || duration <= 0}
          onChange={(event) => playback.requestSeek(origin + Number(event.target.value))}
        />
        <span className="numeric" dir="ltr">
          {formatMicroseconds(duration)}
        </span>
        <button type="button" aria-label={muted || volume === 0 ? "Unmute" : "Mute"} aria-pressed={muted || volume === 0} disabled={!playable} onClick={() => setMuted((value) => !value)}>
          {muted || volume === 0 ? "Unmute" : "Mute"}
        </button>
        <input
          type="range"
          aria-label="Volume"
          min={0}
          max={1}
          step={0.05}
          value={muted ? 0 : volume}
          disabled={!playable}
          onChange={(event) => {
            const next = Number(event.target.value);
            setVolume(next);
            setMuted(next === 0);
          }}
        />
      </div>
      {canGenerate ? (
        <button type="button" className="primary" disabled={data.busy} onClick={() => void generate()}>
          {status === "not_generated" || status === "failed" ? "Generate proxy" : "Regenerate proxy"}
        </button>
      ) : null}
    </section>
  );
}

function statusMessage(status: string | undefined, failure: string | null): string | null {
  if (failure && status !== "ready") {
    return failure;
  }
  switch (status) {
    case "not_generated":
      return "Generate a proxy to preview this media.";
    case "queued":
      return "A proxy is queued.";
    case "generating":
      return "Generating a preview proxy.";
    case "stale":
      return "This proxy is out of date. Regenerate it to preview.";
    case "missing":
      return "The proxy file is missing. Regenerate it to preview.";
    case "failed":
      return "Proxy generation failed.";
    case "unsupported":
      return "This proxy could not be played.";
    case "unavailable":
      return failure ?? "Preview file is unavailable.";
    default:
      return failure;
  }
}
