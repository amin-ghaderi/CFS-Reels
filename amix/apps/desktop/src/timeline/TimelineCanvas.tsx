import { useEffect, useRef } from "react";

import type { TimelineState } from "../api/types";
import { cameraLabel, fitRange, removedRanges, timeToX, xToTime, type Viewport } from "./timeline";

const RULER = 22;
const TRACK = 46;
const GAP = 8;

export function TimelineCanvas({
  timeline,
  playheadUs,
  selectedClipId,
  onSeek,
  onSelect,
  showCamera = true,
}: {
  timeline: TimelineState;
  playheadUs: number;
  selectedClipId: string | null;
  onSeek: (sourceUs: number) => void;
  onSelect: (clipId: string | null) => void;
  showCamera?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewRef = useRef<Viewport | null>(null);
  const start = timeline.source_start_us ?? 0;
  const end = timeline.source_end_us ?? start + 1;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const width = Math.max(1, canvas.clientWidth);
    viewRef.current = fitRange(start, end, width);
    draw(canvas, timeline, playheadUs, selectedClipId, viewRef.current, showCamera);
  }, [start, end, showCamera]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const view = viewRef.current;
    if (!canvas || !view) {
      return;
    }
    draw(canvas, timeline, playheadUs, selectedClipId, view, showCamera);
  }, [playheadUs, timeline, selectedClipId, start, end, showCamera]);

  function zoom(factor: number) {
    const canvas = canvasRef.current;
    const view = viewRef.current;
    if (!canvas || !view) {
      return;
    }
    const next = {
      ...view,
      spanUs: Math.max(1_000, Math.round(view.spanUs * factor)),
      widthPx: canvas.clientWidth,
    };
    const anchor = Math.min(end, Math.max(start, playheadUs));
    const x = timeToX(anchor, view);
    next.originUs = Math.round(anchor - (x * next.spanUs) / next.widthPx);
    viewRef.current = next;
    draw(canvas, timeline, playheadUs, selectedClipId, next, showCamera);
  }

  return (
    <div className="timeline-wrap">
      <div className="row">
        <button type="button" onClick={() => zoom(0.5)}>Zoom in</button>
        <button type="button" onClick={() => zoom(2)}>Zoom out</button>
        <button type="button" onClick={() => {
          const canvas = canvasRef.current;
          if (!canvas) {
            return;
          }
          const fitted = fitRange(start, end, canvas.clientWidth);
          viewRef.current = fitted;
          draw(canvas, timeline, playheadUs, selectedClipId, fitted, showCamera);
        }}>Fit source</button>
      </div>
      <canvas
        ref={canvasRef}
        className="timeline-canvas"
        aria-hidden="true"
        onClick={(event) => {
          const canvas = canvasRef.current;
          const view = viewRef.current;
          if (!canvas || !view) {
            return;
          }
          const rect = canvas.getBoundingClientRect();
          const sourceUs = xToTime(event.clientX - rect.left, { ...view, widthPx: rect.width });
          const hit = timeline.clips.find((clip) => clip.source_start_us <= sourceUs && sourceUs < clip.source_end_us);
          onSelect(hit ? hit.clip_id : null);
          onSeek(sourceUs);
        }}
      />
    </div>
  );
}

function draw(
  canvas: HTMLCanvasElement,
  timeline: TimelineState,
  playheadUs: number,
  selectedClipId: string | null,
  view: Viewport,
  showCamera: boolean,
) {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, canvas.clientWidth);
  const height = showCamera ? RULER + GAP + TRACK + GAP + TRACK + 8 : RULER + GAP + TRACK + 8;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  canvas.style.height = `${height}px`;
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  const fitted = { ...view, widthPx: width };
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#1b1d22";
  context.fillRect(0, 0, width, height);
  context.fillStyle = "#9aa0a6";
  context.font = "11px sans-serif";
  context.fillText("Source", 4, RULER - 6);
  const editTop = RULER + GAP;
  const cameraTop = editTop + TRACK + GAP;
  const sourceStart = timeline.source_start_us ?? 0;
  const sourceEnd = timeline.source_end_us ?? sourceStart;
  paintRange(context, fitted, sourceStart, sourceEnd, editTop, TRACK, "#2a2e35");
  removedRanges(sourceStart, sourceEnd, timeline.clips).forEach((gap) => {
    paintRange(context, fitted, gap.source_start_us, gap.source_end_us, editTop, TRACK, "#3a2a2a");
  });
  timeline.clips.forEach((clip) => {
    paintRange(
      context,
      fitted,
      clip.source_start_us,
      clip.source_end_us,
      editTop,
      TRACK,
      clip.clip_id === selectedClipId ? "#2f6f4e" : "#3d8f62",
    );
  });
  timeline.protected.forEach((region) => {
    paintRange(context, fitted, region.source_start_us, region.source_end_us, editTop, 6, "#d4a017");
  });
  if (showCamera) timeline.camera.forEach((fragment) => {
    paintRange(context, fitted, fragment.source_start_us, fragment.source_end_us, cameraTop, TRACK, fragment.locked ? "#6a5a2a" : "#3a4d6e");
    const x = timeToX(fragment.source_start_us, fitted);
    const right = timeToX(fragment.source_end_us, fitted);
    if (right - x > 48) {
      context.fillStyle = "#f4f4f4";
      context.fillText(cameraLabel(fragment.presentation, fragment.participant_name, fragment.locked), x + 4, cameraTop + 18);
    }
  });
  const playX = timeToX(playheadUs, fitted);
  context.strokeStyle = "#f2f2f2";
  context.beginPath();
  context.moveTo(playX, 0);
  context.lineTo(playX, height);
  context.stroke();
}

function paintRange(
  context: CanvasRenderingContext2D,
  view: Viewport,
  startUs: number,
  endUs: number,
  top: number,
  height: number,
  color: string,
) {
  const left = timeToX(startUs, view);
  const right = timeToX(endUs, view);
  context.fillStyle = color;
  context.fillRect(left, top, Math.max(1, right - left), height);
}
