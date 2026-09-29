import { describe, expect, it } from "vitest";

import type { ReelCandidate, ReelDraft, ReelState } from "../api/types";
import {
  candidateSeekUs,
  discoveryAction,
  draftTimeline,
  draftsRemain,
  editorActions,
  exportsForSequence,
  FORMAT_LABELS,
  PICTURE_LABELS,
  reelPhase,
  reelRenderSpec,
  renderEnabled,
  treatmentReason,
  workspaceOffers,
} from "./reels";
import type { ExportRecord, SequenceRenderReadiness } from "../api/types";

const ready: ReelState = {
  transcript_present: true,
  turns_ready: true,
  blocking_reason: null,
  provider_configured: true,
  capability_ready: true,
  offline_blocked: false,
  map_present: true,
  map_stale: false,
  discovery_present: false,
  discovery_stale: false,
  reel_discovery_run_id: null,
  candidates: [],
  drafts: [],
};

const candidate: ReelCandidate = {
  candidate_id: "c1",
  order_index: 0,
  conversation_thread_id: "thread",
  first_turn_id: "T1",
  last_turn_id: "T2",
  first_word_id: "w1",
  last_word_id: "w3",
  start_us: 1_000_000,
  end_us: 4_000_000,
  duration_us: 3_000_000,
  title: "لماذا",
  summary: "ملخص",
  hook: "افتتاح",
  thread_title: "Thread",
  participant_names: ["Alice"],
};

const draft: ReelDraft = {
  sequence_id: "reel-a",
  display_name: "لماذا",
  revision: 2,
  source_start_us: 1_000_000,
  source_end_us: 4_000_000,
  duration_us: 2_000_000,
  origin_candidate_id: "c1",
  clips: [
    { clip_id: "k1", order_index: 0, source_start_us: 1_000_000, source_end_us: 2_000_000 },
    { clip_id: "k2", order_index: 1, source_start_us: 3_000_000, source_end_us: 4_000_000 },
  ],
};

describe("reel workspace", () => {
  it("keeps prerequisite states distinct", () => {
    expect(reelPhase({ hasMedia: false, state: null, discovering: false, failed: false })).toBe("no_media");
    expect(reelPhase({ hasMedia: true, state: { ...ready, transcript_present: false }, discovering: false, failed: false })).toBe("no_transcript");
    expect(reelPhase({ hasMedia: true, state: { ...ready, turns_ready: false }, discovering: false, failed: false })).toBe("turns_required");
    expect(reelPhase({ hasMedia: true, state: { ...ready, map_present: false }, discovering: false, failed: false })).toBe("map_required");
    expect(reelPhase({ hasMedia: true, state: { ...ready, map_stale: true }, discovering: false, failed: false })).toBe("map_stale");
    expect(reelPhase({ hasMedia: true, state: { ...ready, provider_configured: false }, discovering: false, failed: false })).toBe("provider_unavailable");
    expect(reelPhase({ hasMedia: true, state: ready, discovering: false, failed: false })).toBe("ready");
    expect(discoveryAction("ready")).toBe("Discover Reels");
  });

  it("selects a candidate by seeking its source start and does not invent a draft", () => {
    expect(candidateSeekUs(candidate)).toBe(1_000_000);
    expect(ready.drafts).toEqual([]);
  });

  it("rebuilds discovery, keeps drafts, and edits the selected reel", () => {
    const discovered = { ...ready, discovery_present: true, candidates: [candidate], drafts: [draft] };
    expect(reelPhase({ hasMedia: true, state: discovered, discovering: true, failed: false })).toBe("discovering");
    expect(discoveryAction("candidates_ready")).toBe("Rebuild Discovery");
    const stale = { ...discovered, discovery_stale: true };
    expect(reelPhase({ hasMedia: true, state: stale, discovering: false, failed: false })).toBe("discovery_stale");
    expect(draftsRemain(stale).map((item) => item.sequence_id)).toEqual(["reel-a"]);
    const timeline = draftTimeline(draft);
    expect(timeline.sequence_id).toBe("reel-a");
    expect(timeline.camera).toEqual([]);
    expect(timeline.removed).toEqual([{ clip_id: "gap-1", source_start_us: 2_000_000, source_end_us: 3_000_000 }]);
    expect(editorActions()).toEqual(["Split at Playhead", "Remove Clip", "Reset"]);
  });

  it("does not store aspect, score, or ranking on the draft", () => {
    expect(workspaceOffers()).toEqual({ renderSection: true, aspectOnDraft: false, score: false, jev: false, captions: false });
    expect(JSON.stringify(candidate)).not.toMatch(/portrait|score|jev/i);
    expect(JSON.stringify(draft)).not.toMatch(/portrait|preset|caption/);
  });

  it("keeps picture, format, and sequence identity independent", () => {
    const sourceLandscape = reelRenderSpec("reel-a", 4, "source_program", "16:9", "1080");
    const sourcePortrait = reelRenderSpec("reel-a", 4, "source_program", "9:16", "1080");
    const multicamPortrait = reelRenderSpec("reel-a", 4, "multicam", "9:16", "720");
    expect(sourceLandscape.spec.sequence_id).toBe(sourcePortrait.spec.sequence_id);
    expect(sourceLandscape.spec.sequence_revision).toBe(4);
    expect(sourcePortrait.spec.sequence_revision).toBe(multicamPortrait.spec.sequence_revision);
    expect(sourceLandscape.spec.visual_treatment).toBe("source_program");
    expect(multicamPortrait.spec.visual_treatment).toBe("multicam");
    expect(sourceLandscape.spec.render_profile_id).toBe("landscape_1080");
    expect(sourcePortrait.spec.render_profile_id).toBe("portrait_1080");
    expect(multicamPortrait.spec.render_profile_id).toBe("portrait_720");
    expect(draft.revision).toBe(2);
    expect(FORMAT_LABELS["16:9"]).toBe("Landscape 16:9");
    expect(FORMAT_LABELS["9:16"]).toBe("Portrait 9:16");
    expect(PICTURE_LABELS.source_program).toBe("Source / Program");
    expect(JSON.stringify(FORMAT_LABELS)).not.toMatch(/Reel format|TikTok|Instagram|caption/i);
  });

  it("offers source picture without a shot plan and scopes export history", () => {
    const readiness: SequenceRenderReadiness = {
      source_program_ready: true,
      multicam_ready: false,
      source_program_reason: null,
      multicam_reason: "shot_plan_missing",
      ffmpeg_ready: true,
    };
    expect(renderEnabled(readiness, "source_program")).toBe(true);
    expect(renderEnabled(readiness, "multicam")).toBe(false);
    expect(treatmentReason(readiness.multicam_reason)).toMatch(/shot plan/);
    const rows: ExportRecord[] = [
      { job_id: "a", filename: "a.mp4", relative_path: "exports/a.mp4", width: 1920, height: 1080, aspect: "16:9", preset_id: "landscape_1080", visual_treatment: "source_program", sequence_id: "reel-a", created_at: "t", status: "succeeded" },
      { job_id: "b", filename: "b.mp4", relative_path: "exports/b.mp4", width: 1080, height: 1920, aspect: "9:16", preset_id: "portrait_1080", visual_treatment: "multicam", sequence_id: "reel-b", created_at: "t", status: "succeeded" },
    ];
    expect(exportsForSequence(rows, "reel-a").map((row) => row.job_id)).toEqual(["a"]);
    expect(exportsForSequence(rows, "reel-b").map((row) => row.job_id)).toEqual(["b"]);
  });
});
