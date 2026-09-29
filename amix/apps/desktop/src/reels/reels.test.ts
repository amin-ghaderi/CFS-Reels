import { describe, expect, it } from "vitest";

import type { ReelCandidate, ReelDraft, ReelState } from "../api/types";
import {
  candidateSeekUs,
  discoveryAction,
  draftTimeline,
  draftsRemain,
  editorActions,
  reelPhase,
  workspaceOffers,
} from "./reels";

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

  it("does not offer rendering, aspect, score, or ranking", () => {
    expect(workspaceOffers()).toEqual({ render: false, aspectChoice: false, score: false, jev: false });
    expect(JSON.stringify(candidate)).not.toMatch(/9:16|portrait|width|height|score/);
    expect(JSON.stringify(draft)).not.toMatch(/9:16|portrait|preset/);
  });
});
