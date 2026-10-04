import type { JobInfo } from "../api/types";
import { isTerminal } from "../api/jobs";

export const DIARIZE_PROFILE = "amix.diarize.mfcc_kmeans.v1";
export const CLUSTER_COUNT = 3;
export const THREE_CLUSTER_LIMIT =
  "This profile separates exactly three anonymous clusters. It does not identify people, and it does not support another speaker count.";

export type SpeakerServerState =
  | "no_participants"
  | "no_transcript"
  | "source_missing"
  | "ready"
  | "clusters_ready"
  | "applied"
  | "stale";

export interface SpeakerChoice {
  clusterKey: string;
  participantId: string | null;
}

export function activeDiarizeJob(jobs: JobInfo[], assetId: string): JobInfo | null {
  return jobs.find((job) => job.kind === "diarize_audio" && job.media_asset_id === assetId && !isTerminal(job.status)) ?? null;
}

export function latestDiarizeJob(jobs: JobInfo[], assetId: string): JobInfo | null {
  const rows = jobs.filter((job) => job.kind === "diarize_audio" && job.media_asset_id === assetId);
  return rows.length === 0 ? null : rows[rows.length - 1];
}

export function presentedSpeakerState(
  server: SpeakerServerState,
  jobs: JobInfo[],
  assetId: string,
): SpeakerServerState | "running" | "failed" {
  if (activeDiarizeJob(jobs, assetId)) {
    return "running";
  }
  const latest = latestDiarizeJob(jobs, assetId);
  if (latest?.status === "FAILED" && (server === "ready" || server === "source_missing")) {
    return "failed";
  }
  return server;
}

export function speakerAnalysisCopy(state: SpeakerServerState | "running" | "failed"): {
  message: string;
  analyzeEnabled: boolean;
  showMapping: boolean;
  applyLabel: string;
  showLimitation: boolean;
} {
  if (state === "no_participants") {
    return { message: "Add people in Media before analyzing speakers.", analyzeEnabled: false, showMapping: false, applyLabel: "Apply speaker mapping", showLimitation: false };
  }
  if (state === "no_transcript") {
    return { message: "Transcribe this media before analyzing speakers.", analyzeEnabled: false, showMapping: false, applyLabel: "Apply speaker mapping", showLimitation: false };
  }
  if (state === "source_missing") {
    return { message: "Relink the source media before a new speaker analysis. Saved analysis stays readable.", analyzeEnabled: false, showMapping: false, applyLabel: "Apply speaker mapping", showLimitation: true };
  }
  if (state === "running") {
    return { message: "Analyzing speakers…", analyzeEnabled: false, showMapping: false, applyLabel: "Apply speaker mapping", showLimitation: true };
  }
  if (state === "failed") {
    return { message: "Speaker analysis failed. The transcript is unchanged.", analyzeEnabled: true, showMapping: false, applyLabel: "Apply speaker mapping", showLimitation: true };
  }
  if (state === "clusters_ready") {
    return { message: "Clusters are ready. Choose who each cluster is.", analyzeEnabled: false, showMapping: true, applyLabel: "Apply speaker mapping", showLimitation: true };
  }
  if (state === "applied") {
    return { message: "Speaker mapping is applied to this transcript.", analyzeEnabled: false, showMapping: true, applyLabel: "Apply speaker mapping", showLimitation: true };
  }
  if (state === "stale") {
    return { message: "Speaker analysis is stale for this transcript.", analyzeEnabled: false, showMapping: true, applyLabel: "Apply speaker mapping to current transcript", showLimitation: true };
  }
  return { message: "Ready to analyze speakers.", analyzeEnabled: true, showMapping: false, applyLabel: "Apply speaker mapping", showLimitation: true };
}

export function canAnalyzeSpeakers(input: {
  role: string;
  sourcePresent: boolean;
  hasTranscript: boolean;
  participantCount: number;
  running: boolean;
}): boolean {
  return input.role === "master"
    && input.sourcePresent
    && input.hasTranscript
    && input.participantCount > 0
    && !input.running;
}

export function representativeSeekUs(startUs: number): number {
  return startUs;
}

export function mappingReady(
  clusterKeys: string[],
  choices: Record<string, string | null | undefined>,
): SpeakerChoice[] | null {
  const mapped: SpeakerChoice[] = [];
  for (const clusterKey of clusterKeys) {
    if (!Object.prototype.hasOwnProperty.call(choices, clusterKey)) {
      return null;
    }
    const participantId = choices[clusterKey];
    if (participantId === undefined) {
      return null;
    }
    mapped.push({ clusterKey, participantId });
  }
  return mapped;
}

export function transcriptSpeakerLabel(word: {
  participant_id: string | null;
  participant_name: string | null;
}): string | null {
  if (word.participant_name) {
    return word.participant_name;
  }
  return null;
}
