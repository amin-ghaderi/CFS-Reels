/** Source-time timeline viewport. The canvas draws this; React does not own each interval. */

export interface Viewport {
  originUs: number;
  spanUs: number;
  widthPx: number;
}

export interface SourceClip {
  clip_id: string;
  source_start_us: number;
  source_end_us: number;
}

export function timeToX(timeUs: number, view: Viewport): number {
  if (view.spanUs <= 0 || view.widthPx <= 0) {
    return 0;
  }
  return ((timeUs - view.originUs) * view.widthPx) / view.spanUs;
}

export function xToTime(xPx: number, view: Viewport): number {
  if (view.widthPx <= 0) {
    return view.originUs;
  }
  return Math.round(view.originUs + (xPx * view.spanUs) / view.widthPx);
}

export function fitRange(startUs: number, endUs: number, widthPx: number): Viewport {
  const span = Math.max(1, endUs - startUs);
  return { originUs: startUs, spanUs: span, widthPx: Math.max(1, widthPx) };
}

export function zoomViewport(view: Viewport, factor: number, anchorUs: number): Viewport {
  const nextSpan = Math.max(1_000, Math.round(view.spanUs * factor));
  const anchorX = timeToX(anchorUs, view);
  const origin = Math.round(anchorUs - (anchorX * nextSpan) / view.widthPx);
  return { originUs: origin, spanUs: nextSpan, widthPx: view.widthPx };
}

export function panViewport(view: Viewport, deltaPx: number): Viewport {
  const deltaUs = Math.round((deltaPx * view.spanUs) / view.widthPx);
  return { ...view, originUs: view.originUs + deltaUs };
}

export function removedRanges(sourceStartUs: number, sourceEndUs: number, clips: readonly SourceClip[]): SourceClip[] {
  const gaps: SourceClip[] = [];
  let cursor = sourceStartUs;
  const ordered = [...clips].sort((left, right) => left.source_start_us - right.source_start_us);
  ordered.forEach((clip, index) => {
    if (clip.source_start_us > cursor) {
      gaps.push({ clip_id: `gap-${index}`, source_start_us: cursor, source_end_us: clip.source_start_us });
    }
    cursor = clip.source_end_us;
  });
  if (cursor < sourceEndUs) {
    gaps.push({ clip_id: "gap-end", source_start_us: cursor, source_end_us: sourceEndUs });
  }
  return gaps;
}

export function sequenceDurationUs(clips: readonly SourceClip[]): number {
  return clips.reduce((total, clip) => total + (clip.source_end_us - clip.source_start_us), 0);
}

export function splitAllowed(clip: SourceClip | null, playheadUs: number): boolean {
  return clip !== null && clip.source_start_us < playheadUs && playheadUs < clip.source_end_us;
}

export function requestReset(confirming: boolean): { confirming: boolean; commit: boolean } {
  if (!confirming) {
    return { confirming: true, commit: false };
  }
  return { confirming: false, commit: true };
}

export function clipAtSource(clips: readonly SourceClip[], sourceUs: number): SourceClip | null {
  return clips.find((clip) => clip.source_start_us <= sourceUs && sourceUs < clip.source_end_us) ?? null;
}

export function cameraLabel(presentation: string, participantName: string | null, locked: boolean): string {
  if (locked || presentation === "protected_master") {
    return "Protected";
  }
  if (presentation === "full") {
    return `Full — ${participantName || "Participant"}`;
  }
  return "Wide";
}

export function renderKeepsSequence(spec: { sequence_id?: string; sequence_revision?: number; preset: string }): boolean {
  return spec.preset === "landscape_1080" || spec.preset === "landscape_720" || spec.preset === "portrait_1080" || spec.preset === "portrait_720";
}
