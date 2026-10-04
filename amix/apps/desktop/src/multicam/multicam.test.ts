import { describe, expect, it } from "vitest";

import type { ExportRecord, JobInfo, MulticamReadiness, ShotView } from "../api/types";
import {
  MULTICAM_CONTROLS,
  OUTPUT_PRESETS,
  automaticLabel,
  currentShot,
  exportSummary,
  multicamPhase,
  phaseLabel,
  regionSeekUs,
  renderBlockReason,
  renderJobSpec,
  shotLabel,
  shotSeekUs,
  shotStatus,
} from "./multicam";

function ready(patch: Partial<MulticamReadiness> = {}): MulticamReadiness {
  return {
    turns_ready: true,
    overlap_ready: false,
    overlap_stale: false,
    layout_ready: true,
    plan_ready: false,
    plan_present: false,
    plan_stale: false,
    blocking_reason: "overlap_required",
    vision_state: "READY",
    ffmpeg_ready: true,
    plan_start_us: null,
    plan_end_us: null,
    ...patch,
  };
}

function job(patch: Partial<JobInfo>): JobInfo {
  return {
    job_id: "j",
    project_id: "p",
    media_asset_id: "m",
    kind: "detect_overlap",
    status: "RUNNING",
    progress_bp: 1000,
    spec: {},
    result: null,
    error_code: null,
    error_message: null,
    created_at: "t",
    started_at: "t",
    finished_at: null,
    cancel_requested: false,
    attempt: 1,
    resumed_from_job_id: null,
    interrupt_reason: null,
    ...patch,
  };
}

function shot(patch: Partial<ShotView> & Pick<ShotView, "start_us" | "end_us" | "presentation" | "reason">): ShotView {
  return {
    shot_id: patch.reason,
    participant_id: null,
    participant_name: null,
    automatic_presentation: patch.presentation,
    automatic_participant_id: null,
    automatic_participant_name: null,
    override_decision: "auto",
    locked: patch.presentation === "protected_master",
    overridden: false,
    full_choices: [],
    ...patch,
  };
}

const shots: ShotView[] = [
  shot({
    shot_id: "s1", start_us: 0, end_us: 2_000_000, presentation: "full", reason: "floor",
    participant_id: "a", participant_name: "Alice",
    automatic_participant_id: "a", automatic_participant_name: "Alice",
    full_choices: [{ participant_id: "a", display_name: "Alice" }, { participant_id: "b", display_name: "Bea" }],
  }),
  shot({
    shot_id: "s2", start_us: 2_000_000, end_us: 4_000_000, presentation: "untouched_wide", reason: "overlap",
    full_choices: [{ participant_id: "a", display_name: "Alice" }],
  }),
  shot({
    shot_id: "s3", start_us: 4_000_000, end_us: 5_000_000, presentation: "protected_master", reason: "protected",
    locked: true,
  }),
];

