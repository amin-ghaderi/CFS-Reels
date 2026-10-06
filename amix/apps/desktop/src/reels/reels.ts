/** Reel workspace state. A reel is a source selection, not an output format. */

import type { ExportRecord, ReelCandidate, ReelDraft, ReelState, SequenceRenderReadiness, TimelineClip, TimelineState } from "../api/types";
import { presetId, type OutputFormat, type OutputResolution } from "../multicam/multicam";
import { removedRanges } from "../timeline/timeline";

export type PictureTreatment = "source_program" | "multicam";

export type ReelPhase =
  | "no_media"
  | "no_transcript"
  | "turns_required"
  | "map_required"
  | "map_stale"
  | "provider_unavailable"
  | "discovering"
  | "ready"
  | "failed"
  | "discovery_stale"
  | "candidates_ready";

export const REEL_PROFILE = "amix.reel.discover.v1";

export function discoveryActivity(localAiState: string | null | undefined): string {
  if (localAiState === "STARTING") {
    return "Starting local model.";
  }
  if (localAiState === "LOADING") {
    return "Loading model.";
  }
  return "Discovering reels.";
}

export function reelPhase(input: {
  hasMedia: boolean;
  state: ReelState | null;
  discovering: boolean;
  failed: boolean;
}): ReelPhase {
  if (!input.hasMedia) {
    return "no_media";
  }
  const state = input.state;
  if (!state || !state.transcript_present) {
    return "no_transcript";
  }
  if (!state.turns_ready) {
    return "turns_required";
  }
  if (!state.map_present) {
    return "map_required";
  }
  if (state.map_stale) {
    return "map_stale";
  }
  if (!state.provider_configured || state.offline_blocked || !state.capability_ready) {
    return "provider_unavailable";
  }
  if (input.discovering) {
    return "discovering";
  }
  if (state.discovery_present && state.discovery_stale) {
    return "discovery_stale";
  }
  if (state.discovery_present) {
    return "candidates_ready";
  }
  if (input.failed) {
    return "failed";
  }
  return "ready";
}

export function discoveryAction(phase: ReelPhase): "Discover Reels" | "Rebuild Discovery" | null {
  if (phase === "ready" || phase === "failed") {
    return "Discover Reels";
  }
  if (phase === "candidates_ready" || phase === "discovery_stale") {
    return "Rebuild Discovery";
  }
  return null;
}

export function candidateSeekUs(candidate: ReelCandidate): number {
  return candidate.start_us;
}

export function draftTimeline(draft: ReelDraft): TimelineState {
  let cursor = 0;
  const clips: TimelineClip[] = draft.clips.map((clip) => {
    const sequenceStart = cursor;
    cursor += clip.source_end_us - clip.source_start_us;
    return { ...clip, sequence_start_us: sequenceStart };
  });
  return {
    sequence_id: draft.sequence_id,
    revision: draft.revision,
    fingerprint: null,
    source_start_us: draft.source_start_us,
    source_end_us: draft.source_end_us,
    duration_us: draft.duration_us,
    clips,
    removed: removedRanges(draft.source_start_us, draft.source_end_us, clips),
    camera: [],
    protected: [],
  };
}

export function editorActions(): readonly string[] {
  return ["Split at Playhead", "Remove Clip", "Reset to original suggestion"];
}

/** Play stops once the playhead reaches the suggestion or reel end. */
export function previewShouldStop(playheadUs: number, endUs: number): boolean {
  return playheadUs >= endUs;
}

/** Replay always begins at the suggestion or reel start. */
export function replayStartUs(startUs: number): number {
  return startUs;
}

/** Elapsed time inside the reel, separate from the episode clock. */
export function reelClockUs(playheadUs: number, startUs: number, endUs: number): number {
  const duration = Math.max(0, endUs - startUs);
  return Math.min(duration, Math.max(0, playheadUs - startUs));
}

export function suggestionEmptyMessage(count: number, dismissed: number): string | null {
  if (count > 0) {
    return null;
  }
  if (dismissed > 0) {
    return "No Reel suggestions left.";
  }
  return "No usable Reel suggestions were found.";
}

export const USE_REEL_LABEL = "Use this Reel";
export const EXPORT_REEL_LABEL = "Export Reel";
export const DISMISS_LABEL = "Dismiss";
export const SUGGESTIONS_LABEL = "Reel Suggestions";

/** Multicam is a choice only when a current shot plan can actually render. */
export function pictureChoices(readiness: { source_program_ready: boolean; multicam_ready: boolean }): PictureTreatment[] {
  const choices: PictureTreatment[] = [];
  if (readiness.source_program_ready) {
    choices.push("source_program");
  }
  if (readiness.multicam_ready) {
    choices.push("multicam");
  }
  return choices;
}

export function workspaceOffers(): { renderSection: true; aspectOnDraft: false; score: false; jev: false; captions: false } {
  return { renderSection: true, aspectOnDraft: false, score: false, jev: false, captions: false };
}

export function draftsRemain(state: ReelState): ReelDraft[] {
  return state.drafts;
}

export function reelRenderSpec(
  sequenceId: string,
  revision: number,
  treatment: PictureTreatment,
  format: OutputFormat,
  resolution: OutputResolution,
) {
  return {
    kind: "render_sequence" as const,
    spec: {
      sequence_id: sequenceId,
      sequence_revision: revision,
      visual_treatment: treatment,
      render_profile_id: presetId(format, resolution),
    },
  };
}

export function treatmentReason(code: string | null): string {
  switch (code) {
    case "shot_plan_missing":
      return "Multicam needs a current shot plan.";
    case "shot_plan_stale":
      return "The shot plan is out of date.";
    case "layout_incompatible":
      return "The layout no longer matches the shot plan.";
    case "source_missing":
      return "The original source media is missing.";
    case "ffmpeg_missing":
      return "FFmpeg is not available.";
    case "empty_sequence":
      return "This reel has no kept picture.";
    default:
      return "";
  }
}

export function renderEnabled(readiness: SequenceRenderReadiness, treatment: PictureTreatment): boolean {
  return treatment === "source_program" ? readiness.source_program_ready : readiness.multicam_ready;
}

export function exportsForSequence(rows: readonly ExportRecord[], sequenceId: string): ExportRecord[] {
  return rows.filter((row) => row.sequence_id === sequenceId);
}

export const PICTURE_LABELS = {
  source_program: "Source / Program",
  multicam: "Multicam",
} as const;

export const FORMAT_LABELS = {
  "16:9": "Landscape 16:9",
  "9:16": "Portrait 9:16",
} as const;
