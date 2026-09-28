import { createContext, useContext, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import { preparePlayback, releasePlayback } from "../api/client";
import { asFailure } from "../api/errors";
import type { PreparedPlayback } from "../api/types";
import { useProjectData } from "../project/ProjectData";
import { canonicalToCurrentTime, currentTimeToCanonical } from "./time";

interface PlaybackValue {
  view: PreparedPlayback | null;
  failure: string | null;
  playheadUs: number;
  requestedSeekUs: number | null;
  seekSerial: number;
  playing: boolean;
  mediaFailed: boolean;
  videoRef: RefObject<HTMLVideoElement | null>;
  requestSeek: (canonicalUs: number) => boolean;
  toggle: () => void;
  reportTime: (seconds: number) => void;
  setPlaying: (playing: boolean) => void;
  failMedia: () => void;
}

const PlaybackContext = createContext<PlaybackValue | null>(null);

export function PlaybackProvider({ generation, children }: { generation: number; children: ReactNode }) {
  const data = useProjectData();
  const selected = data.selected;
  const requestRef = useRef(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const viewRef = useRef<PreparedPlayback | null>(null);
  const [view, setView] = useState<PreparedPlayback | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [playheadUs, setPlayheadUs] = useState(0);
  const [requestedSeekUs, setRequestedSeekUs] = useState<number | null>(null);
  const [seekSerial, setSeekSerial] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [mediaFailed, setMediaFailed] = useState(false);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  useEffect(() => {
    const requestId = ++requestRef.current;
    let stop = false;
    setView(null);
    viewRef.current = null;
    setFailure(null);
    setPlaying(false);
    setMediaFailed(false);
    setRequestedSeekUs(null);
    const assetId = selected?.role === "master" ? selected.asset_id : null;
    if (assetId) {
      void preparePlayback(assetId, requestId)
        .then((prepared) => {
          if (stop || prepared.stale || prepared.request_id !== requestId) {
            return;
          }
          viewRef.current = prepared;
          setView(prepared);
          setPlayheadUs(prepared.playable ? prepared.canonical_origin_us : 0);
          if (prepared.message) {
            setFailure(prepared.message);
          }
        })
        .catch((error: unknown) => {
          if (!stop) {
            setFailure(asFailure(error).message);
          }
        });
    }
    return () => {
      stop = true;
      const video = videoRef.current;
      if (video) {
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
      if (assetId) {
        void releasePlayback(requestId).catch(() => undefined);
      }
    };
  }, [selected?.asset_id, selected?.role, selected?.proxy_state, selected?.proxy_asset_id, generation]);

  function requestSeek(canonicalUs: number): boolean {
    const current = viewRef.current;
    if (!current?.playable || !Number.isInteger(canonicalUs)) {
      return false;
    }
    setRequestedSeekUs(canonicalUs);
    setSeekSerial((value) => value + 1);
    setPlayheadUs(canonicalUs);
    const video = videoRef.current;
    if (video) {
      video.currentTime = canonicalToCurrentTime(current.canonical_origin_us, canonicalUs, current.playback_duration_us);
    }
    return true;
  }

  function reportTime(seconds: number) {
    const current = viewRef.current;
    if (!current?.playable) {
      return;
    }
    const next = currentTimeToCanonical(current.canonical_origin_us, seconds, current.playback_duration_us);
    setPlayheadUs((existing) => (existing === next ? existing : next));
  }

  function toggle() {
    const video = videoRef.current;
    if (!video || !viewRef.current?.playable) {
      return;
    }
    if (video.paused) {
      void video.play().catch(() => setMediaFailed(true));
    } else {
      video.pause();
    }
  }

  const value: PlaybackValue = {
    view,
    failure,
    playheadUs,
    requestedSeekUs,
    seekSerial,
    playing,
    mediaFailed,
    videoRef,
    requestSeek,
    toggle,
    reportTime,
    setPlaying,
    failMedia: () => setMediaFailed(true),
  };

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}

export function usePlayback(): PlaybackValue {
  const value = useContext(PlaybackContext);
  if (!value) {
    throw new Error("Playback is only available inside a project.");
  }
  return value;
}
