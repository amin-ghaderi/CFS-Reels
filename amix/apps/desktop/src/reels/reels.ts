/** Reel workspace state. A reel is a source selection, not an output format. */

import type { ReelCandidate, ReelDraft, ReelState, TimelineClip, TimelineState } from "../api/types";
import { removedRanges } from "../timeline/timeline";

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
  return ["Split at Playhead", "Remove Clip", "Reset"];
}

export function workspaceOffers(): { render: false; aspectChoice: false; score: false; jev: false } {
  return { render: false, aspectChoice: false, score: false, jev: false };
}

export function draftsRemain(state: ReelState): ReelDraft[] {
  return state.drafts;
}
