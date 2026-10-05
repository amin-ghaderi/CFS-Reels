import { describe, expect, it } from "vitest";

import { formatMicroseconds } from "../time/format";
import type { ConversationState, ConversationThread } from "../api/types";
import {
  conversationActions,
  conversationDisplay,
  conversationPhase,
  mappingActivity,
  providerCheckLabel,
  providerLabel,
  semanticTimeoutDetail,
  semanticTimeoutSummary,
  showExistingThreads,
  threadSeekUs,
} from "./conversation";

const thread: ConversationThread = {
  thread_id: "th1",
  order_index: 0,
  first_turn_id: "T1",
  last_turn_id: "T2",
  first_word_id: "w1",
  last_word_id: "w3",
  title: "Opening",
  summary: "They start.",
  topic: null,
  start_us: 1_500_000,
  end_us: 4_000_000,
  duration_us: 2_500_000,
  participant_names: ["Alice"],
};

function state(patch: Partial<ConversationState> = {}): ConversationState {
  return {
    transcript_present: true,
    turns_ready: true,
    blocking_reason: null,
    provider_configured: true,
    provider_display_name: "Local model",
    provider_model_id: "demo",
    provider_execution: "local",
    capability_ready: true,
    offline_blocked: false,
    network_mode: "offline",
    map_present: false,
    map_stale: false,
    conversation_map_run_id: null,
    threads: [],
    ...patch,
  };
}

describe("conversation workspace", () => {
  it("keeps prerequisite states distinct", () => {
    expect(conversationPhase({ hasMedia: false, state: null, mapping: false, failed: false })).toBe("no_media");
    expect(conversationPhase({ hasMedia: true, state: state({ transcript_present: false }), mapping: false, failed: false })).toBe("no_transcript");
    expect(conversationPhase({ hasMedia: true, state: state({ turns_ready: false }), mapping: false, failed: false })).toBe("turns_required");
    expect(conversationPhase({ hasMedia: true, state: state({ provider_configured: false }), mapping: false, failed: false })).toBe("provider_missing");
    expect(conversationPhase({ hasMedia: true, state: state({ offline_blocked: true, capability_ready: false }), mapping: false, failed: false })).toBe("offline_blocked");
    expect(conversationPhase({ hasMedia: true, state: state(), mapping: true, failed: false })).toBe("mapping");
    expect(conversationPhase({ hasMedia: true, state: state(), mapping: false, failed: true })).toBe("failed");
    expect(conversationPhase({ hasMedia: true, state: state(), mapping: false, failed: false })).toBe("ready");
    expect(conversationPhase({
      hasMedia: true,
      state: state({ map_present: true, map_stale: true, threads: [thread] }),
      mapping: false,
      failed: false,
    })).toBe("stale");
    expect(conversationPhase({
      hasMedia: true,
      state: state({ map_present: true, threads: [thread], conversation_map_run_id: "run" }),
      mapping: false,
      failed: false,
    })).toBe("mapped");
  });

  it("seeks the engine-derived source start and keeps the old map visible", () => {
    expect(threadSeekUs(thread)).toBe(thread.start_us);
    expect(formatMicroseconds(thread.start_us)).toContain("1");
    expect(showExistingThreads("mapping", [thread])).toBe(true);
    expect(showExistingThreads("failed", [thread])).toBe(true);
    expect(conversationActions("mapped")).toEqual(["Rebuild Map"]);
    expect(conversationActions("ready")).toEqual(["Map Conversation"]);
    expect(mappingActivity("STARTING")).toBe("Starting local model.");
    expect(mappingActivity("LOADING")).toBe("Loading model.");
    expect(mappingActivity("READY")).toBe("Mapping conversation.");
    expect(mappingActivity(null)).toBe("Mapping conversation.");
    expect(conversationActions("mapped").join(" ")).not.toMatch(/Reel/);
    expect(providerLabel(state())).toBe("Local model — demo");
    expect(providerLabel(state())).not.toMatch(/sk-|api_key|127\.0\.0\.1/);
  });

  it("distinguishes provider readiness and local timeout details", () => {
    expect(providerCheckLabel("ready")).toBe("Provider is ready.");
    expect(providerCheckLabel("loading")).toBe("Provider is loading.");
    expect(providerCheckLabel("busy")).toBe("Provider is busy with a semantic request.");
    expect(providerCheckLabel("unavailable")).toBe("Provider is unavailable.");
    expect(providerCheckLabel("failed")).toBe("Provider failed to start.");
    const message = "Local semantic processing timed out. Chunk c0001. Request 2. Elapsed 180s. Timeout 180s. Provider managed-local. Model gemma-3-4b-it.";
    expect(semanticTimeoutSummary(message)).toBe("Local semantic processing timed out.");
    expect(semanticTimeoutDetail(message)).toContain("Chunk c0001");
    expect(semanticTimeoutDetail(message)).not.toContain("transcript");
    expect(semanticTimeoutSummary("The semantic provider took too long.")).toBe("The semantic provider took too long.");
  });

  it("keeps the last conversation state when a status refresh fails", () => {
    const known = state({ map_present: true, threads: [thread], conversation_map_run_id: "run" });
    const failed = conversationDisplay({
      hasMedia: true,
      state: known,
      loaded: true,
      unavailable: true,
      mapping: true,
      failed: false,
    });
    expect(failed.note).toBe("Status temporarily unavailable.");
    expect(failed.headline).toBe("Mapping conversation.");
    expect(failed.provider).toBe("Local model — demo");
    expect(failed.phase).toBe("mapping");
    const unknown = conversationDisplay({
      hasMedia: true,
      state: state({ transcript_present: false, turns_ready: false, provider_configured: false, provider_model_id: null, capability_ready: false }),
      loaded: false,
      unavailable: true,
      mapping: false,
      failed: false,
    });
    expect(unknown.headline).toBe("Status temporarily unavailable.");
    expect(unknown.provider).toBe("Status temporarily unavailable.");
    expect(unknown.headline).not.toBe("Create a transcript to continue.");
    expect(unknown.provider).not.toBe("No semantic provider");
  });
});
