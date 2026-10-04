import type { ExportRecord, JobInfo, MulticamReadiness, OverlapRegionView, ShotView } from "../api/types";
import { isTerminal } from "../api/jobs";

/** Review, one-shot camera overrides, and output render. Reaction inserts are not included. */
export const MULTICAM_CONTROLS = ["analyze_overlap", "build_plan", "override_shot", "render"] as const;

export const OUTPUT_PRESETS = [
  { id: "landscape_1080", format: "16:9", resolution: "1080", label: "Landscape 1080" },
  { id: "landscape_720", format: "16:9", resolution: "720", label: "Landscape 720" },
  { id: "portrait_1080", format: "9:16", resolution: "1080", label: "Portrait 1080" },
  { id: "portrait_720", format: "9:16", resolution: "720", label: "Portrait 720" },
] as const;

export type OutputFormat = "16:9" | "9:16";
export type OutputResolution = "1080" | "720";

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
  no_transcript: "Create a transcript to continue.",
  speaker_required: "Analyze speakers before building multicam.",
  layout_incomplete: "Add people on the layout before building multicam.",
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

export function shotStatus(shot: Pick<ShotView, "locked" | "overridden">): "Protected" | "Overridden" | "Automatic" {
  if (shot.locked) {
    return "Protected";
  }
  return shot.overridden ? "Overridden" : "Automatic";
}

export function automaticLabel(shot: Pick<ShotView, "automatic_presentation" | "automatic_participant_name">): string {
  if (shot.automatic_presentation === "full") {
    return `Full — ${shot.automatic_participant_name || "Participant"}`;
  }
  if (shot.automatic_presentation === "protected_master") {
    return "Protected";
  }
  return "Wide";
}

export function presetId(format: OutputFormat, resolution: OutputResolution): string {
  const orientation = format === "16:9" ? "landscape" : "portrait";
  return `${orientation}_${resolution}`;
}

/** Output choice only. The shot plan run stays the one already built. */
export function renderJobSpec(
  format: OutputFormat,
  resolution: OutputResolution,
  shotPlanRunId: string,
  sequence?: { sequenceId: string; revision: number },
) {
  const profile = presetId(format, resolution);
  if (sequence) {
    return {
      kind: "render_sequence" as const,
      spec: {
        sequence_id: sequence.sequenceId,
        sequence_revision: sequence.revision,
        visual_treatment: "multicam",
        render_profile_id: profile,
      },
    };
  }
  return {
    kind: "render_multicam" as const,
    spec: {
      preset: profile,
      shot_plan_run_id: shotPlanRunId,
    },
  };
}

export function renderBlockReason(input: {
  planPresent: boolean;
  planStale: boolean;
  sourceAvailable: boolean;
  ffmpegReady: boolean;
  presetKnown: boolean;
}): string | null {
  if (!input.sourceAvailable) {
    return "A media file for this project is missing.";
  }
  if (!input.planPresent) {
    return "Build a shot plan before rendering.";
  }
  if (input.planStale) {
    return "The shot plan is out of date.";
  }
  if (!input.ffmpegReady) {
    return "FFmpeg tools are not available.";
  }
  if (!input.presetKnown) {
    return "That output format is not available.";
  }
  return null;
}

export function exportSummary(row: Pick<ExportRecord, "filename" | "width" | "height" | "aspect" | "created_at" | "status">): string {
  const size = row.width && row.height ? `${row.width}×${row.height}` : "size unknown";
  return `${row.filename} · ${size} · ${row.aspect ?? "aspect unknown"} · ${row.created_at ?? ""} · ${row.status}`;
}
