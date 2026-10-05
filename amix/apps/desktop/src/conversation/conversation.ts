/** Conversation workspace state. Times on threads are already derived by the engine. */

import type { ConversationState, ConversationThread } from "../api/types";

export type ConversationPhase =
  | "no_media"
  | "no_transcript"
  | "turns_required"
  | "provider_missing"
  | "offline_blocked"
  | "mapping"
  | "failed"
  | "stale"
  | "mapped"
  | "ready";

export function conversationPhase(input: {
  hasMedia: boolean;
  state: ConversationState | null;
  mapping: boolean;
  failed: boolean;
}): ConversationPhase {
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
  if (!state.provider_configured) {
    return "provider_missing";
  }
  if (state.offline_blocked || !state.capability_ready) {
    return state.offline_blocked ? "offline_blocked" : "provider_missing";
  }
  if (input.mapping) {
    return "mapping";
  }
  if (state.map_present && state.map_stale) {
    return "stale";
  }
  if (state.map_present) {
    return "mapped";
  }
  if (input.failed) {
    return "failed";
  }
  return "ready";
}

export function conversationActions(phase: ConversationPhase): string[] {
  if (phase === "ready" || phase === "failed") {
    return ["Map Conversation"];
  }
  if (phase === "stale" || phase === "mapped") {
    return ["Rebuild Map"];
  }
  return [];
}

export function showExistingThreads(phase: ConversationPhase, threads: readonly ConversationThread[]): boolean {
  return threads.length > 0 && (phase === "mapping" || phase === "stale" || phase === "mapped" || phase === "failed");
}

export function mappingActivity(localAiState: string | null | undefined): string {
  if (localAiState === "STARTING") {
    return "Starting local model.";
  }
  if (localAiState === "LOADING") {
    return "Loading model.";
  }
  return "Mapping conversation.";
}

export function providerCheckLabel(readiness: string | null | undefined): string {
  switch (readiness) {
    case "ready":
      return "Provider is ready.";
    case "loading":
      return "Provider is loading.";
    case "busy":
      return "Provider is busy with a semantic request.";
    case "unavailable":
      return "Provider is unavailable.";
    case "failed":
      return "Provider failed to start.";
    default:
      return "Provider status is unknown.";
  }
}

export function semanticTimeoutSummary(message: string | null | undefined): string {
  if (message?.startsWith("Local semantic processing timed out.")) {
    return "Local semantic processing timed out.";
  }
  return "The semantic provider took too long.";
}

export function semanticTimeoutDetail(message: string | null | undefined): string | null {
  if (!message) {
    return null;
  }
  const extra = message.slice(semanticTimeoutSummary(message).length).trim();
  return extra || null;
}

export function providerLabel(state: ConversationState | null): string {
  if (!state?.provider_model_id) {
    return "No semantic provider";
  }
  const name = state.provider_display_name || "Configured provider";
  return `${name} — ${state.provider_model_id}`;
}

export function threadSeekUs(thread: ConversationThread): number {
  return thread.start_us;
}

export const CONVERSATION_PROFILE = "amix.conversation.map.v1";
