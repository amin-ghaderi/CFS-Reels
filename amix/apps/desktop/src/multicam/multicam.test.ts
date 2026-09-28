import { describe, expect, it } from "vitest";

import type { JobInfo, MulticamReadiness, ShotView } from "../api/types";
import {
  MULTICAM_CONTROLS,
  currentShot,
  multicamPhase,
  phaseLabel,
  regionSeekUs,
  shotLabel,
  shotSeekUs,
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

const shots: ShotView[] = [
  { start_us: 0, end_us: 2_000_000, presentation: "full", participant_id: "a", participant_name: "Alice", reason: "floor" },
  { start_us: 2_000_000, end_us: 4_000_000, presentation: "untouched_wide", participant_id: null, participant_name: null, reason: "overlap" },
  { start_us: 4_000_000, end_us: 5_000_000, presentation: "protected_master", participant_id: null, participant_name: null, reason: "protected" },
];

describe("multicam review", () => {
  it("keeps prerequisite states distinct", () => {
    expect(phaseLabel(multicamPhase(null, null, []))).toBe("No media selected");
    expect(phaseLabel(multicamPhase("m", ready({ blocking_reason: "transcript_required", turns_ready: false, layout_ready: false }), []))).toBe("No transcript/turns");
    expect(phaseLabel(multicamPhase("m", ready({ blocking_reason: "turns_required", turns_ready: false, layout_ready: true }), []))).toBe("Speaker analysis required");
    expect(phaseLabel(multicamPhase("m", ready({ blocking_reason: "insufficient_layout", layout_ready: false }), []))).toBe("Layout incomplete");
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

  it("does not offer reaction shots or manual overrides", () => {
    expect(MULTICAM_CONTROLS).toEqual(["analyze_overlap", "build_plan"]);
    expect(MULTICAM_CONTROLS.join(" ")).not.toMatch(/reaction|override/i);
  });
});