describe("multicam review", () => {
  it("keeps prerequisite states distinct", () => {
    expect(phaseLabel(multicamPhase(null, null, []))).toBe("No media selected");
    expect(phaseLabel(multicamPhase("m", ready({ blocking_reason: "transcript_required", turns_ready: false, layout_ready: false }), []))).toBe("Create a transcript to continue.");
    expect(phaseLabel(multicamPhase("m", ready({ blocking_reason: "turns_required", turns_ready: false, layout_ready: true }), []))).toBe("Analyze speakers before building multicam.");
    expect(phaseLabel(multicamPhase("m", ready({ blocking_reason: "insufficient_layout", layout_ready: false }), []))).toBe("Add people on the layout before building multicam.");
    expect(phaseLabel(multicamPhase("m", ready({ vision_state: "MODEL_MISSING" }), []))).toBe("Overlap resource missing");
    expect(phaseLabel(multicamPhase("m", ready(), []))).toBe("Ready to analyze overlap");
    expect(phaseLabel(multicamPhase("m", ready(), [job({})]))).toBe("Overlap running");
    expect(phaseLabel(multicamPhase("m", ready({ overlap_ready: true, plan_ready: true, blocking_reason: null }), []))).toBe("Ready to build plan");
    expect(phaseLabel(multicamPhase("m", ready({ overlap_ready: true, plan_ready: true, plan_present: true, blocking_reason: null }), [job({ kind: "build_multicam_plan" })]))).toBe("Plan building");
    expect(phaseLabel(multicamPhase("m", ready({ overlap_ready: true, plan_ready: true, plan_present: true, blocking_reason: null }), []))).toBe("Plan ready");
    expect(phaseLabel(multicamPhase("m", ready({ overlap_ready: true, plan_ready: true, plan_present: true, plan_stale: true, blocking_reason: null }), []))).toBe("Plan out of date");
  });

  it("labels shots with participant names and product words", () => {
    expect(shotLabel(shots[0])).toBe("Full — Alice");
    expect(shotLabel(shots[1])).toBe("Wide");
    expect(shotLabel(shots[2])).toBe("Protected");
    expect(shotLabel(shots[0])).not.toContain("FULL_");
  });

  it("seeks a region or shot to its canonical start and follows the playhead locally", () => {
    expect(regionSeekUs({ start_us: 2_960_000_000 })).toBe(2_960_000_000);
    expect(shotSeekUs(shots[1])).toBe(2_000_000);
    expect(currentShot(shots, 0)?.reason).toBe("floor");
    expect(currentShot(shots, 2_000_000)?.reason).toBe("overlap");
    expect(currentShot(shots, 4_999_999)?.reason).toBe("protected");
    expect(currentShot(shots, 5_000_000)).toBeNull();
  });

  it("offers a shot override and a render, and does not offer reaction shots", () => {
    expect(MULTICAM_CONTROLS).toEqual(["analyze_overlap", "build_plan", "override_shot", "render"]);
    expect(MULTICAM_CONTROLS.join(" ")).not.toMatch(/reaction/i);
  });

  it("keeps override choices on the current shot and locks protected shots", () => {
    expect(shotStatus(shots[0])).toBe("Automatic");
    expect(automaticLabel(shots[0])).toBe("Full — Alice");
    expect(shots[0].full_choices.map((choice) => choice.display_name)).toEqual(["Alice", "Bea"]);
    expect(shots[1].full_choices.map((choice) => choice.participant_id)).toEqual(["a"]);
    const overridden = { ...shots[1], presentation: "full", participant_name: "Alice", override_decision: "full", overridden: true };
    const cleared = { ...overridden, override_decision: "auto", overridden: false };
    expect(shotStatus(overridden)).toBe("Overridden");
    expect(shotStatus(cleared)).toBe("Automatic");
    expect(shotStatus(shots[2])).toBe("Protected");
    expect(shots[2].locked).toBe(true);
    expect(shots[2].full_choices).toEqual([]);
  });

  it("treats 16:9 and 9:16 as output presets on the same shot plan", () => {
    expect(OUTPUT_PRESETS.map((preset) => preset.format)).toEqual(["16:9", "16:9", "9:16", "9:16"]);
    expect(OUTPUT_PRESETS.map((preset) => preset.resolution)).toEqual(["1080", "720", "1080", "720"]);
    const sequence = { sequenceId: "seq-1", revision: 4 };
    const landscape = renderJobSpec("16:9", "1080", "plan-1", sequence);
    const portrait = renderJobSpec("9:16", "720", "plan-1", sequence);
    expect(landscape.kind).toBe("render_sequence");
    expect(portrait.kind).toBe("render_sequence");
    expect(landscape.spec.sequence_id).toBe("seq-1");
    expect(portrait.spec.sequence_id).toBe(landscape.spec.sequence_id);
    expect(portrait.spec.sequence_revision).toBe(4);
    expect(landscape.spec.sequence_revision).toBe(portrait.spec.sequence_revision);
    expect(landscape.spec.visual_treatment).toBe("multicam");
    expect(portrait.spec.visual_treatment).toBe("multicam");
    expect(landscape.spec.render_profile_id).toBe("landscape_1080");
    expect(portrait.spec.render_profile_id).toBe("portrait_720");
    expect(landscape.kind).not.toBe("build_multicam_plan");
    expect(renderBlockReason({
      planPresent: true, planStale: true, sourceAvailable: true, ffmpegReady: true, presetKnown: true,
    })).toMatch(/out of date/);
    expect(renderBlockReason({
      planPresent: true, planStale: false, sourceAvailable: false, ffmpegReady: true, presetKnown: true,
    })).toMatch(/missing/);
    expect(renderBlockReason({
      planPresent: true, planStale: false, sourceAvailable: true, ffmpegReady: true, presetKnown: true,
    })).toBeNull();
  });

  it("names a completed export without starting another plan", () => {
    const row: ExportRecord = {
      job_id: "job", filename: "job.mp4", relative_path: "exports/job.mp4",
      width: 1080, height: 1920, aspect: "9:16", preset_id: "portrait_1080",
      created_at: "2026-09-28T12:00:00+00:00", status: "succeeded",
    };
    expect(exportSummary(row)).toContain("1080×1920");
    expect(exportSummary(row)).toContain("9:16");
    expect(exportSummary(row)).toContain("succeeded");
    expect(renderJobSpec("9:16", "1080", "plan-1").kind).toBe("render_multicam");
  });
});
