import { describe, expect, it } from "vitest";

import type { JobInfo } from "../api/types";
import {
  CLUSTER_COUNT,
  THREE_CLUSTER_LIMIT,
  canAnalyzeSpeakers,
  mappingReady,
  presentedSpeakerState,
  representativeSeekUs,
  speakerAnalysisCopy,
  transcriptSpeakerLabel,
} from "./speakers";

function job(partial: Partial<JobInfo> & Pick<JobInfo, "status" | "kind">): JobInfo {
  return {
    job_id: partial.job_id ?? "job",
    project_id: "p",
    media_asset_id: partial.media_asset_id ?? "asset",
    kind: partial.kind,
    status: partial.status,
    progress_bp: partial.progress_bp ?? 0,
    spec: {},
    result: null,
    error_code: partial.error_code ?? null,
    error_message: null,
    created_at: "t",
    started_at: null,
    finished_at: null,
    cancel_requested: false,
    attempt: 1,
    resumed_from_job_id: null,
    interrupt_reason: null,
  };
}

describe("speaker analysis", () => {
  it("states the three-cluster limit and the prerequisites", () => {
    expect(CLUSTER_COUNT).toBe(3);
    expect(THREE_CLUSTER_LIMIT).toMatch(/three anonymous clusters/);
    expect(THREE_CLUSTER_LIMIT.toLowerCase()).not.toMatch(/two-person|two person/);
    expect(canAnalyzeSpeakers({
      role: "master",
      sourcePresent: true,
      hasTranscript: true,
      participantCount: 1,
      running: false,
    })).toBe(true);
    expect(canAnalyzeSpeakers({
      role: "master",
      sourcePresent: true,
      hasTranscript: false,
      participantCount: 1,
      running: false,
    })).toBe(false);
    const ready = speakerAnalysisCopy("ready");
    expect(ready.analyzeEnabled).toBe(true);
    expect(ready.showLimitation).toBe(true);
    expect(speakerAnalysisCopy("no_participants").analyzeEnabled).toBe(false);
    expect(speakerAnalysisCopy("no_transcript").message).toMatch(/Transcribe/);
  });

  it("shows a running job and a failed attempt without hiding the transcript", () => {
    const jobs = [job({ kind: "diarize_audio", status: "RUNNING", progress_bp: 2500 })];
    expect(presentedSpeakerState("ready", jobs, "asset")).toBe("running");
    expect(speakerAnalysisCopy("running").message).toMatch(/Analyzing speakers/);
    expect(speakerAnalysisCopy("failed").message).toMatch(/transcript is unchanged/);
  });

  it("maps every cluster, including Unknown, and seeks a sample by canonical time", () => {
    expect(mappingReady(["SPEAKER_00", "SPEAKER_01"], { SPEAKER_00: "p1" })).toBeNull();
    expect(mappingReady(["SPEAKER_00"], { SPEAKER_00: null })).toEqual([
      { clusterKey: "SPEAKER_00", participantId: null },
    ]);
    expect(mappingReady(["SPEAKER_00", "SPEAKER_01"], { SPEAKER_00: "p1", SPEAKER_01: "p1" })).toEqual([
      { clusterKey: "SPEAKER_00", participantId: "p1" },
      { clusterKey: "SPEAKER_01", participantId: "p1" },
    ]);
    expect(representativeSeekUs(5_100_000)).toBe(5_100_000);
  });

  it("shows a participant name or Unknown, and hides a stale label", () => {
    expect(transcriptSpeakerLabel({ participant_id: "p", participant_name: "Ava" })).toBe("Ava");
    expect(transcriptSpeakerLabel({ participant_id: null, participant_name: "Unknown" })).toBe("Unknown");
    expect(transcriptSpeakerLabel({ participant_id: null, participant_name: null })).toBeNull();
    expect(speakerAnalysisCopy("stale").applyLabel).toMatch(/current transcript/);
    expect(speakerAnalysisCopy("applied").message).toMatch(/applied/);
    expect(presentedSpeakerState("stale", [], "asset")).toBe("stale");
  });
});
