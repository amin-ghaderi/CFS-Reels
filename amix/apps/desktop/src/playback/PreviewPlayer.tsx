import { useEffect, useState, type ReactNode } from "react";

import type { ProjectInfo } from "../api/types";
import { useProjectData } from "../project/ProjectData";
import { formatMicroseconds } from "../time/format";
import { usePlayback } from "./PlaybackSession";
import { canonicalToCurrentTime, currentTimeToCanonical } from "./time";
import { previewShouldStop, reelClockUs, replayStartUs } from "../reels/reels";

export function PreviewPlayer({
  project,
  overlay,
  range,
}: {
  project: ProjectInfo;
  overlay?: ReactNode;
  range?: { startUs: number; endUs: number } | null;
}) {
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
  const bounded = range != null && range.endUs > range.startUs;
  const reelDuration = bounded ? range.endUs - range.startUs : duration;
  const reelPosition = bounded ? reelClockUs(playback.playheadUs, range.startUs, range.endUs) : position;

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

  const status = playback.mediaFailed ? "unsupported" : view?.status;
  const notice = statusMessage(status, playback.failure);

  return (
    <section className="preview" aria-label="Preview" data-readonly={project.read_only ? "true" : "false"}>
      <div className="preview-frame">
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
          onTimeUpdate={(event) => {
            playback.reportTime(event.currentTarget.currentTime);
            if (!bounded || !view?.playable) {
              return;
            }
            const canonical = currentTimeToCanonical(
              view.canonical_origin_us,
              event.currentTarget.currentTime,
              view.playback_duration_us,
            );
            if (previewShouldStop(canonical, range.endUs) && !event.currentTarget.paused) {
              event.currentTarget.pause();
            }
          }}
          onSeeked={(event) => playback.reportTime(event.currentTarget.currentTime)}
          onPlay={() => playback.setPlaying(true)}
          onPause={() => playback.setPlaying(false)}
          onError={() => playback.failMedia()}
        />
        {overlay}
      </div>
      {view?.warning ? <p className="warning">{view.warning}</p> : null}
      {!playable ? <p className="muted">{notice ?? (selected ? "Preparing preview." : "Select a media file to preview.")}</p> : null}
      <div className="transport">
        <button
          type="button"
          aria-label={playback.playing ? "Pause" : "Play"}
          aria-pressed={playback.playing}
          disabled={!playable}
          onClick={() => {
            if (bounded && !playback.playing && (playback.playheadUs < range.startUs || previewShouldStop(playback.playheadUs, range.endUs))) {
              playback.requestSeek(replayStartUs(range.startUs));
            }
            playback.toggle();
          }}
        >
          {playback.playing ? "Pause" : "Play"}
        </button>
        {bounded ? (
          <button
            type="button"
            aria-label="Replay"
            disabled={!playable}
            onClick={() => {
              playback.requestSeek(replayStartUs(range.startUs));
              const video = playback.videoRef.current;
              if (video) {
                void video.play().catch(() => playback.failMedia());
              }
            }}
          >
            Replay
          </button>
        ) : null}
        {bounded ? (
          <>
            <span className="numeric" dir="ltr" aria-label="Reel time">
              Reel {formatMicroseconds(playable ? reelPosition : 0)}
            </span>
            <span className="numeric" dir="ltr" aria-label="Episode time">
              Episode {formatMicroseconds(playable ? playback.playheadUs : 0)}
            </span>
          </>
        ) : (
          <span className="numeric" dir="ltr">
            {formatMicroseconds(playable ? playback.playheadUs : 0)}
          </span>
        )}
        <input
          type="range"
          aria-label={bounded ? "Reel timeline" : "Seek"}
          min={0}
          max={bounded ? reelDuration : duration}
          step={1}
          value={bounded ? reelPosition : position}
          disabled={!playable || (bounded ? reelDuration <= 0 : duration <= 0)}
          onChange={(event) => playback.requestSeek(bounded ? range.startUs + Number(event.target.value) : origin + Number(event.target.value))}
        />
        <span className="numeric" dir="ltr">
          {formatMicroseconds(bounded ? reelDuration : duration)}
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
    </section>
  );
}

function statusMessage(status: string | undefined, failure: string | null): string | null {
  if (failure && status !== "ready") {
    return failure;
  }
  switch (status) {
    case "not_generated":
    case "queued":
    case "generating":
      return "Preparing preview…";
    case "stale":
      return "Preview is out of date.";
    case "missing":
      return "Preview is missing.";
    case "failed":
      return "Preview preparation failed.";
    case "unsupported":
      return "This proxy could not be played.";
    case "unavailable":
      return failure ?? "Preview file is unavailable.";
    default:
      return failure;
  }
}
