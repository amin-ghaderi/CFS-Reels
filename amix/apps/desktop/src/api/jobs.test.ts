import { describe, expect, it } from "vitest";

import { canCancel, canRetry, compactActivityLabel, isTerminal, jobTitle, orderJobs, progressPercent, ACTIVITY_STARTS_OPEN } from "./jobs";
import type { JobInfo } from "./types";

describe("job display helpers", () => {
  it("converts basis points for display only", () => {
    expect(progressPercent(0)).toBe(0);
    expect(progressPercent(5000)).toBe(50);
    expect(progressPercent(10000)).toBe(100);
  });

  it("treats succeeded history as terminal and not cancellable", () => {
    expect(isTerminal("SUCCEEDED")).toBe(true);
    expect(canCancel("SUCCEEDED")).toBe(false);
    expect(canRetry("SUCCEEDED")).toBe(false);
  });

  it("allows cancel while running and retry after failure", () => {
    expect(canCancel("RUNNING")).toBe(true);
    expect(canRetry("FAILED")).toBe(true);
    expect(canRetry("INTERRUPTED")).toBe(true);
    expect(isTerminal("QUEUED")).toBe(false);
  });

  it("names a transcription job for the activity list", () => {
    expect(jobTitle("transcribe")).toBe("Transcribe");
    expect(jobTitle("diarize_audio")).toBe("Analyze speakers");
    expect(jobTitle("detect_overlap")).toBe("Detect overlap");
    expect(jobTitle("build_multicam_plan")).toBe("Build multicam plan");
    expect(jobTitle("map_conversation")).toBe("Map conversation");
    expect(jobTitle("discover_reels")).toBe("Discover reels");
    expect(jobTitle("render_multicam", { preset: "portrait_1080" })).toBe("Render multicam · Portrait 1080");
    expect(jobTitle("render_multicam")).toBe("Render multicam");
    expect(jobTitle("render_sequence", {
      visual_treatment: "source_program",
      render_profile_id: "portrait_1080",
    })).toBe("Render · Source / Program · Portrait 1080");
  });

  it("lists active jobs before terminal history", () => {
    const jobs = [
      job("old-done", "SUCCEEDED", "2020-01-01T00:00:00Z"),
      job("running", "RUNNING", "2020-01-01T00:00:02Z"),
      job("newer-done", "FAILED", "2020-01-01T00:00:03Z"),
      job("queued", "QUEUED", "2020-01-01T00:00:01Z"),
    ];
    expect(orderJobs(jobs).map((item) => item.job_id)).toEqual(["running", "queued", "newer-done", "old-done"]);
  });

  it("keeps activity collapsed and names a running discover or export on the status bar", () => {
    expect(ACTIVITY_STARTS_OPEN).toBe(false);
    expect(compactActivityLabel([])).toBe("No active job");
    expect(compactActivityLabel([
      { kind: "discover_reels", status: "RUNNING", progress_bp: 4200 },
    ])).toBe("Discover reels 42%");
    expect(compactActivityLabel([
      { kind: "render_sequence", status: "RUNNING", progress_bp: 1000, spec: { visual_treatment: "source_program", render_profile_id: "landscape_1080" } },
    ])).toMatch(/^Render · Source \/ Program/);
    expect(compactActivityLabel([
      { kind: "discover_reels", status: "FAILED", progress_bp: 0 },
    ])).toBe("1 failed");
  });
});

function job(id: string, status: JobInfo["status"], createdAt: string): JobInfo {
  return {
    job_id: id,
    project_id: "p",
    media_asset_id: null,
    kind: "project_integrity_check",
    status,
    progress_bp: 0,
    spec: {},
    result: null,
    error_code: null,
    error_message: null,
    created_at: createdAt,
    started_at: null,
    finished_at: null,
    cancel_requested: false,
    attempt: 1,
    resumed_from_job_id: null,
    interrupt_reason: null,
  };
}
