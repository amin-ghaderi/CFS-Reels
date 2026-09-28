import { describe, expect, it } from "vitest";

import { canCancel, canRetry, isTerminal, jobTitle, orderJobs, progressPercent } from "./jobs";
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
