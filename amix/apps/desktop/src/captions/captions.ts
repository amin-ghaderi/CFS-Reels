/**Caption preview and editor behavior. Shared by the primary edit and reel drafts. */

export interface CaptionCueView {
  cue_id: string;
  order_index: number;
  first_word_id: string;
  last_word_id: string;
  source_start_us: number;
  source_end_us: number;
  sequence_start_us: number;
  sequence_end_us: number;
  generated_text: string;
  manual_text: string | null;
  effective_text: string;
}

export type CaptionStatus = "absent" | "ready" | "stale";

export const CAPTION_COPY = {
  none: "No captions",
  ready: "Captions ready",
  stale: "Captions out of date",
  generate: "Generate Captions",
  regenerate: "Regenerate Captions",
  exportSrt: "Export SRT",
  exportVtt: "Export VTT",
  useGenerated: "Use Generated Text",
  staleNote: "Regenerate captions before exporting. Manual caption edits on the old track may not carry over.",
  edited: "Edited",
  save: "Save caption",
} as const;

export const CAPTION_ACTIONS = [
  CAPTION_COPY.generate,
  CAPTION_COPY.regenerate,
  CAPTION_COPY.exportSrt,
  CAPTION_COPY.exportVtt,
  CAPTION_COPY.useGenerated,
] as const;

export function captionStatusLabel(status: CaptionStatus | null): string {
  if (status === "ready") {
    return CAPTION_COPY.ready;
  }
  if (status === "stale") {
    return CAPTION_COPY.stale;
  }
  return CAPTION_COPY.none;
}

export function exportEnabled(status: CaptionStatus | null): boolean {
  return status === "ready";
}

export function cueAtSource(cues: readonly CaptionCueView[], sourceUs: number): CaptionCueView | null {
  return cues.find((cue) => cue.source_start_us <= sourceUs && sourceUs < cue.source_end_us) ?? null;
}

export function overlayText(cues: readonly CaptionCueView[], sourceUs: number): string | null {
  return cueAtSource(cues, sourceUs)?.effective_text ?? null;
}

/** Source playback seek. Sequence time is not the preview clock. */
export function seekTargetUs(cue: CaptionCueView): number {
  return cue.source_start_us;
}

export function captionTextDirection(): "auto" {
  return "auto";
}

export function captionCopyMentionsPortraitOrStyle(): boolean {
  const blob = Object.values(CAPTION_COPY).join("\n");
  return /9:16 caption|vertical caption|burn-?in|font|theme|karaoke/i.test(blob);
}
