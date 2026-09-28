import type { JobInfo, MulticamReadiness, OverlapRegionView, ShotView } from "../api/types";
import { isTerminal } from "../api/jobs";

/** Review actions only. Reaction inserts and manual camera overrides are not part of this workspace. */
export const MULTICAM_CONTROLS = ["analyze_overlap", "build_plan"] as const;

export type MulticamPhase =
  | "no_media"
  | "no_transcript"
  | "speaker_required"
  | "layout_incomplete"
  | "vision_missing"
  | "overlap_running"
  | "ready_overlap"
  | "overlap_stale"
  | "plan_building"
  | "ready_plan"
  | "plan_ready"
  | "plan_stale"
  | "failed";

const PHASE_LABEL: Record<MulticamPhase, string> = {
  no_media: "No media selected",
  no_transcript: "No transcript/turns",
  speaker_required: "Speaker analysis required",
  layout_incomplete: "Layout incomplete",
  vision_missing: "Overlap resource missing",
  overlap_running: "Overlap running",
  ready_overlap: "Ready to analyze overlap",
  overlap_stale: "Overlap analysis required",
  plan_building: "Plan building",
  ready_plan: "Ready to build plan",
  plan_ready: "Plan ready",
  plan_stale: "Plan out of date",
  failed: "Failed",
};

export function phaseLabel(phase: MulticamPhase): string {
  return PHASE_LABEL[phase];
}

export function runningJob(jobs: readonly JobInfo[], assetId: string, kind: string): JobInfo | null {
  return jobs.find((job) => job.kind === kind && job.media_asset_id === assetId && !isTerminal(job.status)) ?? null;
}

export function latestFailure(jobs: readonly JobInfo[], assetId: string): JobInfo | null {
  const failed = jobs.filter((job) => (
    (job.kind === "detect_overlap" || job.kind === "build_multicam_plan")
    && job.media_asset_id === assetId
    && job.status === "FAILED"
  ));
  return failed.length ? failed[failed.length - 1] : null;
}

export function multicamPhase(
  assetId: string | null,
  readiness: MulticamReadiness | null,
  jobs: readonly JobInfo[],
): MulticamPhase {
  if (!assetId) {
    return "no_media";
  }
  if (runningJob(jobs, assetId, "detect_overlap")) {
    return "overlap_running";
  }
  if (runningJob(jobs, assetId, "build_multicam_plan")) {
    return "plan_building";
  }
  if (!readiness) {
    return "failed";
  }
  if (readiness.blocking_reason === "transcript_required") {
    return "no_transcript";
  }
  if (readiness.blocking_reason === "turns_required") {
    return "speaker_required";
  }
  if (!readiness.layout_ready) {
    return "layout_incomplete";
  }
  if (readiness.vision_state !== "READY" && !readiness.overlap_ready && !readiness.overlap_stale) {
    return "vision_missing";
  }
  if (readiness.overlap_stale) {
    return "overlap_stale";
  }
  if (!readiness.overlap_ready) {
    return "ready_overlap";
  }
  if (readiness.plan_stale) {
    return "plan_stale";
  }
  if (readiness.plan_present) {
    return "plan_ready";
  }
  if (readiness.plan_ready) {
    return "ready_plan";
  }
  if (latestFailure(jobs, assetId)) {
    return "failed";
  }
  return "failed";
}

export function shotLabel(shot: Pick<ShotView, "presentation" | "participant_name">): string {
  if (shot.presentation === "full") {
    return `Full — ${shot.participant_name || "Participant"}`;
  }
  if (shot.presentation === "protected_master") {
    return "Protected";
  }
  return "Wide";
}

export function regionSeekUs(region: Pick<OverlapRegionView, "start_us">): number {
  return region.start_us;
}

export function shotSeekUs(shot: Pick<ShotView, "start_us">): number {
  return shot.start_us;
}

/** Local half-open lookup. The playhead is canonical microseconds. */
export function currentShot(shots: readonly ShotView[], playheadUs: number): ShotView | null {
  return shots.find((shot) => shot.start_us <= playheadUs && playheadUs < shot.end_us) ?? null;
}
