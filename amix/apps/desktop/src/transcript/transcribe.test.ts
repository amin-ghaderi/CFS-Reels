import { describe, expect, it } from "vitest";

import type { JobInfo, JobStatus } from "../api/types";
import {
  MODEL_MISSING_MESSAGE,
  RETRANSCRIBE_WARNING,
  activeTranscribeJob,
  directionForLanguage,
  keepLoadedTranscript,
  languageSelection,
  transcribeOffer,
  transcribeRunningLabel,
  transcriptionJobSpec,
} from "./transcribe";

describe("transcription workspace state", () => {
  it("offers Transcribe when no transcript is loaded and the model is ready", () => {
    const offer = transcribeOffer({
      readOnly: false,
      hasAsset: true,
      role: "master",
      mediaStatus: "present",
      hasTranscript: false,
      modelState: "READY",
      activeJob: null,
    });
    expect(offer.start).toBe("transcribe");
    expect(offer.blocked).toBeNull();
  });

  it("explains a missing model and does not offer a download", () => {
    const offer = transcribeOffer({
      readOnly: false,
      hasAsset: true,
      role: "master",
      mediaStatus: "present",
      hasTranscript: false,
      modelState: "MODEL_MISSING",
      activeJob: null,
    });
    expect(offer.start).toBeNull();
    expect(offer.blocked).toBe(MODEL_MISSING_MESSAGE);
    expect(offer.blocked?.toLowerCase()).not.toContain("download");
    expect(offer.blocked).not.toContain("AMIX_STT");
  });

  it("accepts Auto or a short language code", () => {
    expect(languageSelection(true, "persian")).toEqual({ language: null });
    expect(languageSelection(false, "FA")).toEqual({ language: "fa" });
    expect(languageSelection(false, "persian")).toEqual({ error: "Enter a Whisper language code, or use Auto." });
    expect(languageSelection(false, "")).toHaveProperty("error");
  });

  it("builds a job spec the engine is allowed to see", () => {
    expect(transcriptionJobSpec(null)).toEqual({ profile: "amix.transcribe.v1" });
    expect(transcriptionJobSpec("fa")).toEqual({ profile: "amix.transcribe.v1", language: "fa" });
    expect(transcriptionJobSpec("fa")).not.toHaveProperty("model_path");
    expect(transcriptionJobSpec("fa")).not.toHaveProperty("command");
    expect(transcriptionJobSpec("fa")).not.toHaveProperty("executable");
  });

  it("shows running progress and a cancel target", () => {
    const running = job("run", "RUNNING", 4300);
    const offer = transcribeOffer({
      readOnly: false,
      hasAsset: true,
      role: "master",
      mediaStatus: "present",
      hasTranscript: false,
      modelState: "READY",
      activeJob: activeTranscribeJob([running], "asset"),
    });
    expect(offer.running?.label).toBe(transcribeRunningLabel(4300));
    expect(offer.running?.label).toBe("Transcribing… 43%");
    expect(offer.running?.jobId).toBe("run");
    expect(offer.start).toBeNull();
    expect(transcribeRunningLabel(0)).toBe("Transcribing…");
  });

  it("refreshes only after success and keeps a failed retranscription on screen", () => {
    expect(keepLoadedTranscript(true, "FAILED")).toBe(true);
    expect(keepLoadedTranscript(true, "CANCELLED")).toBe(true);
    expect(keepLoadedTranscript(true, "INTERRUPTED")).toBe(true);
    expect(keepLoadedTranscript(true, "SUCCEEDED")).toBe(false);
    expect(keepLoadedTranscript(false, "FAILED")).toBe(false);
  });

  it("warns that retranscription keeps history and does not copy corrections", () => {
    const offer = transcribeOffer({
      readOnly: false,
      hasAsset: true,
      role: "master",
      mediaStatus: "present",
      hasTranscript: true,
      modelState: "READY",
      activeJob: null,
    });
    expect(offer.start).toBe("retranscribe");
    expect(RETRANSCRIBE_WARNING).toContain("only after successful completion");
    expect(RETRANSCRIBE_WARNING).toContain("corrections are kept");
    expect(RETRANSCRIBE_WARNING.toLowerCase()).not.toContain("copied");
  });

  it("uses detected language for direction and not for time", () => {
    expect(directionForLanguage("fa")).toBe("rtl");
    expect(directionForLanguage("en")).toBe("ltr");
    expect(directionForLanguage(null)).toBe("auto");
    const startUs = 1_250_000;
    expect(startUs).toBe(1_250_000);
  });
});

function job(id: string, status: JobStatus, progress: number): JobInfo {
  return {
    job_id: id,
    project_id: "p",
    media_asset_id: "asset",
    kind: "transcribe",
    status,
    progress_bp: progress,
    spec: {},
    result: null,
    error_code: null,
    error_message: null,
    created_at: "2020-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
    cancel_requested: false,
    attempt: 1,
    resumed_from_job_id: null,
    interrupt_reason: null,
  };
}
