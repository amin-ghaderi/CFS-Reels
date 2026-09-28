import type { JobStatus } from "./types";

const TERMINAL: ReadonlySet<JobStatus> = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "INTERRUPTED",
]);

const CANCELLABLE: ReadonlySet<JobStatus> = new Set(["QUEUED", "RUNNING", "CANCEL_REQUESTED"]);

const RETRYABLE: ReadonlySet<JobStatus> = new Set(["FAILED", "INTERRUPTED", "CANCELLED"]);

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL.has(status);
}

export function canCancel(status: JobStatus): boolean {
  return CANCELLABLE.has(status);
}

export function canRetry(status: JobStatus): boolean {
  return RETRYABLE.has(status);
}

/** Display-only. 5000 basis points is 50 percent. Persistence stays in basis points. */
export function progressPercent(progressBp: number): number {
  if (!Number.isInteger(progressBp) || progressBp <= 0) {
    return 0;
  }
  if (progressBp >= 10000) {
    return 100;
  }
  return Math.floor(progressBp / 100);
}

export function jobStatusLabel(status: JobStatus): string {
  switch (status) {
    case "QUEUED":
      return "Queued";
    case "RUNNING":
      return "Running";
    case "SUCCEEDED":
      return "Succeeded";
    case "FAILED":
      return "Failed";
    case "CANCEL_REQUESTED":
      return "Cancel requested";
    case "CANCELLED":
      return "Cancelled";
    case "INTERRUPTED":
      return "Interrupted";
  }
}

/** Active work stays ahead of history. Persisted order is unchanged. */
export function orderJobs<T extends { status: JobStatus; created_at: string; job_id: string }>(jobs: readonly T[]): T[] {
  const newest = (left: T, right: T) => {
    const byTime = right.created_at.localeCompare(left.created_at);
    return byTime === 0 ? right.job_id.localeCompare(left.job_id) : byTime;
  };
  return [
    ...jobs.filter((job) => !isTerminal(job.status)).sort(newest),
    ...jobs.filter((job) => isTerminal(job.status)).sort(newest),
  ];
}

export function jobTitle(kind: string): string {
  if (kind === "project_integrity_check") {
    return "Project integrity check";
  }
  if (kind === "media_probe") {
    return "Analyze media";
  }
  if (kind === "generate_proxy") {
    return "Generate proxy";
  }
  if (kind === "transcribe") {
    return "Transcribe";
  }
  if (kind === "diarize_audio") {
    return "Analyze speakers";
  }
  return "Background job";
}
