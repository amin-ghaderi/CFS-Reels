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

export function jobTitle(kind: string): string {
  if (kind === "project_integrity_check") {
    return "Project integrity check";
  }
  return "Background job";
}
