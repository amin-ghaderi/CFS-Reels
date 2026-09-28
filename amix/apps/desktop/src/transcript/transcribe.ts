import type { JobInfo, JobStatus, SpeechModelState } from "../api/types";
import { isTerminal, progressPercent } from "../api/jobs";
import { transcriptDir } from "./text";

export const TRANSCRIBE_PROFILE = "amix.transcribe.v1";

export const RETRANSCRIBE_WARNING =
  "A new transcript version will become active only after successful completion. Existing transcript history and corrections are kept.";

export const MODEL_MISSING_MESSAGE = "Speech model not installed.";
export const INVALID_MODEL_MESSAGE = "The configured speech model cannot be used.";
export const RUNTIME_UNAVAILABLE_MESSAGE = "The speech runtime is not available.";
export const SOURCE_MISSING_MESSAGE = "The original media is missing. Relink it before transcribing.";
export const SOURCE_ROLE_MESSAGE = "Transcription uses the original source media.";

export interface TranscribeOffer {
  start: "transcribe" | "retranscribe" | null;
  blocked: string | null;
  running: { jobId: string; label: string } | null;
}

export function transcriptionJobSpec(language: string | null): Record<string, string> {
  const spec: Record<string, string> = { profile: TRANSCRIBE_PROFILE };
  if (language) {
    spec.language = language;
  }
  return spec;
}

export function languageSelection(
  auto: boolean,
  code: string,
): { language: string | null } | { error: string } {
  if (auto) {
    return { language: null };
  }
  const trimmed = code.trim().toLowerCase();
  if (!/^[a-z]{2,3}$/.test(trimmed)) {
    return { error: "Enter a Whisper language code, or use Auto." };
  }
  return { language: trimmed };
}

export function transcribeRunningLabel(progressBp: number): string {
  if (!Number.isInteger(progressBp) || progressBp <= 0) {
    return "Transcribing…";
  }
  return `Transcribing… ${progressPercent(progressBp)}%`;
}

export function activeTranscribeJob(
  jobs: readonly Pick<JobInfo, "job_id" | "kind" | "status" | "media_asset_id" | "progress_bp" | "created_at">[],
  assetId: string,
): { jobId: string; progressBp: number } | null {
  const active = jobs
    .filter((job) => job.kind === "transcribe" && job.media_asset_id === assetId && !isTerminal(job.status))
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
  const job = active[0];
  if (!job) {
    return null;
  }
  return { jobId: job.job_id, progressBp: job.progress_bp };
}

/** A failed or cancelled attempt must not replace the transcript already on screen. */
export function keepLoadedTranscript(hasTranscript: boolean, status: JobStatus): boolean {
  return hasTranscript && status !== "SUCCEEDED";
}

export function transcribeOffer(input: {
  readOnly: boolean;
  hasAsset: boolean;
  role: string | null;
  mediaStatus: "present" | "missing" | null;
  hasTranscript: boolean;
  modelState: SpeechModelState | null;
  activeJob: { jobId: string; progressBp: number } | null;
}): TranscribeOffer {
  if (!input.hasAsset) {
    return { start: null, blocked: null, running: null };
  }
  if (input.activeJob) {
    return {
      start: null,
      blocked: null,
      running: { jobId: input.activeJob.jobId, label: transcribeRunningLabel(input.activeJob.progressBp) },
    };
  }
  if (input.readOnly) {
    return { start: null, blocked: "This project is open read-only.", running: null };
  }
  if (input.role !== "master") {
    return { start: null, blocked: SOURCE_ROLE_MESSAGE, running: null };
  }
  if (input.mediaStatus !== "present") {
    return { start: null, blocked: SOURCE_MISSING_MESSAGE, running: null };
  }
  if (input.modelState === null) {
    return { start: null, blocked: null, running: null };
  }
  if (input.modelState === "MODEL_MISSING") {
    return { start: null, blocked: MODEL_MISSING_MESSAGE, running: null };
  }
  if (input.modelState === "INVALID_MODEL") {
    return { start: null, blocked: INVALID_MODEL_MESSAGE, running: null };
  }
  if (input.modelState === "RUNTIME_UNAVAILABLE") {
    return { start: null, blocked: RUNTIME_UNAVAILABLE_MESSAGE, running: null };
  }
  return {
    start: input.hasTranscript ? "retranscribe" : "transcribe",
    blocked: null,
    running: null,
  };
}

export function directionForLanguage(language: string | null): "ltr" | "rtl" | "auto" {
  return transcriptDir(language);
}
